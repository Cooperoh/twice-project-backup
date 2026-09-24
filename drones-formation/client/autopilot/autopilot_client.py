#!/usr/bin/env python3
"""Flight-controller adapter for the external binary frame protocol."""

from __future__ import annotations

import asyncio
import math
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any

from .send_frame import pack_send_frame
from .stream_reader import FrameStreamParser


@dataclass(frozen=True)
class FlightState:
    seq: int
    system_id: int
    phase: int
    lat: float
    lon: float
    alt: float
    speed: float
    heading: float
    heading_valid: bool
    received_at: float


@dataclass(frozen=True)
class FlightTarget:
    seq: int
    lat: float
    lon: float
    alt: float
    speed: float
    sent_at: float


class FlightController:
    """Read telemetry frames and send target-point command frames."""

    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        serial_port: Any | None = None,
        udp_socket: socket.socket | None = None,
        udp_rx_socket: socket.socket | None = None,
        udp_tx_socket: socket.socket | None = None,
    ) -> None:
        self.cfg = dict(cfg)
        self.transport = str(self.cfg.get("fc_transport", "udp")).strip().lower()
        self.system_id = int(self.cfg.get("fc_id", self.cfg.get("id", 0)))
        self.accept_any_system = bool(self.cfg.get("accept_any_system", False))
        self.poll_interval = float(self.cfg.get("state_poll_interval", 0.05))

        self._serial_port = serial_port
        self._udp_rx_socket = udp_rx_socket if udp_rx_socket is not None else udp_socket
        self._udp_tx_socket = udp_tx_socket
        self._target_addr: tuple[str, int] | None = None
        self._parser = FrameStreamParser()
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: FlightState | None = None
        self._last_target: FlightTarget | None = None
        self._last_error: Exception | None = None
        self._seq = 0
        self._send_frame_print_interval = float(self.cfg.get("send_frame_print_interval", 0))
        self._last_send_frame_print_at = 0.0

    async def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()
        self._last_error = None

        if self.transport == "serial":
            self._ensure_serial_open()
            target = self._serial_read_loop
        elif self.transport == "udp":
            self._ensure_udp_open()
            target = self._udp_read_loop
        else:
            raise ValueError(f"unsupported transport: {self.transport}")

        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

        udp_sockets = [
            sock
            for sock in (self._udp_rx_socket, self._udp_tx_socket)
            if sock is not None
        ]
        closed_ids = set()
        for sock in udp_sockets:
            if id(sock) in closed_ids:
                continue
            closed_ids.add(id(sock))
            try:
                sock.close()
            except OSError:
                pass
        self._udp_rx_socket = None
        self._udp_tx_socket = None

        if self._serial_port is not None and hasattr(self._serial_port, "close"):
            try:
                self._serial_port.close()
            except Exception:
                pass

    async def get_state(
        self,
        *,
        require_heading: bool = False,
        timeout: float | None = None,
    ) -> FlightState:
        deadline = None
        loop = asyncio.get_running_loop()
        if timeout is not None:
            deadline = loop.time() + float(timeout)

        while True:
            with self._lock:
                state = self._state
                last_error = self._last_error

            if state is not None and (not require_heading or state.heading_valid):
                return state

            if last_error is not None:
                raise RuntimeError("flight-controller reader stopped") from last_error

            if deadline is not None and loop.time() >= deadline:
                raise TimeoutError("timed out waiting for flight-controller telemetry")

            await asyncio.sleep(self.poll_interval)

    async def goto_location(self, lat: float, lon: float, alt: float, speed: float | None) -> None:
        """Send one msg_id=1 target-point control frame through serial or UDP."""
        speed_value = float(speed) if speed is not None else math.nan
        if not math.isfinite(speed_value):
            raise ValueError("speed must be a finite number")

        with self._send_lock:
            seq = self._seq
            self._seq = (self._seq + 1) & 0xFFFF

        frame = pack_send_frame(
            seq=seq,
            target_system=self.system_id,
            lat=lat,
            lon=lon,
            alt=alt,
            spd=speed_value,
        )

        if self.transport == "serial":
            await asyncio.to_thread(self._write_serial, frame)
            self._set_last_target(seq, lat, lon, alt, speed_value)
            self._maybe_print_sent_frame(seq, lat, lon, alt, speed_value, frame)
            return

        if self.transport == "udp":
            if self._udp_tx_socket is None or self._target_addr is None:
                raise RuntimeError("UDP flight-controller transport is not started")
            self._udp_tx_socket.sendto(frame, self._target_addr)
            self._set_last_target(seq, lat, lon, alt, speed_value)
            self._maybe_print_sent_frame(seq, lat, lon, alt, speed_value, frame)
            return

        raise ValueError(f"unsupported transport: {self.transport}")

    def get_last_target(self) -> FlightTarget | None:
        """Return the latest target-point command sent to the flight controller."""
        with self._lock:
            return self._last_target

    @property
    def local_addr(self) -> tuple[str, int] | None:
        if self._udp_rx_socket is None:
            return None
        return self._udp_rx_socket.getsockname()

    @property
    def tx_local_addr(self) -> tuple[str, int] | None:
        if self._udp_tx_socket is None:
            return None
        return self._udp_tx_socket.getsockname()

    def describe(self) -> str:
        if self.transport == "serial":
            port = self.cfg.get("serial_port", "<provided>")
            return f"serial:{port} fc_id={self.system_id}"
        if self.transport == "udp":
            return (
                f"udp:rx={self.local_addr} tx={self.tx_local_addr} "
                f"target={self._target_addr} fc_id={self.system_id}"
            )
        return f"{self.transport} fc_id={self.system_id}"

    def _ensure_serial_open(self) -> None:
        if self._serial_port is not None:
            return

        port = self.cfg.get("serial_port")
        if not port:
            raise ValueError("serial transport requires serial_port")

        try:
            import serial  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on deployment env
            raise RuntimeError("serial transport requires pyserial") from exc

        self._serial_port = serial.Serial(
            port,
            baudrate=int(self.cfg.get("serial_baudrate", 115200)),
            timeout=float(self.cfg.get("serial_timeout", 0.1)),
        )

    def _ensure_udp_open(self) -> None:
        rx_bind_host = str(self.cfg.get("udp_rx_bind_host", self.cfg.get("udp_bind_host", "0.0.0.0")))
        rx_bind_port = int(self.cfg.get("udp_rx_bind_port", self.cfg.get("udp_bind_port", 0)))
        tx_bind_host = str(self.cfg.get("udp_tx_bind_host", "0.0.0.0"))
        tx_bind_port = int(self.cfg.get("udp_tx_bind_port", 0))
        target_host = str(self.cfg.get("udp_target_host", "127.0.0.1"))
        target_port = int(self.cfg.get("udp_target_port", rx_bind_port))

        if self._udp_rx_socket is None:
            self._udp_rx_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_rx_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp_rx_socket.bind((rx_bind_host, rx_bind_port))

        if self._udp_tx_socket is None:
            self._udp_tx_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_tx_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp_tx_socket.bind((tx_bind_host, tx_bind_port))

        self._udp_rx_socket.settimeout(float(self.cfg.get("udp_timeout", 0.1)))
        self._target_addr = (target_host, target_port)

    def _write_serial(self, frame: bytes) -> None:
        if self._serial_port is None:
            raise RuntimeError("serial flight-controller transport is not started")
        self._serial_port.write(frame)

    def _serial_read_loop(self) -> None:
        read_size = int(self.cfg.get("read_size", 128))
        while not self._stop.is_set():
            try:
                chunk = self._serial_port.read(read_size)
            except Exception as exc:  # pragma: no cover - depends on serial driver
                self._set_error(exc)
                break
            self._feed_bytes(chunk)

    def _udp_read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk, _addr = self._udp_rx_socket.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    self._set_error(exc)
                break
            self._feed_bytes(chunk)

    def _feed_bytes(self, chunk: bytes | bytearray | memoryview) -> None:
        if not chunk:
            return

        for frame in self._parser.feed(chunk):
            if not self.accept_any_system and frame.sending_system != self.system_id:
                continue
            self._update_state(frame)

    def _update_state(self, frame: Any) -> None:
        now = time.monotonic()
        with self._lock:
            prev = self._state
            heading = prev.heading if prev is not None else float(self.cfg.get("initial_heading", 0.0))
            heading_valid = prev.heading_valid if prev is not None else "initial_heading" in self.cfg

            if prev is not None and (frame.lat != prev.lat or frame.lon != prev.lon):
                heading = _bearing_deg(prev.lat, prev.lon, frame.lat, frame.lon)
                heading_valid = True

            self._state = FlightState(
                seq=frame.seq,
                system_id=frame.sending_system,
                phase=frame.phase,
                lat=frame.lat,
                lon=frame.lon,
                alt=frame.alt,
                speed=frame.spd,
                heading=heading % 360.0,
                heading_valid=heading_valid,
                received_at=now,
            )

    def _set_error(self, exc: Exception) -> None:
        with self._lock:
            self._last_error = exc

    def _set_last_target(self, seq: int, lat: float, lon: float, alt: float, speed: float) -> None:
        with self._lock:
            self._last_target = FlightTarget(
                seq=seq,
                lat=float(lat),
                lon=float(lon),
                alt=float(alt),
                speed=float(speed),
                sent_at=time.monotonic(),
            )

    def _maybe_print_sent_frame(
        self,
        seq: int,
        lat: float,
        lon: float,
        alt: float,
        speed: float,
        frame: bytes,
    ) -> None:
        if self._send_frame_print_interval <= 0:
            return

        now = time.monotonic()
        if now - self._last_send_frame_print_at < self._send_frame_print_interval:
            return
        self._last_send_frame_print_at = now

        if self.transport == "serial":
            target = self.cfg.get("serial_port", "<provided>")
        else:
            target = self._target_addr

        print(
            "[flight-controller send frame] "
            f"transport={self.transport} target={target} seq={seq} "
            f"target_system={self.system_id} lat={float(lat):.7f} lon={float(lon):.7f} "
            f"alt={float(alt):.2f} speed={float(speed):.2f} hex={frame.hex(' ')}"
        )


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lon = math.radians(lon2 - lon1)
    y = math.sin(delta_lon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
