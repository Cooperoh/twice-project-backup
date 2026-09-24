#!/usr/bin/env python3

import asyncio
import types
import unittest
from unittest.mock import patch

from behavior.telemetry import push_basic_telemetry

DRONE_ID = 1


class BasicTelemetryTest(unittest.TestCase):
    def test_target_created_during_state_wait_is_in_same_packet(self):
        for outcome in (_state(received_at=10.0, lat=38.0), TimeoutError(), RuntimeError("reader stopped")):
            with self.subTest(outcome=outcome):
                target = types.SimpleNamespace(lat=38.2, lon=117.3, alt=120.0, speed=16.0)

                class Drone(_SequenceDrone):
                    async def get_state(self, *, timeout=None):
                        await asyncio.sleep(0)
                        self.target = target
                        if isinstance(outcome, Exception):
                            raise outcome
                        return outcome

                drone = Drone([])
                bridge = _FakeBridge()

                async def run():
                    task = asyncio.create_task(push_basic_telemetry(drone, bridge, "DRONE1", DRONE_ID))
                    try:
                        await _wait_for_telemetry_count(bridge, 1)
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

                asyncio.run(run())
                self.assertEqual(len(bridge.telemetry), 1)
                self.assertEqual(bridge.telemetry[0]["goto_lat"], target.lat)
                self.assertEqual(bridge.telemetry[0]["goto_lon"], target.lon)
                self.assertEqual(bridge.telemetry[0]["goto_alt"], target.alt)
                self.assertEqual(bridge.telemetry[0]["goto_speed"], target.speed)
                self.assertEqual("lat" in bridge.telemetry[0], not isinstance(outcome, Exception))

    def test_changed_target_survives_unchanged_state_and_reader_error(self):
        state = _state(received_at=10.0, lat=38.0)

        class Drone(_SequenceDrone):
            async def get_state(self, *, timeout=None):
                self.calls += 1
                self.target = types.SimpleNamespace(lat=38.0 + self.calls / 10, lon=117.3, alt=120, speed=16)
                if self.calls >= 3:
                    raise RuntimeError("reader stopped")
                return state

        drone = Drone([])
        bridge = _FakeBridge()

        async def run():
            task = asyncio.create_task(push_basic_telemetry(drone, bridge, "DRONE1", DRONE_ID))
            try:
                await _wait_for_telemetry_count(bridge, 4)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        with patch("behavior.telemetry.CHECK_INT", 0.01):
            asyncio.run(run())
        self.assertEqual([msg["goto_lat"] for msg in bridge.telemetry], [38.1, 38.2, 38.3, 38.4])
        self.assertEqual(["lat" in msg for msg in bridge.telemetry], [True, False, False, False])
        self.assertEqual(len(bridge.logs), 1)

    def test_repeated_state_sends_empty_heartbeat_after_first_full_frame(self):
        state = _state(received_at=10.0, lat=38.0)
        drone = _SequenceDrone([state, state, state])
        bridge = _FakeBridge()

        async def run():
            task = asyncio.create_task(push_basic_telemetry(drone, bridge, "DRONE1", DRONE_ID))
            await drone.wait_for_calls(3)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        with patch("behavior.telemetry.CHECK_INT", 0.001):
            asyncio.run(run())

        self.assertEqual(
            bridge.telemetry,
            [
                _full_telemetry(lat=38.0),
                _empty_telemetry(),
                _empty_telemetry(),
            ],
        )

    def test_new_received_at_is_sent_again(self):
        first = _state(received_at=10.0, lat=38.0)
        second = _state(received_at=11.0, lat=38.1)
        drone = _SequenceDrone([first, first, second, second])
        bridge = _FakeBridge()

        async def run():
            task = asyncio.create_task(push_basic_telemetry(drone, bridge, "DRONE1", DRONE_ID))
            await drone.wait_for_calls(4)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        with patch("behavior.telemetry.CHECK_INT", 0.001):
            asyncio.run(run())

        self.assertEqual(
            bridge.telemetry,
            [
                _full_telemetry(lat=38.0),
                _empty_telemetry(),
                _full_telemetry(lat=38.1),
                _empty_telemetry(),
            ],
        )

    def test_first_state_timeout_sends_empty_heartbeat(self):
        drone = _TimeoutDrone()
        bridge = _FakeBridge()

        async def run():
            task = asyncio.create_task(push_basic_telemetry(drone, bridge, "DRONE1", DRONE_ID))
            await _wait_for_telemetry_count(bridge, 2)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        with patch("behavior.telemetry.CHECK_INT", 0.001):
            asyncio.run(run())

        self.assertEqual(bridge.telemetry, [_empty_telemetry(), _empty_telemetry()])
        self.assertGreaterEqual(len(drone.timeouts), 2)
        self.assertTrue(all(timeout == 0.001 for timeout in drone.timeouts))

    def test_last_target_is_included_in_full_frame_and_heartbeat(self):
        state = _state(received_at=10.0, lat=38.0)
        target = types.SimpleNamespace(lat=38.2, lon=117.3, alt=120.0, speed=16.0)
        drone = _SequenceDrone([state, state], target=target)
        bridge = _FakeBridge()

        async def run():
            task = asyncio.create_task(push_basic_telemetry(drone, bridge, "DRONE1", DRONE_ID))
            await drone.wait_for_calls(2)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        with patch("behavior.telemetry.CHECK_INT", 0.001):
            asyncio.run(run())

        target_fields = {
            "goto_lat": 38.2,
            "goto_lon": 117.3,
            "goto_alt": 120.0,
            "goto_speed": 16.0,
        }
        self.assertEqual(
            bridge.telemetry,
            [
                {**_full_telemetry(lat=38.0), **target_fields},
                {**_empty_telemetry(), **target_fields},
            ],
        )


def _state(*, received_at, lat):
    return types.SimpleNamespace(
        seq=1,
        system_id=DRONE_ID,
        phase=1,
        lat=lat,
        lon=117.0,
        alt=100.0,
        speed=15.0,
        heading=90.0,
        heading_valid=True,
        received_at=received_at,
    )


def _empty_telemetry():
    return {"id": DRONE_ID, "tag": "DRONE1"}


def _full_telemetry(*, lat):
    return {
        "id": DRONE_ID,
        "tag": "DRONE1",
        "lat": lat,
        "lon": 117.0,
        "alt": 100.0,
        "speed": 15.0,
        "heading": 90,
        "phase": 1,
    }


async def _wait_for_telemetry_count(bridge, count, timeout=0.2):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if len(bridge.telemetry) >= count:
            return
        await asyncio.sleep(0.001)
    raise AssertionError(f"expected at least {count} telemetry messages")


class _SequenceDrone:
    def __init__(self, states, target=None):
        self.states = list(states)
        self.target = target
        self.calls = 0
        self._calls_changed = None

    async def get_state(self, *, timeout=None):
        self.calls += 1
        if self._calls_changed is not None:
            self._calls_changed.set()
        if self.states:
            return self.states.pop(0)
        await asyncio.sleep(3600)

    async def wait_for_calls(self, count, timeout=0.2):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self.calls >= count:
                return
            self._calls_changed = asyncio.Event()
            await asyncio.wait_for(self._calls_changed.wait(), deadline - loop.time())
        raise AssertionError(f"expected at least {count} get_state calls")

    def get_last_target(self):
        return self.target


class _TimeoutDrone:
    def __init__(self):
        self.timeouts = []

    async def get_state(self, *, timeout=None):
        self.timeouts.append(timeout)
        await asyncio.sleep(float(timeout or 0))
        raise TimeoutError("timed out waiting for flight-controller telemetry")


class _FakeBridge:
    def __init__(self):
        self.telemetry = []
        self.logs = []

    def send_log(self, text):
        self.logs.append(text)

    def send_telemetry(self, **fields):
        self.telemetry.append(fields)


if __name__ == "__main__":
    unittest.main()
