from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from backend.config import load_settings
from backend.events import WebSocketHub
from backend.state import (
    MAX_DYNAMIC_TELEMETRY_FIELDS_PER_DRONE,
    StateStore,
    flight_control_status,
    telemetry_status,
)


def capture_events(hub: WebSocketHub) -> list[tuple[str, object]]:
    published: list[tuple[str, object]] = []
    original_publish = hub.publish

    async def capture_publish(event_type, payload):
        published.append((event_type, payload))
        return await original_publish(event_type, payload)

    hub.publish = capture_publish  # type: ignore[method-assign]
    return published


@pytest.mark.asyncio
async def test_mixed_receive_queue_reduces_telemetry_and_batches_all_logs(config_path) -> None:
    settings = load_settings(config_path)
    hub = WebSocketHub(settings.limits.websocket_queue)
    store = StateStore(settings, hub)
    published = capture_events(hub)

    assert store.enqueue_message(
        {"type": "telemetry", "id": 1, "lat": 38.0, "lon": 117.0}
    )
    assert store.enqueue_message({"type": "log", "text": "first"})
    assert store.enqueue_message(
        {
            "type": "telemetry",
            "id": "1",
            "lat": 38.1,
            "lon": 117.1,
            "alt": 120.5,
            "phase": "cruise",
            "future": {"mode": 3},
            "_private": "ignored",
        }
    )
    assert store.enqueue_message(
        {"type": "telemetry", "id": 2, "lat": 39.0, "lon": 118.0}
    )
    assert store.enqueue_message({"type": "log", "text": "second"})

    assert await store.process_receive_queue_once()
    batches = [payload for kind, payload in published if kind == "realtime_batch"]
    assert len(batches) == 1
    assert [kind for kind, _payload in published] == ["realtime_batch"]
    payload = batches[0]
    assert payload["drones"]["1"]["lat"] == pytest.approx(38.1)
    assert payload["drones"]["1"]["alt"] == pytest.approx(120.5)
    assert payload["drones"]["1"]["phase"] == "cruise"
    assert payload["drones"]["1"]["future"] == {"mode": 3}
    assert "_private" not in payload["drones"]["1"]
    assert payload["track_updates"]["1"] == {
        "epoch": 0,
        "seq": 1,
        "point": {"lat": 38.1, "lon": 117.1},
    }
    assert [entry["text"] for entry in payload["logs"]] == ["first", "second"]
    assert payload["formations"]["members"]["0"] == [1, 2]

    snapshot = await store.snapshot()
    assert snapshot["tracks"] == {}
    assert snapshot["logs"] == []
    diagnostics = store.receive_queue_diagnostics()
    assert diagnostics["depth"] == 0
    assert diagnostics["high_watermark"] == 4
    assert diagnostics["telemetry_replaced_total"] == 1
    assert diagnostics["last_batch_size"] == 4
    assert diagnostics["last_batch_duration_ms"] >= 0


@pytest.mark.asyncio
async def test_heartbeat_keeps_last_flight_fields_and_dynamic_state_bounded(
    config_path,
) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))

    assert await store.handle_message(
        {
            "type": "telemetry",
            "id": 2,
            "lat": 38.1,
            "lon": 117.2,
            "alt": 87,
            "speed": 12.5,
            "heading": 90,
            "phase": "cruise",
            "goto_lat": 38.2,
            "goto_lon": 117.3,
            "future": {"mode": 3},
        }
    )
    first = await store.snapshot()
    first_flight_seen = first["drones"]["2"]["last_flight_control_at"]

    assert await store.handle_message(
        {"type": "telemetry", "id": 2, "tag": "DRONE2"}
    )
    heartbeat = await store.snapshot()
    drone = heartbeat["drones"]["2"]
    assert drone["last_flight_control_at"] == first_flight_seen
    assert (drone["lat"], drone["lon"]) == (38.1, 117.2)
    assert (drone["alt"], drone["speed"]) == (87, 12.5)
    assert (drone["heading"], drone["phase"]) == (90, "cruise")
    assert drone["future"] == {"mode": 3}
    assert heartbeat["tracks"] == {}

    assert await store.handle_message(
        {"type": "telemetry", "id": 2, "speed": 13.0, "phase": "hold"}
    )
    partial = (await store.snapshot())["drones"]["2"]
    assert partial["speed"] == 13.0
    assert partial["phase"] == "hold"
    assert partial["heading"] == 90
    assert partial["alt"] == 87

    for index in range(MAX_DYNAMIC_TELEMETRY_FIELDS_PER_DRONE + 3):
        assert await store.handle_message(
            {"type": "telemetry", "id": 2, f"extension_{index}": index}
        )
    bounded = (await store.snapshot())["drones"]["2"]
    extensions = [key for key in bounded if key.startswith("extension_")]
    assert len(extensions) == MAX_DYNAMIC_TELEMETRY_FIELDS_PER_DRONE
    assert "extension_0" not in bounded
    assert bounded[f"extension_{MAX_DYNAMIC_TELEMETRY_FIELDS_PER_DRONE + 2}"] == (
        MAX_DYNAMIC_TELEMETRY_FIELDS_PER_DRONE + 2
    )
    assert bounded["heading"] == 90
    assert bounded["speed"] == 13.0

    assert await store.handle_message(
        {"type": "telemetry", "id": 2, "lat": 0.0, "lon": 0.0, "bad": float("nan")}
    )
    invalid_fix = (await store.snapshot())["drones"]["2"]
    assert (invalid_fix["lat"], invalid_fix["lon"]) == (38.1, 117.2)
    assert "bad" not in invalid_fix

    assert await store.handle_message({"type": "telemetry", "id": 2, "goto_lat": None})
    cleared = (await store.snapshot())["drones"]["2"]
    assert "goto_lat" not in cleared
    assert "goto_lon" not in cleared


@pytest.mark.asyncio
async def test_unknown_types_invalid_ids_and_empty_cycles_do_not_publish(config_path) -> None:
    settings = load_settings(config_path)
    hub = WebSocketHub(settings.limits.websocket_queue)
    store = StateStore(settings, hub)
    published = capture_events(hub)

    assert not store.enqueue_message({"type": "telemetry", "id": 0})
    assert not store.enqueue_message({"type": "telemetry", "id": 25})
    assert not store.enqueue_message({"type": "telemetry_batch", "list": []})
    assert not store.enqueue_message({"type": "trajectory", "id": 1, "points": []})
    assert not store.enqueue_message({"type": "unknown"})
    assert not store.enqueue_message({"type": "log", "text": ""})
    assert not store.enqueue_message(["not", "an", "object"])
    assert not await store.process_receive_queue_once()
    assert published == []
    assert store.receive_queue_diagnostics()["last_batch_size"] == 0


@pytest.mark.asyncio
async def test_receive_queue_drops_oldest_and_keeps_newest(config_path) -> None:
    base = load_settings(config_path)
    settings = replace(base, limits=replace(base.limits, log_entries=1))
    hub = WebSocketHub(settings.limits.websocket_queue)
    store = StateStore(settings, hub)
    published = capture_events(hub)

    assert store.enqueue_message({"type": "telemetry", "id": 1})
    assert store.enqueue_message({"type": "log", "text": "old-log"})
    assert store.enqueue_message({"type": "telemetry", "id": 2})
    assert store.enqueue_message({"type": "log", "text": "new-log"})
    diagnostics = store.receive_queue_diagnostics()
    assert diagnostics["capacity"] == 25
    assert diagnostics["depth"] == 3
    assert diagnostics["telemetry_depth"] == 2
    assert diagnostics["log_depth"] == 1
    assert diagnostics["high_watermark"] == 3
    assert diagnostics["log_dropped_total"] == 1

    await store.process_receive_queue_once()
    snapshot = await store.snapshot()
    assert "1" in snapshot["drones"]
    assert "2" in snapshot["drones"]
    batch = next(payload for kind, payload in published if kind == "realtime_batch")
    assert [entry["text"] for entry in batch["logs"]] == ["new-log"]


@pytest.mark.asyncio
async def test_fixed_consumer_publishes_one_batch_and_skips_empty_tick(config_path) -> None:
    base = load_settings(config_path)
    settings = replace(base, server=replace(base.server, push_interval_ms=20))
    hub = WebSocketHub(settings.limits.websocket_queue)
    store = StateStore(settings, hub)
    published = capture_events(hub)
    await store.start()
    try:
        for offset in (0.1, 0.2, 0.3):
            assert store.enqueue_message(
                {
                    "type": "telemetry",
                    "id": 1,
                    "lat": 1.0 + offset,
                    "lon": 2.0 + offset,
                }
            )
        assert store.enqueue_message({"type": "log", "text": "batched"})
        await asyncio.sleep(0.03)
        batches = [payload for kind, payload in published if kind == "realtime_batch"]
        assert len(batches) == 1
        assert batches[0]["drones"]["1"]["lat"] == pytest.approx(1.3)
        assert batches[0]["track_updates"]["1"] == {
            "epoch": 0,
            "seq": 1,
            "point": {"lat": 1.3, "lon": 2.3},
        }
        await asyncio.sleep(0.025)
        assert len([kind for kind, _ in published if kind == "realtime_batch"]) == 1
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_track_sequence_and_ring_rollover_stay_incremental(config_path) -> None:
    base = load_settings(config_path)
    settings = replace(base, limits=replace(base.limits, track_points_per_drone=2))
    hub = WebSocketHub(settings.limits.websocket_queue)
    store = StateStore(settings, hub)
    published = capture_events(hub)

    for sequence in range(1, 5):
        published.clear()
        store.enqueue_message(
            {
                "type": "telemetry",
                "id": 1,
                "lat": float(sequence),
                "lon": float(sequence + 10),
            }
        )
        await store.process_receive_queue_once()
        batch = next(payload for kind, payload in published if kind == "realtime_batch")
        assert batch["track_updates"]["1"] == {
            "epoch": 0,
            "seq": sequence,
            "point": {"lat": float(sequence), "lon": float(sequence + 10)},
        }

    snapshot = await store.snapshot()
    assert snapshot["tracks"] == {}
    assert snapshot["track_meta"] == {}


@pytest.mark.asyncio
async def test_snapshot_waits_for_batch_publication_and_does_not_duplicate(config_path) -> None:
    settings = load_settings(config_path)
    hub = WebSocketHub(settings.limits.websocket_queue)
    store = StateStore(settings, hub)
    entered_publish = asyncio.Event()
    release_publish = asyncio.Event()
    original_publish = hub.publish

    async def delayed_publish(event_type, payload):
        if event_type == "realtime_batch":
            entered_publish.set()
            await release_publish.wait()
        return await original_publish(event_type, payload)

    hub.publish = delayed_publish  # type: ignore[method-assign]
    store.enqueue_message({"type": "telemetry", "id": 1, "lat": 1.0, "lon": 2.0})
    store.enqueue_message({"type": "log", "text": "race"})
    process_task = asyncio.create_task(store.process_receive_queue_once())
    await asyncio.wait_for(entered_publish.wait(), 0.2)
    subscribe_task = asyncio.create_task(store.subscribe_snapshot())
    await asyncio.sleep(0)
    assert not subscribe_task.done()

    release_publish.set()
    await process_task
    queue, _baseline, snapshot = await subscribe_task
    try:
        assert snapshot["drones"]["1"]["lat"] == 1.0
        assert snapshot["logs"] == []
        assert queue.empty()
    finally:
        await hub.unsubscribe(queue)


@pytest.mark.asyncio
async def test_clear_tracks_advances_cursor_before_new_batch(config_path) -> None:
    settings = load_settings(config_path)
    hub = WebSocketHub(settings.limits.websocket_queue)
    store = StateStore(settings, hub)
    published = capture_events(hub)

    await store.handle_message(
        {"type": "telemetry", "id": 1, "lat": 1.0, "lon": 2.0}
    )
    published.clear()
    await store.clear_tracks()
    assert published == [("tracks_cleared", {"epoch": 1})]

    published.clear()
    store.enqueue_message(
        {"type": "telemetry", "id": 1, "lat": 3.0, "lon": 4.0}
    )
    await store.process_receive_queue_once()
    batch = next(payload for kind, payload in published if kind == "realtime_batch")
    assert batch["track_updates"]["1"] == {
        "epoch": 1,
        "seq": 1,
        "point": {"lat": 3.0, "lon": 4.0},
    }


@pytest.mark.asyncio
async def test_stop_cancels_consumer_and_discards_unprocessed_queue(config_path) -> None:
    settings = load_settings(config_path)
    store = StateStore(settings, WebSocketHub(settings.limits.websocket_queue))
    await store.start()
    store.enqueue_message({"type": "log", "text": "discard-me"})
    await store.stop()
    assert store.receive_queue_diagnostics()["depth"] == 0
    assert (await store.snapshot())["logs"] == []


def test_status_boundaries(config_path) -> None:
    settings = load_settings(config_path)
    now = 100.0
    assert telemetry_status(97.0, now, settings) == "normal"
    assert telemetry_status(92.0, now, settings) == "weak"
    assert telemetry_status(80.0, now, settings) == "poor"
    assert telemetry_status(79.999, now, settings) == "disconnected"
    assert flight_control_status(97.0, now, settings) == "normal"
    assert flight_control_status(92.0, now, settings) == "fault"
    assert flight_control_status(91.999, now, settings) == "dead"
