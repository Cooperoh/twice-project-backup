"""Per-Windows-user Cesium token storage. Never store credentials in the checkout."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import tempfile


_MAGIC = b"GCS-CESIUM-DPAPI\x00"


class CredentialError(Exception):
    """Messages are safe for UI display; do not include token values."""


def normalize_token(value: object) -> str:
    if not isinstance(value, str):
        raise CredentialError("请输入 Token，或选择只包含 Token 的文本文件。")
    token = value.strip().lstrip("\ufeff").strip()
    if len(token) > 4096 or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
        raise CredentialError("Token 格式不正确，请粘贴完整的 Cesium ion Access Token。")
    return token


def credential_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return root / "GroundControlPanel" / "cesium-token.dat"


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise CredentialError("当前自动保存功能使用 Windows 本机加密，请在 Windows 地面站中导入。")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    output = Blob()
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN; no machine-wide flag, so protection is user-scoped.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise CredentialError("无法读取或保存本机加密 Token，请重新导入。")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


class CesiumCredentialStore:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else credential_path()

    def read(self) -> str | None:
        try:
            with self.path.open("rb") as stream:
                data = stream.read(65_537)
        except FileNotFoundError:
            return None
        except OSError:
            raise CredentialError("无法读取本机 Token 文件，请检查目录权限或重新导入。") from None
        if len(data) > 65_536 or not data.startswith(_MAGIC):
            raise CredentialError("本机 Token 文件已损坏，请重新导入。")
        try:
            return normalize_token(_dpapi(data[len(_MAGIC):], decrypt=True).decode("utf-8"))
        except UnicodeError:
            raise CredentialError("本机 Token 文件已损坏，请重新导入。") from None

    def status(self) -> dict:
        try:
            token = self.read()
            state = "saved" if token else "missing"
            message = "已保存，下次启动自动读取。" if token else "尚未导入 Token，可使用普通地球。"
        except CredentialError as error:
            state, message = "unreadable", str(error)
        return {"configured": state == "saved", "state": state, "message": message,
                "storage_path": str(self.path), "supported": os.name == "nt"}

    def save(self, value: str) -> None:
        token = normalize_token(value)
        data = _MAGIC + _dpapi(token.encode("utf-8"))
        temporary: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".cesium-", delete=False) as stream:
                temporary = stream.name
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise CredentialError("无法保存本机 Token，请检查用户目录的写入权限。") from None
        finally:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink(missing_ok=True)

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            raise CredentialError("无法清除本机 Token，请检查用户目录权限。") from None
