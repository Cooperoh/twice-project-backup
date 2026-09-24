from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
import pytest

from backend import create_app, load_settings
from backend.events import WebSocketHub
from backend.state import StateStore


def test_runtime_identity_and_authenticated_shutdown(config_path, tmp_path) -> None:
    app = create_app(
        settings=load_settings(config_path),
        static_dir=tmp_path,
        start_udp=False,
    )
    requested: list[bool] = []
    app.state.shutdown_token = "local-test-token"
    app.state.request_shutdown = lambda: requested.append(True)

    with TestClient(app) as client:
        runtime = client.get("/api/runtime")
        assert runtime.status_code == 200
        assert runtime.json()["application"] == "GroundControlPanel-2C/web_app"

        assert client.post("/api/runtime/shutdown").status_code == 403
        accepted = client.post(
            "/api/runtime/shutdown",
            headers={"X-GCS-Shutdown-Token": "local-test-token"},
        )
        assert accepted.status_code == 202
        assert accepted.json() == {"status": "stopping"}
        assert requested == [True]


def test_bootstrap_health_static_and_validation(config_path, tmp_path) -> None:
    app = create_app(
        settings=load_settings(config_path),
        static_dir=tmp_path,
        start_udp=False,
    )
    with TestClient(app) as client:
        bootstrap = client.get("/api/bootstrap")
        assert bootstrap.status_code == 200
        body = bootstrap.json()
        assert body["formation_settings"] == {"form_type": 1, "spacing": 2000.0}
        assert body["config"]["home_lat"] == 38.3094
        assert "monitor_refresh_interval_ms" not in body["config"]
        assert body["tracks"] == {}
        assert body["logs"] == []

        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "degraded"
        receive_queue = health.json()["receive_queue"]
        assert receive_queue["capacity"] == 2024
        assert receive_queue["depth"] == 0
        assert receive_queue["high_watermark"] == 0
        assert receive_queue["dropped_total"] == 0
        assert receive_queue["last_batch_size"] == 0
        assert receive_queue["last_batch_duration_ms"] >= 0

        assert client.get("/").status_code == 503
        rejected = client.post(
            "/api/commands/basic",
            json={"command": "takeoff", "group": 1},
        )
        assert rejected.status_code == 422


def test_frontend_html_is_not_cached_and_hashed_assets_are_immutable(
    config_path,
    tmp_path,
) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text("<main>web app</main>", encoding="utf-8")
    (assets / "index-AbCd1234.js").write_text("export {}", encoding="utf-8")
    (assets / "plain.js").write_text("export {}", encoding="utf-8")
    app = create_app(
        settings=load_settings(config_path),
        static_dir=tmp_path,
        start_udp=False,
    )

    with TestClient(app) as client:
        for path in ("/", "/index.html", "/workbench"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == (
                "no-store, no-cache, must-revalidate"
            )
            assert response.headers["pragma"] == "no-cache"
            assert response.headers["expires"] == "0"

        hashed = client.get("/assets/index-AbCd1234.js")
        assert hashed.status_code == 200
        assert hashed.headers["cache-control"] == (
            "public, max-age=31536000, immutable"
        )

        unhashed = client.get("/assets/plain.js")
        assert unhashed.status_code == 200
        assert unhashed.headers.get("cache-control") != (
            "public, max-age=31536000, immutable"
        )


def test_revision_conflict_abort_lock_and_websocket_snapshot(config_path, tmp_path) -> None:
    app = create_app(
        settings=load_settings(config_path),
        static_dir=tmp_path,
        start_udp=False,
    )
    with TestClient(app) as client:
        with client.websocket_connect("/api/ws") as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["type"] == "snapshot"
            assert snapshot["payload"]["formations"]["revision"] == 0

            empty = {
                "revision": 0,
                "members": {"0": [], "1": [], "2": [], "3": []},
                "leaders": {"0": None, "1": None, "2": None, "3": None},
            }
            accepted = client.put("/api/formations", json=empty)
            assert accepted.status_code == 200
            assert accepted.json()["revision"] == 1
            assert websocket.receive_json()["type"] == "formations"

            conflict = client.put("/api/formations", json=empty)
            assert conflict.status_code == 409

        # No UDP sender exists in test mode, but emergency state must remain set.
        failed_abort = client.post("/api/commands/abort")
        assert failed_abort.status_code == 503
        assert client.get("/api/bootstrap").json()["command_blocked"] is True
        resumed = client.post("/api/commands/resume")
        assert resumed.status_code == 200
        assert client.get("/api/bootstrap").json()["command_blocked"] is False


def test_failed_formation_broadcast_does_not_commit_state(config_path, tmp_path) -> None:
    app = create_app(
        settings=load_settings(config_path),
        static_dir=tmp_path,
        start_udp=False,
    )
    proposal = {
        "revision": 0,
        "members": {"0": [1], "1": [], "2": [], "3": []},
        "leaders": {"0": 1, "1": None, "2": None, "3": None},
    }
    with TestClient(app) as client:
        failed = client.put("/api/formations", json=proposal)
        assert failed.status_code == 503
        formations = client.get("/api/bootstrap").json()["formations"]
        assert formations["revision"] == 0
        assert formations["members"] == {"0": [], "1": [], "2": [], "3": []}


def test_cross_site_mutations_are_rejected(config_path, tmp_path) -> None:
    app = create_app(
        settings=load_settings(config_path),
        static_dir=tmp_path,
        start_udp=False,
    )
    with TestClient(app) as client:
        headers = {
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "cross-site",
        }
        assert client.post("/api/commands/abort", headers=headers).status_code == 403
        assert client.post("/api/commands/resume", headers=headers).status_code == 403
        assert client.delete("/api/logs", headers=headers).status_code == 403
        wrong_local_port = {"Origin": "http://127.0.0.1:9999"}
        assert client.post(
            "/api/commands/resume",
            headers=wrong_local_port,
        ).status_code == 403
        exact_origin = {"Origin": "http://127.0.0.1:8765"}
        assert client.post(
            "/api/commands/resume",
            headers=exact_origin,
        ).status_code == 200
        assert client.get("/api/bootstrap").json()["command_blocked"] is False


@pytest.mark.asyncio
async def test_websocket_snapshot_does_not_duplicate_a_concurrent_log(config_path) -> None:
    settings = load_settings(config_path)
    hub = WebSocketHub(settings.limits.websocket_queue)
    store = StateStore(settings, hub)
    entered_publish = asyncio.Event()
    release_publish = asyncio.Event()
    original_publish = hub.publish

    async def delayed_publish(event_type, payload):
        if event_type == "log":
            entered_publish.set()
            await release_publish.wait()
        return await original_publish(event_type, payload)

    hub.publish = delayed_publish  # type: ignore[method-assign]
    append_task = asyncio.create_task(store.append_log("race"))
    await asyncio.wait_for(entered_publish.wait(), 1.0)
    subscribe_task = asyncio.create_task(store.subscribe_snapshot())
    await asyncio.sleep(0)
    assert not subscribe_task.done()

    release_publish.set()
    await append_task
    queue, _baseline, snapshot = await subscribe_task
    try:
        assert snapshot["logs"] == []
        assert queue.empty()
    finally:
        await hub.unsubscribe(queue)


@pytest.mark.asyncio
async def test_event_sequence_and_slow_client_queue_are_non_blocking() -> None:
    hub = WebSocketHub(queue_size=1)
    queue, baseline = await hub.subscribe()
    try:
        assert baseline == 0
        first = await asyncio.wait_for(hub.publish("one", {"value": 1}), 0.1)
        second = await asyncio.wait_for(hub.publish("two", {"value": 2}), 0.1)
        assert first["seq"] == 1
        assert second["seq"] == 2
        assert queue.qsize() == 1
        assert (await queue.get())["type"] == "two"
    finally:
        await hub.unsubscribe(queue)


def test_websocket_reconnect_receives_a_fresh_snapshot(config_path, tmp_path) -> None:
    app = create_app(
        settings=load_settings(config_path),
        static_dir=tmp_path,
        start_udp=False,
    )
    with TestClient(app) as client:
        with client.websocket_connect("/api/ws") as first_socket:
            first = first_socket.receive_json()
            assert first["payload"]["logs"] == []

        assert client.portal is not None
        client.portal.call(app.state.store.append_log, "after-reconnect")

        with client.websocket_connect("/api/ws") as second_socket:
            recovered = second_socket.receive_json()
            assert recovered["type"] == "snapshot"
            assert recovered["seq"] > first["seq"]
            assert recovered["payload"]["logs"] == []
