#!/usr/bin/env python3

"""
如果你收到的是一整条完整数据帧：

from client.autopilot import ProtocolError, parse_receive_frame

try:
    data = parse_receive_frame(raw_frame)
except ProtocolError:
    # 不是这个协议、长度不对、帧头不对、校验不对，都会进这里
    data = None

if data is not None:
    print(data.seq)
    print(data.sending_system)
    print(data.phase)
    print(data.lat)
    print(data.lon)
    print(data.alt)
    print(data.spd)
"""

from __future__ import annotations

from dataclasses import dataclass

from .frame_common import decode_alt, decode_lat_lon, decode_spd, split_frame

RECEIVE_FRAME_MSG_ID = 2
RECEIVE_PAYLOAD_LEN = 18


@dataclass(frozen=True)
class ReceivedFrame:
    """Fields parsed from a frame received from the external flight controller."""

    seq: int
    sending_system: int
    phase: int
    lat: float
    lon: float
    alt: float
    spd: float


def parse_receive_frame(frame: bytes | bytearray | memoryview | str) -> ReceivedFrame:
    """Parse a msg_id=2 receive frame into fields you can access as attributes."""

    _msg_id, payload = split_frame(
        frame,
        expected_msg_id=RECEIVE_FRAME_MSG_ID,
        expected_payload_len=RECEIVE_PAYLOAD_LEN,
    )

    # 1-2: seq, counter, uint16, little-endian.
    seq = int.from_bytes(payload[0:2], byteorder="little", signed=False)

    # 3: sending_system, source external flight-controller ID, uint8.
    sending_system = payload[2]

    # 4: phase, current mode/stage, uint8.
    phase = payload[3]

    # 5-8: lat, int32 raw value -> degrees.
    lat_raw = int.from_bytes(payload[4:8], byteorder="little", signed=True)
    lat = decode_lat_lon(lat_raw)

    # 9-12: lon, int32 raw value -> degrees.
    lon_raw = int.from_bytes(payload[8:12], byteorder="little", signed=True)
    lon = decode_lat_lon(lon_raw)

    # 13-16: alt, uint32 raw value -> meters.
    alt_raw = int.from_bytes(payload[12:16], byteorder="little", signed=False)
    alt = decode_alt(alt_raw)

    # 17-18: spd, speed/IAS raw value -> meters per second.
    spd_raw = int.from_bytes(payload[16:18], byteorder="little", signed=False)
    spd = decode_spd(spd_raw)

    return ReceivedFrame(
        seq=seq,
        sending_system=sending_system,
        phase=phase,
        lat=lat,
        lon=lon,
        alt=alt,
        spd=spd,
    )
