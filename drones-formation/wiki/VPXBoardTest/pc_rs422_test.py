#!/usr/bin/env python3
"""Windows-side full-duplex RS-422 link test using pyserial."""

from __future__ import annotations

import argparse
import sys
import threading
import time
import zlib
from dataclasses import dataclass

import serial


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


def reader_loop(
    port: serial.Serial,
    local_node: str,
    stop_event: threading.Event,
    stats: Stats,
) -> None:
    buffer = bytearray()
    while not stop_event.is_set():
        chunk = port.read(port.in_waiting or 1)
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
        description="Send and receive CRC-protected RS-422 test frames on Windows."
    )
    parser.add_argument("--port", default="COM5", help="Windows COM port")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--node", default="PC", help="Node name placed in frames")
    parser.add_argument("--interval", type=float, default=1.0, help="TX interval in seconds")
    parser.add_argument("--duration", type=float, default=15.0, help="Test duration in seconds; 0 runs until Ctrl+C")
    parser.add_argument("--listen-only", action="store_true", help="Receive without transmitting")
    parser.add_argument("--loopback", action="store_true", help="Pass when transmitted frames return as self-echo")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.interval <= 0:
        raise SystemExit("--interval must be greater than zero")
    if "|" in args.node or not args.node:
        raise SystemExit("--node must be non-empty and cannot contain '|'")

    stats = Stats()
    stop_event = threading.Event()

    try:
        with serial.serial_for_url(
            args.port,
            baudrate=args.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.2,
            write_timeout=1.0,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        ) as port:
            port.dtr = False
            port.rts = False
            port.reset_input_buffer()
            print(
                f"[OPEN] port={args.port} baud={args.baudrate} mode=8N1 node={args.node} "
                f"role={'listen-only' if args.listen_only else 'full-duplex'}",
                flush=True,
            )

            reader = threading.Thread(
                target=reader_loop,
                args=(port, args.node, stop_event, stats),
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
                        port.write(frame)
                        port.flush()
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
    except serial.SerialException as exc:
        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        return 1

    print(
        "[SUMMARY] "
        f"tx={stats.tx} rx_bytes={stats.rx_bytes} rx_lines={stats.rx_lines} "
        f"peer_ok={stats.rx_peer_ok} "
        f"self_echo={stats.rx_self} bad={stats.rx_bad}",
        flush=True,
    )
    if args.loopback and stats.rx_self:
        print("[RESULT] PASS - hardware loopback returned transmitted frames", flush=True)
        return 0
    if not args.loopback and stats.rx_peer_ok:
        print("[RESULT] PASS - valid frames were received from the peer", flush=True)
        return 0
    if args.loopback:
        print("[RESULT] FAIL - no transmitted frame returned through the hardware loopback", flush=True)
        return 2
    print("[RESULT] FAIL - no valid frame was received from the peer", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
