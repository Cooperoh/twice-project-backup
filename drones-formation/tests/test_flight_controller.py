#!/usr/bin/env python3

import asyncio
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from client.autopilot import FlightController, build_frame, parse_sent_frame
from behavior.telemetry import push_basic_telemetry
from bridge import FGCBridge


class FlightControllerTest(unittest.TestCase):
    def test_udp_target_reaches_gui_via_unified_telemetry(self):
        async def run():
            command_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            gui_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            telemetry_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for receiver in (command_rx, gui_rx):
                receiver.bind(("127.0.0.1", 0))
                receiver.setblocking(False)
            fc = FlightController({
                "id": 4, "fc_transport": "udp", "udp_bind_host": "127.0.0.1",
                "udp_bind_port": 0, "udp_target_host": "127.0.0.1",
                "udp_target_port": command_rx.getsockname()[1], "send_frame_print_interval": 0,
            })
            bridge = FGCBridge(bind_ip="127.0.0.1", gui_host="127.0.0.1", gui_port=gui_rx.getsockname()[1])
            task = None
            loop = asyncio.get_running_loop()

            async def receive_gui():
                return json.loads(await asyncio.wait_for(loop.sock_recv(gui_rx, 4096), 1.0))

            async def receive_target(lat):
                for _ in range(10):
                    message = await receive_gui()
                    if message.get("goto_lat") == lat:
                        return message
                self.fail("latest goto did not reach GUI UDP receiver")

            try:
                await fc.start()
                task = asyncio.create_task(push_basic_telemetry(fc, bridge, "DRONE4", 4))
                self.assertEqual(await receive_gui(), {"type": "telemetry", "id": 4, "tag": "DRONE4"})

                # Target arrives while no flight-controller state exists.
                await fc.goto_location(40.01, 109.02, 1300.0, 120.0)
                sent = parse_sent_frame(await asyncio.wait_for(loop.sock_recv(command_rx, 4096), 1.0))
                message = await receive_target(40.01)
                self.assertNotIn("lat", message)
                self.assertAlmostEqual(message["goto_lat"], sent.lat)
                self.assertAlmostEqual(message["goto_lon"], sent.lon)
                self.assertAlmostEqual(message["goto_alt"], sent.alt)
                self.assertAlmostEqual(message["goto_speed"], sent.spd)

                telemetry_tx.sendto(_receive_frame(sending_system=4), fc.local_addr)
                await fc.get_state(timeout=1.0)
                for _ in range(10):
                    message = await receive_gui()
                    if "lat" in message:
                        break
                self.assertIn("lat", message)
                self.assertEqual(message["goto_lat"], 40.01)

                # A second target must propagate even though the FC state never changes.
                await fc.goto_location(40.02, 109.03, 1301.0, 121.0)
                message = await receive_target(40.02)
                self.assertNotIn("lat", message)
                self.assertEqual(message["goto_lon"], 109.03)
                self.assertEqual(message["goto_speed"], 121.0)
            finally:
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await fc.stop()
                bridge.close()
                for sock in (command_rx, gui_rx, telemetry_tx):
                    sock.close()

        with patch("behavior.telemetry.CHECK_INT", 0.01):
            asyncio.run(run())

    def test_sent_frame_debug_print_is_rate_limited(self):
        fake_serial = _FakeSerial([])

        async def run():
            fc = FlightController(
                {
                    "id": 3,
                    "fc_transport": "serial",
                    "send_frame_print_interval": 10.0,
                },
                serial_port=fake_serial,
            )
            with patch("builtins.print") as mock_print:
                await fc.goto_location(40.0, 109.0, 1200.0, 110.0)
                await fc.goto_location(40.1, 109.1, 1201.0, 111.0)
                fc._last_send_frame_print_at -= 10.1
                await fc.goto_location(40.2, 109.2, 1202.0, 112.0)

            printed = [" ".join(str(arg) for arg in call.args) for call in mock_print.call_args_list]
            self.assertEqual(len(printed), 2)
            self.assertIn("seq=0", printed[0])
            self.assertIn("target_system=3", printed[0])
            self.assertIn("hex=eb 90 01", printed[0])
            self.assertIn("seq=2", printed[1])

        asyncio.run(run())

    def test_serial_reads_latest_state_and_writes_target_frame(self):
        fake_serial = _FakeSerial(
            [
                _receive_frame(seq=1, sending_system=3, lat=40.0, lon=109.0, alt=1200.0, spd=110.0),
                _receive_frame(seq=2, sending_system=3, lat=40.001, lon=109.0, alt=1201.0, spd=111.0),
            ]
        )

        async def run():
            fc = FlightController(
                {
                    "id": 3,
                    "fc_transport": "serial",
                    "serial_port": "COM_TEST",
                    "send_frame_print_interval": 0,
                },
                serial_port=fake_serial,
            )
            try:
                await fc.start()
                state = await fc.get_state(require_heading=True, timeout=1.0)
                self.assertEqual(state.seq, 2)
                self.assertEqual(state.system_id, 3)
                self.assertAlmostEqual(state.lat, 40.001, places=7)
                self.assertAlmostEqual(state.alt, 1201.0, places=2)
                self.assertTrue(state.heading_valid)

                await fc.goto_location(40.002, 109.003, 1210.0, 115.0)
                target = fc.get_last_target()
                self.assertIsNotNone(target)
                self.assertAlmostEqual(target.lat, 40.002, places=7)
                self.assertAlmostEqual(target.lon, 109.003, places=7)
                self.assertAlmostEqual(target.alt, 1210.0, places=2)
                self.assertAlmostEqual(target.speed, 115.0, places=2)
            finally:
                await fc.stop()

        asyncio.run(run())

        self.assertEqual(len(fake_serial.writes), 1)
        sent = parse_sent_frame(fake_serial.writes[0])
        self.assertEqual(sent.target_system, 3)
        self.assertAlmostEqual(sent.lat, 40.002, places=7)
        self.assertAlmostEqual(sent.lon, 109.003, places=7)
        self.assertAlmostEqual(sent.alt, 1210.0, places=2)
        self.assertAlmostEqual(sent.spd, 115.0, places=2)

    def test_udp_receives_state_estimates_heading_and_sends_target_frame(self):
        command_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        command_rx.bind(("127.0.0.1", 0))
        command_rx.settimeout(1.0)
        target_host, target_port = command_rx.getsockname()
        addrs = {}

        async def run():
            fc = FlightController(
                {
                    "id": 4,
                    "fc_transport": "udp",
                    "udp_bind_host": "127.0.0.1",
                    "udp_bind_port": 0,
                    "udp_target_host": target_host,
                    "udp_target_port": target_port,
                    "send_frame_print_interval": 0,
                }
            )
            telemetry_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                await fc.start()
                self.assertIsNotNone(fc.local_addr)
                self.assertIsNotNone(fc.tx_local_addr)
                self.assertNotEqual(fc.local_addr[1], fc.tx_local_addr[1])
                addrs["rx"] = fc.local_addr
                addrs["tx"] = fc.tx_local_addr
                description = fc.describe()
                self.assertIn(f"rx={fc.local_addr}", description)
                self.assertIn(f"tx={fc.tx_local_addr}", description)
                self.assertIn(f"target={target_host, target_port}", description)
                telemetry_tx.sendto(
                    _receive_frame(seq=1, sending_system=4, lat=40.0, lon=109.0),
                    fc.local_addr,
                )
                telemetry_tx.sendto(
                    _receive_frame(seq=2, sending_system=4, lat=40.0, lon=109.001),
                    fc.local_addr,
                )

                state = await fc.get_state(require_heading=True, timeout=1.0)
                self.assertEqual(state.seq, 2)
                self.assertAlmostEqual(state.heading, 90.0, delta=1.0)

                await fc.goto_location(40.01, 109.02, 1300.0, 120.0)
                target = fc.get_last_target()
                self.assertIsNotNone(target)
                self.assertAlmostEqual(target.lat, 40.01, places=7)
                self.assertAlmostEqual(target.lon, 109.02, places=7)
                self.assertAlmostEqual(target.alt, 1300.0, places=2)
                self.assertAlmostEqual(target.speed, 120.0, places=2)
            finally:
                telemetry_tx.close()
                await fc.stop()

        try:
            asyncio.run(run())
            data, addr = command_rx.recvfrom(4096)
        finally:
            command_rx.close()

        self.assertEqual(addr[1], addrs["tx"][1])
        self.assertNotEqual(addr[1], addrs["rx"][1])
        sent = parse_sent_frame(data)
        self.assertEqual(sent.target_system, 4)
        self.assertAlmostEqual(sent.lat, 40.01, places=7)
        self.assertAlmostEqual(sent.lon, 109.02, places=7)
        self.assertAlmostEqual(sent.alt, 1300.0, places=2)
        self.assertAlmostEqual(sent.spd, 120.0, places=2)


def _receive_frame(
    *,
    seq=1,
    sending_system=1,
    phase=1,
    lat=40.8663949,
    lon=109.5596,
    alt=1380.0,
    spd=125.0,
):
    payload = bytearray()
    payload += int(seq).to_bytes(2, byteorder="little", signed=False)
    payload += int(sending_system).to_bytes(1, byteorder="little", signed=False)
    payload += int(phase).to_bytes(1, byteorder="little", signed=False)
    payload += round(lat * 3600 * 3000).to_bytes(4, byteorder="little", signed=True)
    payload += round(lon * 3600 * 3000).to_bytes(4, byteorder="little", signed=True)
    payload += round((alt + 500.0) * 100).to_bytes(4, byteorder="little", signed=False)
    payload += round(spd * 100).to_bytes(2, byteorder="little", signed=False)
    return build_frame(2, payload)


class _FakeSerial:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._lock = threading.Lock()
        self.writes = []
        self.closed = False

    def read(self, _size):
        with self._lock:
            if self._chunks:
                return self._chunks.pop(0)
        time.sleep(0.005)
        return b""

    def write(self, data):
        with self._lock:
            self.writes.append(bytes(data))
        return len(data)

    def close(self):
        self.closed = True


if __name__ == "__main__":
    unittest.main()
