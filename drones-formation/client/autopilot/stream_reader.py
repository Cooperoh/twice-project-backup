#!/usr/bin/env python3
"""Read protocol frames from a continuous byte stream.

Serial ports deliver bytes continuously. A single read may contain half a
frame, one exact frame, multiple frames, or random bytes before a frame. This
module keeps a small buffer, cuts complete receive frames out of that stream,
and keeps only the newest parsed frame when used with a background reader.

两种用法。

1. 串口后台线程，只保留最新数据

import serial
from client.autopilot import LatestFrameReader

ser = serial.Serial("COM3", baudrate=115200, timeout=0.1)

reader = LatestFrameReader(ser)
reader.start()

data = reader.get_latest()
if data is not None:
    print(data.lat, data.lon, data.alt, data.spd)

reader.stop()
ser.close()

2. 自己读串口，只用切帧器

from client.autopilot import FrameStreamParser

parser = FrameStreamParser()

chunk = serial_port.read(128)
frames = parser.feed(chunk)

for data in frames:
    print(data.lat, data.lon, data.alt, data.spd)

3. async 代码里读取最新数据时，直接调用同步方法就可以：

async def some_task(reader):
    while True:
        data = reader.get_latest()
        if data is not None:
            print(data.lat, data.lon, data.alt, data.spd)

        await asyncio.sleep(0.05)

需要注意的点：

不要在 async 函数里直接调用 serial.read()，会阻塞事件循环。
LatestFrameReader 的线程里不要调用 async 飞控接口。
async 循环里要用 await asyncio.sleep(...)，不要写纯 while True: pass。
程序退出时调用 reader.stop()，然后 ser.close()。
"""

from __future__ import annotations

import threading
from typing import Any

from .frame_common import FRAME_OVERHEAD, HEAD1, HEAD2, ProtocolError
from .receive_frame import (
    RECEIVE_FRAME_MSG_ID,
    RECEIVE_PAYLOAD_LEN,
    ReceivedFrame,
    parse_receive_frame,
)

HEADER = bytes([HEAD1, HEAD2])
RECEIVE_TOTAL_LEN = RECEIVE_PAYLOAD_LEN + FRAME_OVERHEAD


class FrameStreamParser:
    """Cut complete received frames from arbitrary byte chunks."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes | bytearray | memoryview) -> list[ReceivedFrame]:
        """Add bytes from serial.read() and return all complete valid frames."""

        if not chunk:
            return []

        self._buffer.extend(bytes(chunk))
        frames: list[ReceivedFrame] = []

        while True:
            start = self._buffer.find(HEADER)

            if start < 0:
                # Keep a trailing 0xEB because the next read may start with 0x90.
                if self._buffer[-1:] == bytes([HEAD1]):
                    self._buffer[:] = self._buffer[-1:]
                else:
                    self._buffer.clear()
                break

            if start > 0:
                del self._buffer[:start]

            # Need at least EB 90 + msg_id + len before deciding frame size.
            if len(self._buffer) < 4:
                break

            msg_id = self._buffer[2]
            payload_len = self._buffer[3]

            # This stream reader only extracts received data frames.
            # If bytes look like a header but are not msg_id=2/len=18, resync.
            if msg_id != RECEIVE_FRAME_MSG_ID or payload_len != RECEIVE_PAYLOAD_LEN:
                del self._buffer[0]
                continue

            if len(self._buffer) < RECEIVE_TOTAL_LEN:
                break

            raw_frame = bytes(self._buffer[:RECEIVE_TOTAL_LEN])
            try:
                frames.append(parse_receive_frame(raw_frame))
            except ProtocolError:
                # Bad checksum or damaged bytes. Drop one byte and search again
                # so a later EB 90 inside the buffer can still be found.
                del self._buffer[0]
                continue

            del self._buffer[:RECEIVE_TOTAL_LEN]

        return frames

    def clear(self) -> None:
        """Discard buffered partial data."""

        self._buffer.clear()


class LatestFrameReader:
    """Background serial reader that stores only the newest parsed frame."""

    def __init__(
        self,
        serial_port: Any,
        *,
        read_size: int = 128,
        idle_sleep: float = 0.01,
    ) -> None:
        if read_size <= 0:
            raise ValueError("read_size must be > 0")
        if idle_sleep < 0:
            raise ValueError("idle_sleep must be >= 0")

        self.serial_port = serial_port
        self.read_size = int(read_size)
        self.idle_sleep = float(idle_sleep)

        self._parser = FrameStreamParser()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: ReceivedFrame | None = None
        self._last_error: Exception | None = None

    def start(self) -> None:
        """Start the background reader thread."""

        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = 1.0) -> None:
        """Ask the background thread to stop and wait briefly for it."""

        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def get_latest(self) -> ReceivedFrame | None:
        """Return the newest successfully parsed frame, or None."""

        with self._lock:
            return self._latest

    def get_last_error(self) -> Exception | None:
        """Return the last serial read exception, if the reader stopped on one."""

        with self._lock:
            return self._last_error

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self.serial_port.read(self.read_size)
            except Exception as exc:  # pragma: no cover - depends on serial driver
                with self._lock:
                    self._last_error = exc
                break

            if not chunk:
                if self.idle_sleep:
                    self._stop.wait(self.idle_sleep)
                continue

            frames = self._parser.feed(chunk)
            if not frames:
                continue

            with self._lock:
                self._latest = frames[-1]
