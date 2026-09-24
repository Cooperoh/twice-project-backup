#!/usr/bin/env python3

"""
from client.autopilot import pack_send_frame

frame = pack_send_frame(
    seq=1,              # 计数器，0~65535
    target_system=1,    # 外部飞控/目标设备ID
    lat=40.8663949,
    lon=109.5596,
    alt=1380,
    spd=125,            # IAS / 表速，m/s
)

# UDP 示例
# sock.sendto(frame, ("目标IP", 目标端口))

# 串口示例
# serial_port.write(frame)

frame 是 bytes，可以直接发。每次发送后建议：
seq = (seq + 1) & 0xFFFF
"""

from __future__ import annotations

from dataclasses import dataclass

from .frame_common import (
    build_frame,
    decode_alt,
    decode_lat_lon,
    decode_spd,
    encode_alt,
    encode_lat_lon,
    encode_spd,
    require_int,
    split_frame,
)

SEND_FRAME_MSG_ID = 1
SEND_PAYLOAD_LEN = 17


@dataclass(frozen=True)
class SentFrame:
    """Fields in the frame sent to the external flight controller."""

    seq: int
    target_system: int
    lat: float
    lon: float
    alt: float
    spd: float


def pack_send_frame(
    *,
    seq: int,
    target_system: int,
    lat: float,
    lon: float,
    alt: float,
    spd: float,
) -> bytes:
    """Pack one complete send frame and return bytes ready to transmit."""

    payload = bytearray()

    # 1-2: seq, counter, uint16, little-endian.
    seq_raw = require_int("seq", seq, 0, 0xFFFF)
    payload += seq_raw.to_bytes(2, byteorder="little", signed=False)

    # 3: target_system, target external flight-controller ID, uint8.
    target_system_raw = require_int("target_system", target_system, 0, 0xFF)
    payload += target_system_raw.to_bytes(1, byteorder="little", signed=False)

    # 4-7: lat, degrees * 3600 * 3000, int32, little-endian.
    lat_raw = encode_lat_lon("lat", lat)
    payload += lat_raw.to_bytes(4, byteorder="little", signed=True)

    # 8-11: lon, degrees * 3600 * 3000, int32, little-endian.
    lon_raw = encode_lat_lon("lon", lon)
    payload += lon_raw.to_bytes(4, byteorder="little", signed=True)

    # 12-15: alt, (meters + 500) / 0.01, uint32, little-endian.
    alt_raw = encode_alt(alt)
    payload += alt_raw.to_bytes(4, byteorder="little", signed=False)

    # 16-17: spd, speed/IAS / 0.01, uint16, little-endian.
    spd_raw = encode_spd(spd)
    payload += spd_raw.to_bytes(2, byteorder="little", signed=False)

    if len(payload) != SEND_PAYLOAD_LEN:
        raise AssertionError(f"send payload must be {SEND_PAYLOAD_LEN} bytes")

    return build_frame(SEND_FRAME_MSG_ID, payload)


def parse_sent_frame(frame: bytes | bytearray | memoryview | str) -> SentFrame:
    """Parse msg_id=1 frames; useful for tests and debugging sent bytes."""

    _msg_id, payload = split_frame(
        frame,
        expected_msg_id=SEND_FRAME_MSG_ID,
        expected_payload_len=SEND_PAYLOAD_LEN,
    )

    seq = int.from_bytes(payload[0:2], byteorder="little", signed=False)
    target_system = payload[2]

    lat_raw = int.from_bytes(payload[3:7], byteorder="little", signed=True)
    lon_raw = int.from_bytes(payload[7:11], byteorder="little", signed=True)
    alt_raw = int.from_bytes(payload[11:15], byteorder="little", signed=False)
    spd_raw = int.from_bytes(payload[15:17], byteorder="little", signed=False)

    return SentFrame(
        seq=seq,
        target_system=target_system,
        lat=decode_lat_lon(lat_raw),
        lon=decode_lat_lon(lon_raw),
        alt=decode_alt(alt_raw),
        spd=decode_spd(spd_raw),
    )
