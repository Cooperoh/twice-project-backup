from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import queue
import socket
import time
from types import SimpleNamespace

import pytest

from backend.config import DroneTarget, load_settings
from backend.commands import CommandService
from backend.events import WebSocketHub
from backend.models import BasicCommandRequest, FormationCommandRequest
from backend.state import StateStore
from backend.udp import UDPService, UDPUnavailable


@pytest.mark.asyncio
async def test_listed_routing_distinct_ips_disconnected_drone_and_command_scopes(
    config_path, tmp_path, monkeypatch,
) -> None:
    # Two real loopback peers share a control port on different IPs. The third
    # peer has a configured destination but never sends telemetry.
    peers: list[socket.socket] = []
    now = [100.0]
    monkeypatch.setattr("backend.state.time", SimpleNamespace(
        monotonic=lambda: now[0], perf_counter=time.perf_counter,
    ))
    try:
        for host, port in (("127.0.0.1", 0), ("127.0.0.2", None), ("127.0.0.1", 0)):
            peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            peers.append(peer)
            peer.bind((host, peers[0].getsockname()[1] if port is None else port))
            peer.setblocking(False)
        endpoints = tuple(
            DroneTarget(drone_id, *peer.getsockname())
            for drone_id, peer in zip((7, 2, 24), peers)
        )
        base = load_settings(config_path)
        settings = replace(base, udp=replace(
            base.udp, bind_host="127.0.0.1", bind_port=0, targets=endpoints,
        ))
        store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
        service = UDPService(settings, store, audit_dir=tmp_path)
        commands = CommandService(store, service)
        loop = asyncio.get_running_loop()

        async def received(index):
            data, _ = await asyncio.wait_for(loop.sock_recvfrom(peers[index], 4096), 1)
            return json.loads(data)

        def empty(index):
            with pytest.raises(BlockingIOError):
                peers[index].recvfrom(4096)

        await service.start()
        try:
            # No peers are listed at startup; even abort must not fan out.
            with pytest.raises(UDPUnavailable, match="没有地面站列表中的"):
                await commands.abort()
            assert await store.is_command_blocked()
            await commands.resume()
            assert store.enqueue_message({"type": "log", "id": 7, "text": "hello"})
            assert not store.enqueue_message({"type": "telemetry", "id": 25})
            assert not store.enqueue_message({"type": "unknown", "id": 2})
            assert await store.listed_drone_ids() == set()
            for index in range(3):
                empty(index)

            # Apply telemetry to the same authoritative list shown by the ground station.
            for drone_id in (7, 2):
                assert await store.handle_message({"type": "telemetry", "id": drone_id})
            assert set((await store.snapshot())["drones"]) == {"2", "7"}
            global_dispatch = await service.send_json({"cmd": "mission"})
            assert len(global_dispatch["targets"]) == 2
            assert await received(0) == await received(1) == {"cmd": "mission"}
            empty(2)

            payload = {"cmd": "test_vo", "targets": [24, 7, 7]}
            result = await service.send_json(payload)
            assert len(result["targets"]) == 1
            assert await received(0) == payload
            empty(0)  # Duplicate ID is sent only once.
            empty(1)
            empty(2)
            for targets in ([], [24]):
                with pytest.raises(UDPUnavailable, match="没有地面站列表中的"):
                    await service.send_json({"cmd": "mission", "targets": targets})
            with pytest.raises(UDPUnavailable, match="不在地面站列表中"):
                await service.send_json_to_drone({"cmd": "config_update", "id": 24}, 24)

            # Group commands reach only its listed members. Membership and
            # leader order in the protocol are not silently rewritten.
            await store.update_formations((await store.snapshot())["formations"]["revision"],
                {0: [7, 24], 1: [2], 2: [], 3: []},
                {0: 7, 1: 2, 2: None, 3: None},
            )
            await commands.send_basic(BasicCommandRequest(command="land", group=0))
            assert await received(0) == {"cmd": "land", "targets": [7, 24], "group": 0}
            await commands.send_formation(FormationCommandRequest(group=0))
            form_type, spacing = await store.formation_settings()
            assert await received(0) == {
                "cmd": "formation_start", "group": 0, "targets": [7, 24],
                "form_type": form_type, "spacing": spacing,
            }
            empty(0)  # One complete start packet; no preceding set or duplicate start.
            empty(1)
            empty(2)

            await commands.config_update_for_drone(2, 1, True)
            assert (await received(1))["id"] == 2
            empty(0)
            await commands.abort()
            assert await received(0) == await received(1) == {"cmd": "abort"}
            empty(2)

            # Both aircraft show disconnected but remain in the list, so
            # global, group, and single-drone commands must still reach them.
            now[0] += settings.telemetry.disconnected_seconds + 1
            assert await store.listed_drone_ids() == {2, 7}
            drones = (await store.snapshot())["drones"]
            assert all(drone["telemetry_status"] == "disconnected" for drone in drones.values())
            await commands.abort()
            assert await received(0) == await received(1) == {"cmd": "abort"}
            await commands.resume()
            await commands.send_basic(BasicCommandRequest(command="land", group=0))
            assert (await received(0))["cmd"] == "land"
            await commands.config_update_for_drone(2, 1, True)
            assert (await received(1))["cmd"] == "config_update"
            empty(2)

            # A heartbeat changes displayed connectivity, not recipient scope.
            await store.handle_message({"type": "telemetry", "id": 2})
            await service.send_json({"cmd": "mission"})
            assert await received(0) == await received(1) == {"cmd": "mission"}
            empty(2)

            # An observed ID without a configured address never falls back to
            # a shared host or a port derived from the ID.
            await store.handle_message({"type": "telemetry", "id": 23})
            with pytest.raises(UDPUnavailable, match="#23 未配置控制地址"):
                await service.send_json({"cmd": "mission", "targets": [23]})
            for index in range(3):
                empty(index)
        finally:
            await service.stop()
            await store.stop()
        records = [json.loads(line) for line in next(tmp_path.glob("sent-*.jsonl")).read_text(encoding="utf-8").splitlines()]
        assert {record["target"]["id"] for record in records} == {2, 7}
        assert {record["target"]["host"] for record in records} == {"127.0.0.1", "127.0.0.2"}
    finally:
        for peer in peers:
            peer.close()


@pytest.mark.asyncio
async def test_loopback_udp_threads_and_permanent_audit(config_path, tmp_path) -> None:
    receivers: list[socket.socket] = []
    try:
        target_ports: list[int] = []
        for _ in range(24):
            receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            receiver.bind(("127.0.0.1", 0))
            receiver.setblocking(False)
            receivers.append(receiver)
            target_ports.append(receiver.getsockname()[1])

        base = load_settings(config_path)
        settings = replace(
            base,
            udp=replace(
                base.udp,
                bind_host="127.0.0.1",
                bind_port=0,
                targets=tuple(
                    DroneTarget(i, "127.0.0.1", port)
                    for i, port in enumerate(target_ports, 1)
                ),
            ),
        )
        store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
        service = UDPService(settings, store, audit_dir=tmp_path)
        await store.start()
        await service.start()
        try:
            diagnostics = service.diagnostics()
            assert diagnostics["receiver_thread_alive"] is True
            assert diagnostics["sender_thread_alive"] is True
            receive_port = diagnostics["receiver_port"]
            assert isinstance(receive_port, int)

            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sender.sendto(b"\xff\xfe", ("127.0.0.1", receive_port))
                sender.sendto(b"{not-json", ("127.0.0.1", receive_port))
                sender.sendto(
                    json.dumps(
                        {"type": "telemetry", "id": 7, "lat": 38.3, "lon": 117.6}
                    ).encode("utf-8"),
                    ("127.0.0.1", receive_port),
                )
            finally:
                sender.close()

            for _ in range(50):
                if "7" in (await store.snapshot())["drones"]:
                    break
                await asyncio.sleep(0.01)
            assert (await store.snapshot())["drones"]["7"]["lat"] == 38.3

            dispatch = await service.send_json({"cmd": "mission"})
            assert all(result["sent"] for result in dispatch["targets"])
            loop = asyncio.get_running_loop()
            assert len(dispatch["targets"]) == 1
            data, _ = await asyncio.wait_for(loop.sock_recvfrom(receivers[6], 4096), 1.0)
            assert json.loads(data.decode("utf-8")) == {"cmd": "mission"}
            for index, receiver in enumerate(receivers):
                if index != 6:
                    with pytest.raises(BlockingIOError):
                        receiver.recvfrom(4096)

            targeted = await service.send_json_to_drone(
                {"cmd": "config_update", "id": 7},
                7,
            )
            assert targeted["targets"][0]["port"] == target_ports[6]
            data, _ = await asyncio.wait_for(
                loop.sock_recvfrom(receivers[6], 4096),
                1.0,
            )
            assert json.loads(data.decode("utf-8"))["cmd"] == "config_update"
            for invalid_id in (0, 25):
                with pytest.raises(ValueError, match=r"outside 1\.\.24"):
                    await service.send_json_to_drone(
                        {"cmd": "config_update", "id": invalid_id},
                        invalid_id,
                    )
        finally:
            await service.stop()
            await store.stop()

        stopped = service.diagnostics()
        assert stopped["receiver_thread_alive"] is False
        assert stopped["sender_thread_alive"] is False

        received_files = list(tmp_path.glob("received-*.jsonl"))
        sent_files = list(tmp_path.glob("sent-*.jsonl"))
        assert len(received_files) == len(sent_files) == 1
        received_records = [
            json.loads(line)
            for line in received_files[0].read_text(encoding="utf-8").splitlines()
        ]
        assert len(received_records) == 3
        assert [record["parse_status"] for record in received_records] == [
            "invalid_utf8",
            "invalid_json",
            "accepted",
        ]
        assert all(record["timestamp"].endswith("Z") for record in received_records)
        assert all(record["remote"]["host"] == "127.0.0.1" for record in received_records)
        assert "raw_base64" in received_records[0]
        assert received_records[1]["raw"] == "{not-json"
        assert json.loads(received_records[2]["raw"]) == {
            "type": "telemetry", "id": 7, "lat": 38.3, "lon": 117.6
        }
        sent_records = [
            json.loads(line)
            for line in sent_files[0].read_text(encoding="utf-8").splitlines()
        ]
        assert len(sent_records) == 2
        assert all(record["target"]["id"] == 7 for record in sent_records)
        assert all(json.loads(record["raw"])["cmd"] for record in sent_records)
        assert all(record["sendto_result"] == record["bytes"] for record in sent_records)
        assert all(record["sent"] is True and record["error"] is None for record in sent_records)

        old_received = received_files[0].read_bytes()
        old_sent = sent_files[0].read_bytes()
        restart_store = StateStore(
            settings,
            WebSocketHub(settings.limits.websocket_queue),
        )
        restart_service = UDPService(settings, restart_store, audit_dir=tmp_path)
        await restart_store.start()
        await restart_service.start()
        await restart_service.stop()
        await restart_store.stop()
        assert len(list(tmp_path.glob("received-*.jsonl"))) == 2
        assert len(list(tmp_path.glob("sent-*.jsonl"))) == 2
        assert received_files[0].read_bytes() == old_received
        assert sent_files[0].read_bytes() == old_sent
    finally:
        for receiver in receivers:
            receiver.close()


@pytest.mark.asyncio
async def test_send_queue_full_and_timeout_are_bounded_and_never_retried(
    config_path,
    tmp_path,
) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))

    # Add a real entry to the ground-station list before testing the send queue.
    assert await store.handle_message({"type": "telemetry", "id": 1})

    full_service = UDPService(settings, store, audit_dir=tmp_path / "full")
    full_queue: queue.Queue[object] = queue.Queue(maxsize=settings.limits.send_queue)
    for _ in range(settings.limits.send_queue):
        full_queue.put_nowait(object())
    full_service._sender = SimpleNamespace(  # type: ignore[assignment]
        socket=object(),
        requests=full_queue,
        is_alive=lambda: True,
    )
    with pytest.raises(UDPUnavailable, match="send queue is full"):
        await full_service.send_json({"cmd": "abort"})
    assert full_queue.qsize() == settings.limits.send_queue

    timeout_service = UDPService(
        settings,
        store,
        audit_dir=tmp_path / "timeout",
        send_timeout_seconds=0.01,
    )
    timeout_queue: queue.Queue[object] = queue.Queue(
        maxsize=settings.limits.send_queue
    )
    timeout_service._sender = SimpleNamespace(  # type: ignore[assignment]
        socket=object(),
        requests=timeout_queue,
        is_alive=lambda: True,
    )
    with pytest.raises(UDPUnavailable, match="outcome is unknown.*not be retried"):
        await timeout_service.send_json_to_drone({"cmd": "takeoff"}, 1)
    assert timeout_queue.qsize() == 1
    pending = timeout_queue.get_nowait()
    assert pending.payload == {"cmd": "takeoff"}
    assert pending.targets == (settings.udp.targets[0],)
    assert not pending.future.done()
    pending.future.set_result({"payload": pending.payload, "targets": []})
    await asyncio.sleep(0)
    assert timeout_queue.empty()


@pytest.mark.asyncio
async def test_audit_open_failure_degrades_health_without_blocking_udp(
    config_path,
    tmp_path,
) -> None:
    target = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target.bind(("127.0.0.1", 0))
    target.setblocking(False)
    blocker = tmp_path / "audit-is-a-file"
    blocker.write_text("not a directory", encoding="utf-8")

    base = load_settings(config_path)
    settings = replace(
        base,
        udp=replace(
            base.udp,
            bind_host="127.0.0.1",
            bind_port=0,
            targets=(DroneTarget(1, "127.0.0.1", target.getsockname()[1]),),
        ),
    )
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    service = UDPService(settings, store, audit_dir=blocker)
    await store.start()
    await service.start()
    try:
        health = await store.udp_health()
        assert health["audit_ready"] is False
        assert isinstance(health["audit_last_error"], str)
        assert "audit" in health["audit_last_error"]
        diagnostics = service.diagnostics()
        assert diagnostics["receiver_thread_alive"] is True
        assert diagnostics["sender_thread_alive"] is True
        assert diagnostics["audit"]["received"]["healthy"] is False
        assert diagnostics["audit"]["sent"]["healthy"] is False

        await store.handle_message({"type": "telemetry", "id": 1})
        dispatch = await service.send_json({"cmd": "abort"})
        assert dispatch["targets"][0]["sent"] is True
        loop = asyncio.get_running_loop()
        data, _ = await asyncio.wait_for(loop.sock_recvfrom(target, 4096), 1.0)
        assert json.loads(data.decode("utf-8")) == {"cmd": "abort"}

        receive_port = diagnostics["receiver_port"]
        uplink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            uplink.sendto(
                json.dumps(
                    {"type": "telemetry", "id": 1, "lat": 38.3, "lon": 117.6}
                ).encode("utf-8"),
                ("127.0.0.1", receive_port),
            )
        finally:
            uplink.close()
        for _ in range(50):
            if (await store.snapshot())["drones"].get("1", {}).get("lat") == 38.3:
                break
            await asyncio.sleep(0.01)
        assert (await store.snapshot())["drones"]["1"]["lat"] == 38.3
    finally:
        await service.stop()
        await store.stop()
        target.close()
