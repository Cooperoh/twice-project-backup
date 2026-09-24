"""Local-only credential endpoints, separate from telemetry, audit and bootstrap."""
from __future__ import annotations

import asyncio
import ipaddress
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx

from .cesium_credentials import CesiumCredentialStore, CredentialError, normalize_token


async def validate_terrain_token(token: str, origin: str | None = None) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    if origin:
        headers.update({"Origin": origin, "Referer": origin + "/"})
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response = await client.get("https://api.cesium.com/v1/assets/1/endpoint", headers=headers)
        if response.status_code in {401, 403, 404}:
            raise HTTPException(422, "Token 无效或无权访问世界地形，请检查资产权限及允许的站点地址。")
        if response.status_code != 200:
            raise HTTPException(503, "Cesium 地形服务暂时不可用，请稍后重试；原 Token 保留。")
        if response.json().get("type") != "TERRAIN":
            raise HTTPException(422, "该 Token 无法访问世界地形。")
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "暂时无法连接 Cesium 验证 Token，请检查网络后重试；原 Token 保留。") from None


def credential_router(store: CesiumCredentialStore) -> APIRouter:
    async def local_request(request: Request) -> None:
        try:
            local = ipaddress.ip_address(request.client.host).is_loopback if request.client else False
        except ValueError:
            local = False
        # Custom header forces cross-origin scripts through a rejected CORS preflight.
        # Check Host as well to keep DNS rebinding from exposing the user's credential.
        if (not local or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}
                or request.headers.get("x-gcs-token-request") != "1"
                or request.headers.get("sec-fetch-site") == "cross-site"):
            raise HTTPException(403, "请从本机地面站页面管理 Token。")

    router = APIRouter(prefix="/api/earth/cesium-token", dependencies=[Depends(local_request)])
    mutation = asyncio.Lock()

    def reply(body: dict) -> JSONResponse:
        return JSONResponse(body, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    @router.get("")
    async def status() -> JSONResponse:
        return reply(store.status())

    @router.post("/read")
    async def read() -> JSONResponse:
        try:
            return reply({"token": store.read()})
        except CredentialError as error:
            raise HTTPException(409, str(error)) from None

    @router.put("")
    async def save(request: Request) -> JSONResponse:
        # Parse manually so validation responses cannot echo a submitted credential.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise HTTPException(413, "Token 文件过大，请选择只包含 Token 的文本文件。")
        try:
            payload = json.loads(body)
            token = normalize_token(payload.get("token") if isinstance(payload, dict) else None)
        except (ValueError, CredentialError) as error:
            message = str(error) if isinstance(error, CredentialError) else "无法读取 Token，请检查输入内容。"
            raise HTTPException(422, message) from None
        async with mutation:
            await validate_terrain_token(token, request.headers.get("origin"))
            try:
                store.save(token)
            except CredentialError as error:
                raise HTTPException(409, str(error)) from None
            return reply(store.status())

    @router.delete("")
    async def clear() -> JSONResponse:
        async with mutation:
            try:
                store.clear()
            except CredentialError as error:
                raise HTTPException(409, str(error)) from None
            return reply(store.status())

    return router
