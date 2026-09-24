from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.commands import CommandBlockedError, CommandService
from backend.config import load_settings
from backend.events import WebSocketHub
from backend.models import BasicCommandRequest, FormationCommandRequest, WorkbenchCommandRequest
from backend.state import StateStore
from backend.udp import UDPUnavailable


class RecordingSender:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.broadcast_payloads: list[dict[str, Any]] = []
        self.targeted_drone_ids: list[int] = []

    async def send_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        self.broadcast_payloads.append(payload)
        return {
            "payload": payload,
            "targets": [
                {"host": "127.0.0.1", "port": 1, "sent": True, "error": None}
            ],
        }

    async def send_json_to_drone(
        self,
        payload: dict[str, Any],
        drone_id: int,
    ) -> dict[str, Any]:
        self.payloads.append(payload)
        self.targeted_drone_ids.append(drone_id)
        return {
            "payload": payload,
            "targets": [
                {
                    "host": "127.0.0.1",
                    "port": 57000 + drone_id,
                    "sent": True,
                    "error": None,
                }
            ],
        }


class DelayedSender(RecordingSender):
    def __init__(self) -> None:
        super().__init__()
        self.basic_started = asyncio.Event()
        self.release_basic = asyncio.Event()

    async def send_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("cmd") == "takeoff":
            self.basic_started.set()
            await self.release_basic.wait()
        return await super().send_json(payload)


class DelayedConfigSender(RecordingSender):
    def __init__(self) -> None:
        super().__init__()
        self.config_started = asyncio.Event()
        self.release_config = asyncio.Event()
        self._delayed = False

    async def send_json_to_drone(
        self,
        payload: dict[str, Any],
        drone_id: int,
    ) -> dict[str, Any]:
        if not self._delayed:
            self._delayed = True
            self.config_started.set()
            await self.release_config.wait()
        return await super().send_json_to_drone(payload, drone_id)


class DelayedFormationSender(RecordingSender):
    def __init__(self) -> None:
        super().__init__()
        self.start_packet_entered = asyncio.Event()
        self.release_start_packet = asyncio.Event()

    async def send_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("cmd") == "formation_start":
            self.start_packet_entered.set()
            await self.release_start_packet.wait()
        return await super().send_json(payload)


class FailingDispatchSender(RecordingSender):
    def __init__(
        self,
        *,
        fail_targeted_id: int | None = None,
        fail_command: str | None = None,
    ) -> None:
        super().__init__()
        self.fail_targeted_id = fail_targeted_id
        self.fail_command = fail_command

    @staticmethod
    def _mark_failed(dispatch: dict[str, Any], message: str) -> dict[str, Any]:
        dispatch["targets"][0]["sent"] = False
        dispatch["targets"][0]["error"] = message
        return dispatch

    async def send_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        dispatch = await super().send_json(payload)
        if payload.get("cmd") == self.fail_command:
            return self._mark_failed(dispatch, f"failed {self.fail_command}")
        return dispatch

    async def send_json_to_drone(
        self,
        payload: dict[str, Any],
        drone_id: int,
    ) -> dict[str, Any]:
        dispatch = await super().send_json_to_drone(payload, drone_id)
        if drone_id == self.fail_targeted_id:
            return self._mark_failed(dispatch, f"failed drone {drone_id}")
        return dispatch


@pytest.mark.asyncio
async def test_abort_bypasses_a_full_unprocessed_receive_queue(config_path) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = RecordingSender()
    service = CommandService(store, sender)

    for index in range(settings.limits.log_entries):
        assert store.enqueue_message({"type": "log", "text": f"burst-{index}"})
    assert store.receive_queue_diagnostics()["depth"] == settings.limits.log_entries

    response = await asyncio.wait_for(service.abort(), 0.1)
    assert response.locally_dispatched is True
    assert sender.payloads[0]["cmd"] == "abort"
    assert store.receive_queue_diagnostics()["depth"] == settings.limits.log_entries


@pytest.mark.asyncio
async def test_command_payloads_order_and_emergency_lock(config_path) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = RecordingSender()
    service = CommandService(store, sender)
    await store.update_formations(
        0,
        {0: [], 1: [3, 1, 2], 2: [], 3: []},
        {0: None, 1: 3, 2: None, 3: None},
    )

    basic = await service.send_basic(BasicCommandRequest(command="takeoff", group=1))
    assert basic.locally_dispatched
    assert sender.payloads[-1] == {
        "cmd": "takeoff",
        "targets": [1, 2, 3],
        "group": 1,
    }

    count_before_formation = len(sender.payloads)
    formation = await service.send_formation(
        FormationCommandRequest(group=1, form_type=2, spacing=50.0)
    )
    assert formation.locally_dispatched
    assert sender.payloads[count_before_formation:] == [{
        "cmd": "formation_start",
        "group": 1,
        "targets": [1, 2, 3],
        "form_type": 2,
        "spacing": 50.0,
    }]
    assert len(formation.dispatches) == 1
    assert formation.dispatches[0].payload == sender.payloads[-1]

    await service.send_workbench(
        WorkbenchCommandRequest(command="test_dubins", targets=[3, 1, 3])
    )
    assert sender.payloads[-1] == {"cmd": "test_dubins", "targets": [1, 3]}

    await service.abort()
    assert sender.payloads[-1] == {"cmd": "abort"}
    assert await store.is_command_blocked()
    with pytest.raises(CommandBlockedError):
        await service.send_basic(BasicCommandRequest(command="land", group=1))

    count_before_resume = len(sender.payloads)
    resumed = await service.resume()
    assert not resumed.locally_dispatched
    assert len(sender.payloads) == count_before_resume
    assert not await store.is_command_blocked()
    assert sender.broadcast_payloads == sender.payloads
    assert sender.targeted_drone_ids == []


@pytest.mark.asyncio
async def test_first_discovery_config_update_uses_current_settings(config_path) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = RecordingSender()
    service = CommandService(store, sender)

    async def on_new(
        drone_id: int,
        group_id: int,
        leader: bool,
        _displaced_leader_id: int | None,
    ) -> None:
        await service.config_update_for_drone(drone_id, group_id, leader)

    store.set_new_drone_handler(on_new)
    try:
        await store.handle_message({"type": "telemetry", "id": 4})
        assert sender.payloads == [
            {
                "cmd": "config_update",
                "id": 4,
                "group": 0,
                "is_leader": 1,
                "form_type": 1,
                "spacing": 2000.0,
            }
        ]
        assert sender.broadcast_payloads == []
        assert sender.targeted_drone_ids == [4]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_ascending_discovery_targets_each_new_drone_once(config_path) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = RecordingSender()
    service = CommandService(store, sender)
    store.set_new_drone_handler(service.config_updates_for_discovery)
    try:
        for drone_id in range(1, 25):
            assert await store.handle_message({"type": "telemetry", "id": drone_id})

        assert sender.targeted_drone_ids == list(range(1, 25))
        assert len(sender.payloads) == 24
        assert sender.broadcast_payloads == []
        assert sender.payloads[0]["is_leader"] == 1
        assert all(payload["is_leader"] == 0 for payload in sender.payloads[1:])
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_lower_id_discovery_updates_only_new_and_displaced_leader(config_path) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = RecordingSender()
    service = CommandService(store, sender)
    store.set_new_drone_handler(service.config_updates_for_discovery)
    try:
        await store.handle_message({"type": "telemetry", "id": 5})
        await store.handle_message({"type": "telemetry", "id": 8})
        before_replacement = len(sender.payloads)

        await store.handle_message({"type": "telemetry", "id": 2})

        assert sender.targeted_drone_ids == [5, 8, 2, 5]
        replacement_payloads = sender.payloads[before_replacement:]
        assert [(payload["id"], payload["is_leader"]) for payload in replacement_payloads] == [
            (2, 1),
            (5, 0),
        ]
        assert all(payload["group"] == 0 for payload in replacement_payloads)
        assert sender.broadcast_payloads == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_abort_latches_immediately_and_skips_queued_commands(config_path) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = DelayedSender()
    service = CommandService(store, sender)
    await store.update_formations(
        0,
        {0: [], 1: [1], 2: [], 3: []},
        {0: None, 1: 1, 2: None, 3: None},
    )

    basic_task = asyncio.create_task(
        service.send_basic(BasicCommandRequest(command="takeoff", group=1))
    )
    await asyncio.wait_for(sender.basic_started.wait(), 1.0)
    resume_task = asyncio.create_task(service.resume())
    await asyncio.sleep(0)
    land_task = asyncio.create_task(
        service.send_basic(BasicCommandRequest(command="land", group=1))
    )
    rtl_task = asyncio.create_task(
        service.send_basic(BasicCommandRequest(command="rtl", group=1))
    )
    await asyncio.sleep(0)
    abort_task = asyncio.create_task(service.abort())
    for _ in range(20):
        if await store.is_command_blocked():
            break
        await asyncio.sleep(0)

    assert sender.payloads == []
    assert await store.is_command_blocked()
    sender.release_basic.set()
    results = await asyncio.gather(
        basic_task,
        resume_task,
        land_task,
        rtl_task,
        abort_task,
        return_exceptions=True,
    )

    assert [payload["cmd"] for payload in sender.payloads] == ["takeoff", "abort"]
    assert isinstance(results[1], CommandBlockedError)
    assert isinstance(results[2], CommandBlockedError)
    assert isinstance(results[3], CommandBlockedError)
    assert await store.is_command_blocked()
    await store.stop()


@pytest.mark.asyncio
async def test_abort_reclears_an_inflight_formation(config_path) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = DelayedFormationSender()
    service = CommandService(store, sender)
    await store.update_formations(
        0,
        {0: [], 1: [1], 2: [], 3: []},
        {0: None, 1: 1, 2: None, 3: None},
    )

    formation_task = asyncio.create_task(
        service.send_formation(FormationCommandRequest(group=1))
    )
    await asyncio.wait_for(sender.start_packet_entered.wait(), 1.0)
    abort_task = asyncio.create_task(service.abort())
    for _ in range(20):
        if await store.is_command_blocked():
            break
        await asyncio.sleep(0)
    assert await store.is_command_blocked()

    sender.release_start_packet.set()
    await asyncio.gather(formation_task, abort_task)
    snapshot = await store.snapshot()
    assert snapshot["command_blocked"] is True
    assert snapshot["active_formations"] == []
    assert [payload["cmd"] for payload in sender.payloads] == [
        "formation_start",
        "abort",
    ]
    await store.stop()


@pytest.mark.parametrize("command", ["test_dubins", "test_vo", "mission"])
@pytest.mark.parametrize("targets", [None, [3, 1, 3]])
@pytest.mark.asyncio
async def test_all_workbench_payload_variants(config_path, command, targets) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = RecordingSender()
    service = CommandService(store, sender)

    await service.send_workbench(
        WorkbenchCommandRequest(command=command, targets=targets)
    )
    expected = {"cmd": command}
    if targets is not None:
        expected["targets"] = [1, 3]
    assert sender.payloads == [expected]


@pytest.mark.asyncio
async def test_formation_publish_serializes_first_drone_discovery(config_path) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = DelayedConfigSender()
    service = CommandService(store, sender)

    store.set_new_drone_handler(service.config_updates_for_discovery)
    publish_task = asyncio.create_task(
        service.publish_formations(
            0,
            {0: [1], 1: [], 2: [], 3: []},
            {0: 1, 1: None, 2: None, 3: None},
        )
    )
    await asyncio.wait_for(sender.config_started.wait(), 1.0)
    discovery_task = asyncio.create_task(
        store.handle_message({"type": "telemetry", "id": 2})
    )
    await asyncio.sleep(0)
    assert not discovery_task.done()

    sender.release_config.set()
    published, discovered = await asyncio.gather(publish_task, discovery_task)
    assert published["revision"] == 1
    assert discovered is True
    formations = (await store.snapshot())["formations"]
    assert formations["revision"] == 2
    assert formations["members"]["0"] == [1, 2]
    await store.stop()


@pytest.mark.asyncio
async def test_publish_restarts_only_previously_active_nonempty_groups(config_path) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = RecordingSender()
    service = CommandService(store, sender)
    try:
        await store.update_formation_settings(3, 45.0)
        await store.update_formations(
            0,
            {0: [9], 1: [2, 5], 2: [7], 3: [12]},
            {0: 9, 1: 2, 2: 7, 3: 12},
        )
        for group_id in (1, 2, 3):
            await store.mark_formation_active(group_id)

        published = await service.publish_formations(
            1,
            {
                0: [10, 9],
                1: [8, 5, 3],
                2: [7, 4],
                3: [],
            },
            {
                0: 9,
                1: 3,
                2: 4,
                3: None,
            },
        )

        config_packets = sender.payloads[:7]
        restart_packets = sender.payloads[7:]
        assert [packet["cmd"] for packet in config_packets] == ["config_update"] * 7
        assert [packet["id"] for packet in config_packets] == [9, 10, 3, 5, 8, 4, 7]
        assert all("speed" not in packet for packet in config_packets)
        assert all(packet["form_type"] == 3 for packet in config_packets)
        assert all(packet["spacing"] == 45.0 for packet in config_packets)

        assert [
            (packet["cmd"], packet["group"], packet["targets"])
            for packet in restart_packets
        ] == [
            ("formation_start", 1, [3, 5, 8]),
            ("formation_start", 2, [4, 7]),
        ]
        assert all(packet["form_type"] == 3 for packet in restart_packets)
        assert all(packet["spacing"] == 45.0 for packet in restart_packets)

        # Group 0 was not active, so it receives configs but is not started.
        # Group 3 was active but became empty, so it is no longer active.
        assert {packet["group"] for packet in restart_packets} == {1, 2}
        snapshot = await store.snapshot()
        assert snapshot["active_formations"] == [1, 2]
        assert published == snapshot["formations"]
        assert set(published) == {"revision", "members", "leaders"}
    finally:
        await store.stop()


@pytest.mark.parametrize(
    ("fail_targeted_id", "fail_command", "expected_commands"),
    [
        (2, None, ["config_update", "config_update"]),
        (
            None,
            "formation_start",
            ["config_update", "config_update", "formation_start"],
        ),
    ],
)
@pytest.mark.asyncio
async def test_publish_does_not_commit_or_advance_after_a_local_dispatch_failure(
    config_path,
    fail_targeted_id,
    fail_command,
    expected_commands,
) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    sender = FailingDispatchSender(
        fail_targeted_id=fail_targeted_id,
        fail_command=fail_command,
    )
    service = CommandService(store, sender)
    try:
        original = await store.update_formations(
            0,
            {0: [], 1: [1, 2], 2: [], 3: []},
            {0: None, 1: 1, 2: None, 3: None},
        )
        await store.mark_formation_active(1)

        with pytest.raises(UDPUnavailable) as caught:
            await service.publish_formations(
                1,
                {0: [], 1: [1, 2], 2: [], 3: []},
                {0: None, 1: 1, 2: None, 3: None},
            )

        assert "下发失败" in str(caught.value)
        assert "127.0.0.1:" in str(caught.value)
        assert [payload["cmd"] for payload in sender.payloads] == expected_commands
        snapshot = await store.snapshot()
        assert snapshot["formations"] == original
        assert snapshot["active_formations"] == [1]
    finally:
        await store.stop()
