#!/usr/bin/env python3
"""Autopilot client and its binary frame protocol."""

from .frame_common import (
    HEAD1,
    HEAD2,
    ProtocolError,
    build_frame,
    checksum_payload,
    split_frame,
)
from .receive_frame import RECEIVE_FRAME_MSG_ID, ReceivedFrame, parse_receive_frame
from .send_frame import SEND_FRAME_MSG_ID, SentFrame, pack_send_frame, parse_sent_frame
from .stream_reader import FrameStreamParser, LatestFrameReader
from .autopilot_client import FlightController, FlightState, FlightTarget


def parse_frame(frame):
    """Parse a supported frame by msg_id."""

    msg_id, _payload = split_frame(frame)
    if msg_id == SEND_FRAME_MSG_ID:
        return parse_sent_frame(frame)
    if msg_id == RECEIVE_FRAME_MSG_ID:
        return parse_receive_frame(frame)
    raise ProtocolError(f"unsupported msg_id={msg_id}")


__all__ = [
    "HEAD1",
    "HEAD2",
    "RECEIVE_FRAME_MSG_ID",
    "SEND_FRAME_MSG_ID",
    "ProtocolError",
    "FlightController",
    "FlightState",
    "FlightTarget",
    "FrameStreamParser",
    "LatestFrameReader",
    "ReceivedFrame",
    "SentFrame",
    "build_frame",
    "checksum_payload",
    "pack_send_frame",
    "parse_frame",
    "parse_receive_frame",
    "parse_sent_frame",
    "split_frame",
]
