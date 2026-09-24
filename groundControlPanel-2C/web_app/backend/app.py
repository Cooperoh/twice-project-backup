"""
后端总入口和接线板

角色：
    本文件负责搭建 FastAPI 应用，并把各个后端模块连接成一个可以运行的整体。

主要职责：
    ``create_app()`` 先读取配置，再依次创建 
    WebSocket 广播站  ``hub``
    中央数据仓库      ``store``
    UDP 通信服务      ``udp`` 
    命令处理器        ``commands``
    随后注册HTTP API、WebSocket 地址和前端静态文件路径，并用 ``lifespan`` 管理启动与关闭。

输入和输出：
    输入是配置文件路径、测试用配置或前端打包目录；输出是一个完整的 FastAPI 应用。
    浏览器访问 ``/api/...`` 时，本文件把请求转交给状态或命令模块并返回结果。

模块关系和典型数据流：
    ``config -> hub -> store -> udp -> commands`` 是核心对象的创建和依赖顺序。
    浏览器请求则大致按照 ``API -> models/commands/store -> 响应`` 流动。

阅读重点：
    ``create_app()`` 中对象的创建顺序、``lifespan`` 和各路由分区；
    具体的状态保存、UDP 收发和命令规则分别在 ``state.py``、``udp.py`` 和 ``commands.py``。
    app → config → models → events → state → udp → commands 是核心对象的创建和依赖顺序。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import secrets
from typing import Any, AsyncIterator, AsyncGenerator, Callable, TypeVar
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .commands import CommandBlockedError, CommandService, CommandValidationError
from .cesium_api import credential_router
from .cesium_credentials import CesiumCredentialStore
from .config import AppSettings, load_settings
from .events import WebSocketHub
from .models import (
    BasicCommandRequest,
    CommandResponse,
    FormationCommandRequest,
    FormationSettingsRequest,
    FormationsUpdateRequest,
    WorkbenchCommandRequest,
)
from .state import RevisionConflict, StateStore
from .udp import UDPService, UDPUnavailable


_HASHED_ASSET_PATH = re.compile(
    r"^/assets/(?:.*/)?[^/]+-[A-Za-z0-9_-]{8,}\.[^/]+$",
)
_HTML_CACHE_CONTROL = "no-store, no-cache, must-revalidate"
_HASHED_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


def create_app(
    *,
    config_path: str | Path | None = None,
    settings: AppSettings | None = None,
    static_dir: str | Path | None = None,
    start_udp: bool = True,
    cesium_credentials: CesiumCredentialStore | None = None,
) -> FastAPI:
    """Create the standalone application.

    ``config_path`` and ``settings`` are mutually exclusive. ``start_udp=False``
    exists for isolated API tests; production callers should keep the default.
    """

    if config_path is not None and settings is not None:
        raise ValueError("config_path 与 settings 不得同时提供。")
    app_settings = settings if settings is not None else load_settings(config_path)
    web_root = (
        Path(static_dir).expanduser().resolve()
        if static_dir is not None
        else Path(__file__).resolve().parents[1] / "frontend" / "dist"
    )

    hub = WebSocketHub(app_settings.limits.websocket_queue)
    store = StateStore(app_settings, hub)
    udp = UDPService(app_settings, store)
    commands = CommandService(store, udp)
    store.set_new_drone_handler(commands.config_updates_for_discovery)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        await store.start()
        try:
            if start_udp:
                await udp.start()
            yield
        finally:
            if start_udp:
                await udp.stop()
            await store.stop()

    app = FastAPI(
        title="Ground Control Panel Web API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.hub = hub
    app.state.store = store
    app.state.udp = udp
    app.state.commands = commands
    app.state.static_dir = web_root
    app.state.shutdown_token = None
    app.state.request_shutdown = None
    app.include_router(credential_router(cesium_credentials or CesiumCredentialStore()))

    @app.exception_handler(RevisionConflict)
    async def revision_conflict_handler(_request: Any, exc: RevisionConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "submitted_revision": exc.expected,
                "current_revision": exc.actual,
            },
        )

    @app.exception_handler(CommandBlockedError)
    async def command_blocked_handler(_request: Any, exc: CommandBlockedError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CommandValidationError)
    async def command_validation_handler(
        _request: Any,
        exc: CommandValidationError,
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Any, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(UDPUnavailable)
    async def udp_unavailable_handler(_request: Any, exc: UDPUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.middleware("http")
    async def local_origin_guard(request: Request, call_next: Any) -> Any:
        """Reject cross-site browser requests to every state-changing API."""

        if request.url.path.startswith("/api/") and request.method not in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            origin = request.headers.get("origin")
            fetch_site = request.headers.get("sec-fetch-site", "").lower()
            if fetch_site == "cross-site" or (
                origin and not _origin_allowed(
                    origin,
                    app_settings.server.host,
                    app_settings.server.port,
                )
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "只允许本机同源页面修改地面站状态。"},
                )
        response = await call_next(request)
        _set_frontend_cache_headers(request.url.path, response)
        if request.url.path.startswith("/api/earth/cesium-token"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # ------------------------------------------------------------------- state
    @app.get("/api/bootstrap")
    async def get_bootstrap() -> dict[str, Any]:
        return await store.snapshot()

    @app.get("/api/health")
    async def get_health() -> dict[str, Any]:
        udp_health = await store.udp_health()
        healthy = bool(
            udp_health["receiver_ready"]
            and udp_health["sender_ready"]
            and udp_health.get("audit_ready", False)
        )
        return {
            "status": "ok" if healthy else "degraded",
            "udp": udp_health,
            "udp_workers": udp.diagnostics(),
            "websocket": hub.diagnostics(),
            "websocket_clients": hub.client_count,
            "receive_buffer": store.receive_queue_diagnostics(),
            # Compatibility alias for older diagnostic clients.
            "receive_queue": store.receive_queue_diagnostics(),
        }

    @app.get("/api/runtime")
    async def get_runtime() -> dict[str, Any]:
        return {
            "application": "GroundControlPanel-2C/web_app",
            "pid": os.getpid(),
        }

    @app.post("/api/runtime/shutdown", status_code=202, include_in_schema=False)
    async def shutdown_runtime(request: Request) -> dict[str, str]:
        expected = app.state.shutdown_token
        callback = app.state.request_shutdown
        supplied = request.headers.get("x-gcs-shutdown-token", "")
        if (
            not isinstance(expected, str)
            or not expected
            or not secrets.compare_digest(supplied, expected)
        ):
            raise HTTPException(status_code=403, detail="Invalid shutdown token.")
        if not callable(callback):
            raise HTTPException(status_code=503, detail="Shutdown is unavailable.")
        callback()
        return {"status": "stopping"}

    @app.get("/api/logs/export", response_class=PlainTextResponse)
    async def export_logs() -> PlainTextResponse:
        return PlainTextResponse(
            await store.export_logs_text(),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="ground-control-log.txt"'},
        )

    @app.put("/api/formation-settings")
    async def update_formation_settings(
        request: FormationSettingsRequest,
    ) -> dict[str, Any]:
        return await commands.update_formation_settings(
            request.form_type,
            request.spacing,
        )

    @app.put("/api/formations")
    async def update_formations(request: FormationsUpdateRequest) -> dict[str, Any]:
        return await commands.publish_formations(
            request.revision,
            request.members,
            request.leaders,
        )

    # ---------------------------------------------------------------- commands
    @app.post("/api/commands/basic", response_model=CommandResponse)
    async def send_basic(request: BasicCommandRequest) -> CommandResponse:
        return await commands.send_basic(request)

    @app.post("/api/commands/formation", response_model=CommandResponse)
    async def send_formation(request: FormationCommandRequest) -> CommandResponse:
        return await commands.send_formation(request)

    @app.post("/api/commands/workbench", response_model=CommandResponse)
    async def send_workbench(request: WorkbenchCommandRequest) -> CommandResponse:
        return await commands.send_workbench(request)

    @app.post("/api/commands/abort", response_model=CommandResponse)
    async def abort() -> CommandResponse:
        return await commands.abort()

    @app.post("/api/commands/resume", response_model=CommandResponse)
    async def resume() -> CommandResponse:
        return await commands.resume()

    # ------------------------------------------------------------------- clear
    @app.delete("/api/tracks")
    async def clear_tracks() -> dict[str, bool]:
        await store.clear_tracks()
        await store.append_log("[轨迹] 已推进清空 epoch，通知浏览器清空实际轨迹。")
        return {"ok": True}

    @app.delete("/api/goto-targets")
    async def clear_goto_targets() -> dict[str, bool]:
        await store.clear_goto_targets()
        await store.append_log("[Goto] 已清除全部期望点。")
        return {"ok": True}

    @app.delete("/api/logs")
    async def clear_logs() -> dict[str, bool]:
        await store.clear_logs()
        return {"ok": True}

    # --------------------------------------------------------------- websocket
    @app.websocket("/api/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin and not _origin_allowed(
            origin,
            app_settings.server.host,
            app_settings.server.port,
        ):
            await websocket.close(code=1008, reason="只允许本机浏览器连接。")
            return

        await websocket.accept()
        queue, baseline, snapshot = await store.subscribe_snapshot()
        try:
            await websocket.send_json(
                hub.snapshot_envelope(snapshot, baseline)
            )
            while True:
                await websocket.send_json(await queue.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await hub.unsubscribe(queue)

    # ------------------------------------------------------------- static app
    assets_dir = web_root / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    async def serve_frontend(path: str) -> Any:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")

        if web_root.is_dir() and path:
            candidate = (web_root / path).resolve()
            if web_root == candidate or web_root in candidate.parents:
                if candidate.is_file():
                    return FileResponse(candidate)
        index = web_root / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={
                    "detail": "前端构建产物不存在。请构建 web_app/frontend 或检查 static_dir。"
            },
        )

    return app


def _origin_allowed(origin: str, configured_host: str, configured_port: int) -> bool:
    try:
        parsed = urlsplit(origin)
        origin_port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "http":
        return False
    hostname = (parsed.hostname or "").lower()
    configured = configured_host.lower()
    loopback_names = {"localhost", "127.0.0.1", "::1"}
    allowed_hosts = loopback_names if configured in loopback_names else {configured}
    effective_port = origin_port if origin_port is not None else 80
    return hostname in allowed_hosts and effective_port == configured_port


def _set_frontend_cache_headers(path: str, response: Any) -> None:
    """Prevent stale HTML while keeping Vite's content-hashed assets cacheable."""

    if _HASHED_ASSET_PATH.fullmatch(path):
        response.headers["Cache-Control"] = _HASHED_ASSET_CACHE_CONTROL
        return

    content_type = response.headers.get("content-type", "").lower()
    if content_type.startswith("text/html"):
        response.headers["Cache-Control"] = _HTML_CACHE_CONTROL
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
