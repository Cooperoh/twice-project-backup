#!/usr/bin/env python3

import asyncio
import types
import unittest
from unittest.mock import patch

from behavior.leader import leader_patrol_task


class LeaderPatrolTest(unittest.TestCase):
    def test_resends_current_target_before_reaching_threshold(self):
        lead = _FakeLead()
        bridge = _FakeBridge()
        form_ref = {"leader_id": 1, "type": 1, "spacing": 1000, "group": 1, "targets": [1, 2]}

        async def run():
            with patch("behavior.leader.CHECK_INT", 0.001):
                task = asyncio.create_task(leader_patrol_task(lead, bridge, form_ref))
                await lead.wait_for_goto_count(2)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        asyncio.run(run())

        self.assertGreaterEqual(len(lead.targets), 2)
        self.assertEqual(lead.targets[0], lead.targets[1])
        self.assertEqual(bridge.telemetry, [])
        self.assertEqual(bridge.peer_messages[0]["targets"], [1, 2])


class _FakeLead:
    def __init__(self):
        self.targets = []
        self._goto_event = None

    async def get_state(self, *, require_heading=False):
        return types.SimpleNamespace(
            lat=38.0,
            lon=117.0,
            alt=100.0,
            heading=0.0,
            speed=170.0,
        )

    async def goto_location(self, lat, lon, alt, speed):
        self.targets.append((lat, lon, alt, speed))
        if self._goto_event is not None:
            self._goto_event.set()

    async def wait_for_goto_count(self, count, timeout=0.2):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if len(self.targets) >= count:
                return
            self._goto_event = asyncio.Event()
            await asyncio.wait_for(self._goto_event.wait(), deadline - loop.time())
        raise AssertionError(f"expected at least {count} goto_location calls")


class _FakeBridge:
    def __init__(self):
        self.telemetry = []
        self.peer_messages = []

    def send_telemetry(self, **fields):
        self.telemetry.append(fields)

    def send_to_peers(self, payload):
        self.peer_messages.append(payload)


if __name__ == "__main__":
    unittest.main()
