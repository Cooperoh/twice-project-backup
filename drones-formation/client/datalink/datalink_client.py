#!/usr/bin/env python3
"""Reserved interface for the future field data-link bridge.

This client module is deliberately not imported by ``runtime.py`` yet.  The business
frame, node addressing, checksum, and payload rules must come from the actual
data-link protocol before this class is implemented or connected to flight
behavior.
"""

from __future__ import annotations

from typing import Any


class DataLinkBridge:
    """Future drop-in bridge surface matching the behavior-facing FGCBridge API."""

    async def start(self) -> None:
        raise NotImplementedError("data-link business protocol is not defined")

    async def next_cmd(self) -> dict[str, Any]:
        raise NotImplementedError("data-link business protocol is not defined")

    async def next_peer(self) -> dict[int, dict[str, Any]]:
        raise NotImplementedError("data-link business protocol is not defined")

    def send_to_peers(self, payload: dict[str, Any]) -> None:
        raise NotImplementedError("data-link business protocol is not defined")

    def send_gui(self, payload: dict[str, Any]) -> None:
        raise NotImplementedError("data-link business protocol is not defined")

    def send_telemetry(self, **fields: Any) -> None:
        raise NotImplementedError("data-link business protocol is not defined")

    def send_log(self, text: str) -> None:
        raise NotImplementedError("data-link business protocol is not defined")

    def patch_print(self) -> None:
        raise NotImplementedError("data-link business protocol is not defined")

    def close(self) -> None:
        raise NotImplementedError("data-link business protocol is not defined")
