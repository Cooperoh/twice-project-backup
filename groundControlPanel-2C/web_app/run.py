"""Cross-platform launcher for the standalone Web ground-control panel."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import os
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.parse import unquote, urlsplit
import webbrowser

import uvicorn

from backend import create_app, load_settings
from backend.audit import default_audit_directory
from backend.instance import InstanceLock


SRC_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = SRC_DIR / "frontend"
DEFAULT_CONFIG = SRC_DIR / "config.toml"
DEFAULT_STATIC_DIR = FRONTEND_DIR / "dist"
INSTANCE_LOCK = SRC_DIR / ".web_app.lock"
_REBUILD_GUIDANCE = (
    "请在 web_app/frontend 目录运行 `pnpm run build`，然后重启 Python 进程，"
    "并关闭旧标签页或执行浏览器硬刷新。"
)


class FrontendBuildError(RuntimeError):
    """Raised when the packaged frontend cannot safely be served."""


class _FrontendReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attribute = "src" if tag == "script" else "href" if tag == "link" else None
        if attribute is None:
            return
        for name, value in attrs:
            if name == attribute and value:
                self.references.append(value)


def validate_frontend_build(
    static_dir: str | Path = DEFAULT_STATIC_DIR,
    frontend_dir: str | Path | None = None,
) -> None:
    """Validate referenced assets and reject a stale local source build."""

    web_root = Path(static_dir).expanduser().resolve()
    source_root = (
        Path(frontend_dir).expanduser().resolve()
        if frontend_dir is not None
        else web_root.parent
    )
    index = web_root / "index.html"
    if not index.is_file():
        raise FrontendBuildError(
            f"未找到前端构建入口：{index}。\n{_REBUILD_GUIDANCE}"
        )

    parser = _FrontendReferenceParser()
    try:
        parser.feed(index.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise FrontendBuildError(
            f"无法读取前端构建入口 {index}：{exc}。\n{_REBUILD_GUIDANCE}"
        ) from exc

    missing_assets: list[str] = []
    for reference in parser.references:
        relative_path = _local_asset_path(reference)
        if relative_path is None:
            continue
        candidate = (web_root / relative_path).resolve()
        try:
            candidate.relative_to(web_root)
        except ValueError:
            missing_assets.append(reference)
            continue
        if not candidate.is_file():
            missing_assets.append(reference)

    if missing_assets:
        missing = "、".join(sorted(set(missing_assets)))
        raise FrontendBuildError(
            f"前端入口引用了不存在的本地资源：{missing}。\n{_REBUILD_GUIDANCE}"
        )

    build_inputs = list(_frontend_build_inputs(source_root))
    if not build_inputs:
        # A packaged deployment may contain only dist; asset integrity is still
        # checked above, while source freshness cannot and need not be checked.
        return

    newest_input = max(build_inputs, key=lambda path: path.stat().st_mtime_ns)
    if newest_input.stat().st_mtime_ns > index.stat().st_mtime_ns:
        try:
            display_path = newest_input.relative_to(source_root)
        except ValueError:
            display_path = newest_input
        raise FrontendBuildError(
            f"前端源码或构建配置比 dist/index.html 更新（{display_path}），"
            f"当前 dist 已过期。\n{_REBUILD_GUIDANCE}"
        )


def _local_asset_path(reference: str) -> Path | None:
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or reference.startswith("//"):
        return None
    path = unquote(parsed.path).replace("\\", "/")
    if not path or path == "/":
        return None
    while path.startswith("./"):
        path = path[2:]
    return Path(path.lstrip("/"))


def _frontend_build_inputs(frontend_dir: Path):
    candidates: set[Path] = set()
    source_dir = frontend_dir / "src"
    if source_dir.is_dir():
        candidates.update(path for path in source_dir.rglob("*") if path.is_file())

    for name in (
        "index.html",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
    ):
        path = frontend_dir / name
        if path.is_file():
            candidates.add(path)

    for pattern in ("vite.config.*", "tsconfig*.json"):
        candidates.update(path for path in frontend_dir.glob(pattern) if path.is_file())

    yield from sorted(candidates)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动独立 Web 地面站")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="TOML 配置文件路径（默认：web_app/config.toml）",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="启动后不自动打开浏览器",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="测试模式：不绑定真实 UDP 端口，也不自动打开浏览器",
    )
    return parser.parse_args()


def _open_browser_when_ready(host: str, port: int, url: str) -> None:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((probe_host, port), timeout=0.25):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.1)


def main() -> None:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    settings = load_settings(config_path)

    url = f"http://{settings.server.host}:{settings.server.port}/"
    shutdown_token = secrets.token_urlsafe(24)
    instance = InstanceLock(INSTANCE_LOCK)
    metadata = {
        "application": "GroundControlPanel-2C/web_app",
        "pid": os.getpid(),
        "host": settings.server.host,
        "port": settings.server.port,
        "url": url,
        "shutdown_token": shutdown_token,
    }
    if not instance.acquire(metadata):
        running = instance.read_metadata() or {}
        running_pid = running.get("pid", "unknown")
        running_url = str(running.get("url") or url)
        print(
            f"[GCS] Ground station is already running (PID {running_pid}).",
            flush=True,
        )
        print(f"[GCS] Open: {running_url}", flush=True)
        if settings.server.open_browser and not args.no_browser and not args.test_mode:
            webbrowser.open(running_url)
        return

    try:
        static_dir = DEFAULT_STATIC_DIR
        try:
            validate_frontend_build(static_dir, FRONTEND_DIR)
        except FrontendBuildError as exc:
            raise SystemExit(str(exc)) from exc

        parser = _FrontendReferenceParser()
        parser.feed((static_dir / "index.html").read_text(encoding="utf-8"))
        local_assets = [
            str(path)
            for reference in parser.references
            if (path := _local_asset_path(reference)) is not None
        ]
        print(f"[GCS] application root: {SRC_DIR}", flush=True)
        print(f"[GCS] configuration: {config_path}", flush=True)
        print(f"[GCS] frontend assets: {', '.join(local_assets)}", flush=True)
        print(f"[GCS] audit directory: {default_audit_directory()}", flush=True)

        app = create_app(
            settings=settings,
            static_dir=static_dir,
            start_udp=not args.test_mode,
        )

        should_open = (
            settings.server.open_browser and not args.no_browser and not args.test_mode
        )
        if should_open:
            threading.Thread(
                target=_open_browser_when_ready,
                args=(settings.server.host, settings.server.port, url),
                daemon=True,
            ).start()

        config = uvicorn.Config(
            app,
            host=settings.server.host,
            port=settings.server.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        app.state.shutdown_token = shutdown_token
        app.state.request_shutdown = lambda: setattr(server, "should_exit", True)
        server.run()
    finally:
        instance.release()


if __name__ == "__main__":
    main()
