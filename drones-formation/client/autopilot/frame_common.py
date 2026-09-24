#!/usr/bin/env python3
"""Shared frame utilities for the autopilot protocol."""

from __future__ import annotations

import math
from typing import Any

HEAD1 = 0xEB
HEAD2 = 0x90
FRAME_OVERHEAD = 5
LAT_LON_SCALE = 3600 * 3000
CENTI_SCALE = 100


class ProtocolError(ValueError):
    """Raised when a frame does not match the expected protocol format."""


def checksum_payload(payload: bytes | bytearray | memoryview) -> int:
    """Checksum rule: sum payload bytes only, then take modulo 256."""

    return sum(bytes(payload)) % 256


def build_frame(msg_id: int, payload: bytes | bytearray | memoryview) -> bytes:
    """Build EB 90 + msg_id + len + payload + checksum."""

    msg_id = require_int("msg_id", msg_id, 0, 0xFF)
    payload_bytes = bytes(payload)
    if len(payload_bytes) > 0xFF:
        raise ValueError("payload is too long for one-byte len field")

    return bytes(
        [HEAD1, HEAD2, msg_id, len(payload_bytes)]
        + list(payload_bytes)
        + [checksum_payload(payload_bytes)]
    )


def frame_to_bytes(frame: bytes | bytearray | memoryview | str) -> bytes:
    """Accept bytes-like input or a debugging hex string such as 'EB 90 01'."""

    if isinstance(frame, str):
        text = frame.strip()
        if not text:
            raise ProtocolError("empty hex frame string")
        text = text.replace("0x", "").replace("0X", "")
        for separator in ",;:-_":
            text = text.replace(separator, " ")
        hex_text = "".join(text.split())
        try:
            return bytes.fromhex(hex_text)
        except ValueError as exc:
            raise ProtocolError("frame string must contain hexadecimal bytes") from exc

    try:
        return bytes(frame)
    except TypeError as exc:
        raise ProtocolError("frame must be bytes-like or a hexadecimal string") from exc


def split_frame(
    frame: bytes | bytearray | memoryview | str,
    *,
    expected_msg_id: int | None = None,
    expected_payload_len: int | None = None,
) -> tuple[int, bytes]:
    """Validate frame header, length and checksum, then return msg_id and payload."""

    raw = frame_to_bytes(frame)
    if len(raw) < FRAME_OVERHEAD:
        raise ProtocolError(f"frame too short: {len(raw)} bytes")

    if raw[0] != HEAD1 or raw[1] != HEAD2:
        raise ProtocolError(
            f"invalid frame header: got 0x{raw[0]:02X} 0x{raw[1]:02X}"
        )

    msg_id = raw[2]
    payload_len = raw[3]
    expected_total_len = payload_len + FRAME_OVERHEAD
    if len(raw) != expected_total_len:
        raise ProtocolError(
            f"frame length mismatch: len byte={payload_len}, "
            f"expected total={expected_total_len}, got total={len(raw)}"
        )

    if expected_msg_id is not None and msg_id != expected_msg_id:
        raise ProtocolError(f"expected msg_id={expected_msg_id}, got msg_id={msg_id}")

    if expected_payload_len is not None and payload_len != expected_payload_len:
        raise ProtocolError(
            f"expected payload len={expected_payload_len}, got len={payload_len}"
        )

    payload = raw[4:-1]
    expected_checksum = checksum_payload(payload)
    actual_checksum = raw[-1]
    if actual_checksum != expected_checksum:
        raise ProtocolError(
            f"checksum mismatch: expected 0x{expected_checksum:02X}, "
            f"got 0x{actual_checksum:02X}"
        )

    return msg_id, payload


def require_finite_number(name: str, value: Any) -> float:
    """Convert a value to a finite float and reject NaN/inf."""

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def require_int(name: str, value: Any, minimum: int, maximum: int) -> int:
    """Convert a value to int and check the inclusive range."""

    number = require_finite_number(name, value)
    if not number.is_integer():
        raise ValueError(f"{name} must be an integer value")
    integer = int(number)
    if integer < minimum or integer > maximum:
        raise ValueError(f"{name}={integer} out of range [{minimum}, {maximum}]")
    return integer


def encode_lat_lon(name: str, value: Any) -> int:
    """lat/lon degrees -> protocol int32 raw value."""

    raw = round(require_finite_number(name, value) * LAT_LON_SCALE)
    if raw < -(2**31) or raw > 2**31 - 1:
        raise ValueError(f"{name} raw value={raw} out of int32 range")
    return raw


def decode_lat_lon(raw: int) -> float:
    """Protocol int32 raw value -> lat/lon degrees."""

    return raw / LAT_LON_SCALE


def encode_alt(value: Any) -> int:
    """Altitude meters -> protocol uint32 raw value."""

    raw = round((require_finite_number("alt", value) + 500.0) * CENTI_SCALE)
    if raw < 0 or raw > 0xFFFFFFFF:
        raise ValueError(f"alt raw value={raw} out of uint32 range")
    return raw


def decode_alt(raw: int) -> float:
    """Protocol uint32 raw value -> altitude meters."""

    return raw / CENTI_SCALE - 500.0


def encode_spd(value: Any) -> int:
    """Speed/IAS meters per second -> protocol uint16 raw value."""

    raw = round(require_finite_number("spd", value) * CENTI_SCALE)
    if raw < 0 or raw > 0xFFFF:
        raise ValueError(f"spd raw value={raw} out of uint16 range")
    return raw


def decode_spd(raw: int) -> float:
    """Protocol uint16 raw value -> speed/IAS meters per second."""

    return raw / CENTI_SCALE
