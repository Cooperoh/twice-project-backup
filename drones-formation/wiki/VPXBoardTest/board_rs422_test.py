#!/usr/bin/env python3
"""Ubuntu/RK3588-side full-duplex RS-422 test using only the standard library."""

from __future__ import annotations

import argparse
import errno
import os
import select
import sys
import termios
import threading
import time
import zlib
from dataclasses import dataclass


FRAME_PREFIX = "RS422_TEST"


@dataclass
class Stats:
    tx: int = 0
    rx_bytes: int = 0
    rx_lines: int = 0
    rx_peer_ok: int = 0
    rx_self: int = 0
    rx_bad: int = 0


def make_frame(node: str, sequence: int) -> bytes:
    timestamp_ms = int(time.time() * 1000)
    body = f"{FRAME_PREFIX}|{node}|{sequence:06d}|{timestamp_ms}"
    checksum = zlib.crc32(body.encode("ascii")) & 0xFFFFFFFF
    return f"{body}|{checksum:08X}\n".encode("ascii")


def check_frame(line: bytes) -> tuple[bool, str, str]:
    try:
        text = line.rstrip(b"\r").decode("ascii")
        prefix, node, sequence, timestamp_ms, checksum_text = text.split("|")
        if prefix != FRAME_PREFIX:
            return False, "", "unexpected prefix"
        int(sequence)
        int(timestamp_ms)
        received_checksum = int(checksum_text, 16)
        body = "|".join((prefix, node, sequence, timestamp_ms))
        expected_checksum = zlib.crc32(body.encode("ascii")) & 0xFFFFFFFF
        if received_checksum != expected_checksum:
            return False, node, "CRC mismatch"
        return True, node, text
    except (UnicodeDecodeError, ValueError) as exc:
        return False, "", str(exc)


def configure_serial(fd: int, baudrate: int) -> list:
    speed = getattr(termios, f"B{baudrate}", None)
    if speed is None:
        raise ValueError(f"unsupported baud rate: {baudrate}")

    original = termios.tcgetattr(fd)
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] &= ~(
        termios.PARENB
        | termios.CSTOPB
        | termios.CSIZE
        | getattr(termios, "CRTSCTS", 0)
    )
    attrs[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
    attrs[3] = 0
    attrs[4] = speed
    attrs[5] = speed
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIFLUSH)
    return original


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
            view = view[written:]
        except BlockingIOError:
            select.select([], [fd], [], 1.0)


def reader_loop(fd: int, local_node: str, stop_event: threading.Event, stats: Stats) -> None:
    buffer = bytearray()
    while not stop_event.is_set():
        readable, _, _ = select.select([fd], [], [], 0.2)
        if not readable:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                continue
            raise
        if not chunk:
            continue
        stats.rx_bytes += len(chunk)
        buffer.extend(chunk)
        while b"\n" in buffer:
            raw_line, _, remainder = buffer.partition(b"\n")
            buffer[:] = remainder
            stats.rx_lines += 1
            valid, remote_node, detail = check_frame(bytes(raw_line))
            if not valid:
                stats.rx_bad += 1
                print(f"[RX-BAD] {raw_line!r} ({detail})", flush=True)
            elif remote_node == local_node:
                stats.rx_self += 1
                print(f"[RX-SELF] {detail}", flush=True)
            else:
                stats.rx_peer_ok += 1
                print(f"[RX-OK] {detail}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send and receive CRC-protected RS-422 test frames on Ubuntu."
    )
    parser.add_argument("--port", default="/dev/ttyS0", help="Linux serial device")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--node", default="BOARD", help="Node name placed in frames")
    parser.add_argument("--interval", type=float, default=1.0, help="TX interval in seconds")
    parser.add_argument("--duration", type=float, default=15.0, help="Test duration in seconds; 0 runs until Ctrl+C")
    parser.add_argument("--listen-only", action="store_true", help="Receive without transmitting")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.interval <= 0:
        raise SystemExit("--interval must be greater than zero")
    if "|" in args.node or not args.node:
        raise SystemExit("--node must be non-empty and cannot contain '|'")

    stats = Stats()
    stop_event = threading.Event()
    fd = -1
    original_attrs = None

    try:
        fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        original_attrs = configure_serial(fd, args.baudrate)
        print(
            f"[OPEN] port={args.port} baud={args.baudrate} mode=8N1 node={args.node} "
            f"role={'listen-only' if args.listen_only else 'full-duplex'}",
            flush=True,
        )

        reader = threading.Thread(
            target=reader_loop,
            args=(fd, args.node, stop_event, stats),
            daemon=True,
        )
        reader.start()

        started = time.monotonic()
        deadline = started + args.duration if args.duration > 0 else None
        next_send = started
        sequence = 1
        try:
            while deadline is None or time.monotonic() < deadline:
                now = time.monotonic()
                if not args.listen_only and now >= next_send:
                    frame = make_frame(args.node, sequence)
                    write_all(fd, frame)
                    termios.tcdrain(fd)
                    stats.tx += 1
                    print(f"[TX] {frame.decode('ascii').rstrip()}", flush=True)
                    sequence += 1
                    next_send += args.interval
                if args.listen_only:
                    stop_event.wait(0.05)
                else:
                    stop_event.wait(min(0.05, max(0.0, next_send - time.monotonic())))
        except KeyboardInterrupt:
            print("\n[STOP] Ctrl+C", flush=True)
        finally:
            stop_event.set()
            reader.join(timeout=1.0)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if fd >= 0:
            if original_attrs is not None:
                termios.tcsetattr(fd, termios.TCSANOW, original_attrs)
            os.close(fd)

    print(
        "[SUMMARY] "
        f"tx={stats.tx} rx_bytes={stats.rx_bytes} rx_lines={stats.rx_lines} "
        f"peer_ok={stats.rx_peer_ok} "
        f"self_echo={stats.rx_self} bad={stats.rx_bad}",
        flush=True,
    )
    if stats.rx_peer_ok:
        print("[RESULT] PASS - valid frames were received from the peer", flush=True)
        return 0
    print("[RESULT] FAIL - no valid frame was received from the peer", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
