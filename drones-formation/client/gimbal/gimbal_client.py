#!/usr/bin/env python3
"""Reserved interface for a future local gimbal client.

The gimbal transport and frame protocol are not known yet, so this client is
not imported or started by ``runtime.py``.  It records only the intended
lifecycle and behavior-facing call surface.
"""

from __future__ import annotations

from typing import Any


class GimbalClient:
    """Future local-gimbal API; no transport or provisional protocol is assumed."""

    async def start(self) -> None:
        raise NotImplementedError("gimbal protocol is not defined")

    async def stop(self) -> None:
        raise NotImplementedError("gimbal protocol is not defined")

    def get_latest_state(self) -> Any | None:
        raise NotImplementedError("gimbal protocol is not defined")

    async def send_command(self, command: Any) -> None:
        raise NotImplementedError("gimbal protocol is not defined")
