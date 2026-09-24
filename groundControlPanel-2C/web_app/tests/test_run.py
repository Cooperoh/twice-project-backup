from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import pytest

import run as launcher
from backend.instance import InstanceLock


WEB_ROOT = Path(__file__).resolve().parents[1]
LEGACY_MODULES = {
    "drone_icon",
    "groundBridge",
    "groundMain",
    "pageFormation",
    "pageMonitor",
    "pageWorkbench",
}


def test_instance_lock_rejects_a_second_launcher_and_releases(tmp_path) -> None:
    path = tmp_path / ".web_app.lock"
    first = InstanceLock(path)
    second = InstanceLock(path)
    assert first.acquire({"pid": 123, "url": "http://127.0.0.1:8765/"}) is True
    assert second.acquire({"pid": 456}) is False
    assert second.read_metadata() == {
        "pid": 123,
        "url": "http://127.0.0.1:8765/",
    }
    first.release()
    assert second.acquire({"pid": 456}) is True
    second.release()


def _write_packaged_frontend(frontend_dir: Path) -> Path:
    dist = frontend_dir / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (assets / "index-AbCd1234.js").write_text("export {}", encoding="utf-8")
    (assets / "index-EfGh5678.css").write_text("body {}", encoding="utf-8")
    (dist / "index.html").write_text(
        """
        <script type="module" src="./assets/index-AbCd1234.js?build=1"></script>
        <link rel="stylesheet" href="./assets/index-EfGh5678.css">
        <link rel="preconnect" href="https://tiles.example.test">
        """,
        encoding="utf-8",
    )
    return dist


def test_packaged_frontend_without_sources_only_checks_referenced_assets(
    tmp_path,
) -> None:
    frontend_dir = tmp_path / "packaged-frontend"
    dist = _write_packaged_frontend(frontend_dir)

    launcher.validate_frontend_build(dist, frontend_dir)

    (dist / "assets" / "index-AbCd1234.js").unlink()
    with pytest.raises(launcher.FrontendBuildError) as caught:
        launcher.validate_frontend_build(dist, frontend_dir)
    message = str(caught.value)
    assert "index-AbCd1234.js" in message
    assert "pnpm run build" in message


def test_local_frontend_source_newer_than_dist_requires_rebuild(tmp_path) -> None:
    frontend_dir = tmp_path / "frontend"
    dist = _write_packaged_frontend(frontend_dir)
    source = frontend_dir / "src" / "main.ts"
    source.parent.mkdir()
    source.write_text("export {}", encoding="utf-8")
    dist_index = dist / "index.html"
    timestamp = max(source.stat().st_mtime_ns, dist_index.stat().st_mtime_ns)
    os.utime(dist_index, ns=(timestamp, timestamp))
    os.utime(source, ns=(timestamp + 2_000_000_000, timestamp + 2_000_000_000))

    with pytest.raises(launcher.FrontendBuildError) as caught:
        launcher.validate_frontend_build(dist, frontend_dir)
    message = str(caught.value)
    assert "src" in message
    assert "dist 已过期" in message
    assert "pnpm run build" in message

    os.utime(
        dist_index,
        ns=(timestamp + 4_000_000_000, timestamp + 4_000_000_000),
    )
    launcher.validate_frontend_build(dist, frontend_dir)


def test_launcher_runs_from_an_unrelated_working_directory_without_legacy_modules(
    config_path,
    monkeypatch,
    tmp_path,
) -> None:
    frontend_dir = tmp_path / "packaged-frontend"
    dist = _write_packaged_frontend(frontend_dir)
    foreign_cwd = tmp_path / "foreign-cwd"
    foreign_cwd.mkdir()
    loaded_before = LEGACY_MODULES.intersection(sys.modules)
    captured: dict[str, object] = {}

    monkeypatch.chdir(foreign_cwd)
    monkeypatch.setattr(launcher, "FRONTEND_DIR", frontend_dir)
    monkeypatch.setattr(launcher, "DEFAULT_STATIC_DIR", dist)
    monkeypatch.setattr(launcher, "INSTANCE_LOCK", tmp_path / ".web_app.lock")
    monkeypatch.setattr(
        launcher,
        "parse_args",
        lambda: argparse.Namespace(
            config=config_path,
            no_browser=True,
            test_mode=True,
        ),
    )

    class FakeServer:
        def __init__(self, config) -> None:
            captured["config"] = config
            self.should_exit = False

        def run(self) -> None:
            captured["app"] = captured["config"].app

    monkeypatch.setattr(launcher.uvicorn, "Server", FakeServer)
    launcher.main()

    assert launcher.SRC_DIR == WEB_ROOT.resolve()
    assert captured["app"].state.static_dir == dist.resolve()
    assert captured["config"].host == "127.0.0.1"
    assert captured["config"].port == 8765
    assert LEGACY_MODULES.intersection(sys.modules) == loaded_before
