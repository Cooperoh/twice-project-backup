#!/usr/bin/env python3

import asyncio
import types
import unittest
from unittest.mock import patch

import runtime


class RuntimeStartupTest(unittest.TestCase):
    def test_get_cfg_injects_udp_or_serial_transport_from_runtime(self):
        for transport in ("udp", "serial"):
            with self.subTest(transport=transport):
                with patch.object(runtime, "FC_TRANSPORT", transport):
                    cfg, bind_ip, cmd_port, gui_host, gui_port = runtime.get_cfg(1)

                self.assertEqual(cfg["fc_transport"], transport)
                self.assertIn("serial_port", cfg)
                self.assertIn("udp_bind_port", cfg)
                self.assertEqual(bind_ip, "0.0.0.0")
                self.assertEqual(cmd_port, 57001)
                self.assertEqual(gui_host, cfg["gui_host"])
                self.assertEqual(gui_port, runtime.GUI_PORT)

    def test_simulation_bridge_factory_keeps_direct_fgc_bridge(self):
        fake_bridge_cls = _BridgeFactory()
        peers = {2: ("127.0.0.1", 57002)}

        with patch.object(runtime, "RUN_MODE", "simulation"):
            with patch.object(runtime, "FGCBridge", fake_bridge_cls):
                bridge = runtime._create_bridge(
                    bind_ip="0.0.0.0",
                    bind_port=57001,
                    gui_host="127.0.0.1",
                    gui_port=56999,
                    peers=peers,
                    name="DRONE1",
                )

        self.assertIs(bridge, fake_bridge_cls.instances[0])
        self.assertEqual(
            bridge.kwargs,
            {
                "bind_ip": "0.0.0.0",
                "bind_port": 57001,
                "gui_host": "127.0.0.1",
                "gui_port": 56999,
                "peers": peers,
                "name": "DRONE1",
            },
        )

    def test_wait_for_initial_telemetry_prints_locally_until_state_arrives(self):
        state = _state()
        drone = _SequenceDrone([TimeoutError(), state])

        async def run():
            with patch.object(runtime, "INITIAL_TELEMETRY_WAIT_SEC", 0.01):
                with patch("builtins.print") as mock_print:
                    result = await runtime._wait_for_initial_telemetry(drone, "DRONE_TEST")
            self.assertIs(result, state)
            self.assertEqual(drone.timeouts, [0.01, 0.01])
            printed = [" ".join(str(arg) for arg in call.args) for call in mock_print.call_args_list]
            self.assertTrue(
                any("waiting for flight-controller telemetry" in line for line in printed)
            )
            self.assertTrue(any("initial telemetry received" in line for line in printed))

        asyncio.run(run())

    def test_wait_for_initial_telemetry_can_route_waiting_messages_locally(self):
        state = _state()
        drone = _SequenceDrone([TimeoutError(), state])
        waiting_messages = []

        async def run():
            with patch.object(runtime, "INITIAL_TELEMETRY_WAIT_SEC", 0.01):
                with patch("builtins.print") as mock_print:
                    result = await runtime._wait_for_initial_telemetry(
                        drone,
                        "DRONE_TEST",
                        waiting_print=waiting_messages.append,
                    )
            self.assertIs(result, state)
            self.assertEqual(
                waiting_messages,
                ["[DRONE_TEST] waiting for flight-controller telemetry..."],
            )
            printed = [" ".join(str(arg) for arg in call.args) for call in mock_print.call_args_list]
            self.assertFalse(
                any("waiting for flight-controller telemetry" in line for line in printed)
            )
            self.assertTrue(any("initial telemetry received" in line for line in printed))

        asyncio.run(run())

    def test_wait_for_initial_telemetry_propagates_reader_errors(self):
        drone = _SequenceDrone([RuntimeError("reader stopped")])

        async def run():
            with self.assertRaisesRegex(RuntimeError, "reader stopped"):
                await runtime._wait_for_initial_telemetry(drone, "DRONE_TEST")

        asyncio.run(run())

    def test_run_drone_starts_bridge_and_listener_before_initial_telemetry(self):
        async def run():
            telemetry_ready = asyncio.Event()
            listener_started = asyncio.Event()
            listener_release = asyncio.Event()
            telemetry_forwarding_cancelled = asyncio.Event()
            fake_drone = _BlockingDrone(telemetry_ready)
            fake_bridge_cls = _BridgeFactory()

            async def fake_connect_uav(cfg):
                fake_drone.cfg = cfg
                return fake_drone

            async def fake_cmd_listener(bridge, tasks, drone, form_ref, cfg):
                listener_started.set()
                await listener_release.wait()
                raise _ListenerStopped()

            async def fake_push_basic_telemetry(*_args, **_kwargs):
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    telemetry_forwarding_cancelled.set()
                    raise

            with patch.object(runtime, "get_cfg") as mock_get_cfg:
                mock_get_cfg.return_value = (
                    {
                        "id": 7,
                        "tag": "DRONE7",
                        "is_leader": 0,
                        "formation_types": 2,
                        "formation_spacing": 150,
                    },
                    "0.0.0.0",
                    57007,
                    "127.0.0.1",
                    56999,
                )
                with patch.object(runtime, "connect_uav", fake_connect_uav):
                    with patch.object(runtime, "FGCBridge", fake_bridge_cls):
                        with patch.object(runtime, "drone_broadcast", return_value=[]):
                            with patch.object(runtime, "cmd_listener", fake_cmd_listener):
                                with patch.object(
                                    runtime,
                                    "push_basic_telemetry",
                                    fake_push_basic_telemetry,
                                ):
                                    with patch("builtins.print") as mock_print:
                                        task = asyncio.create_task(runtime.run_drone(7))
                                        await asyncio.wait_for(listener_started.wait(), 0.2)

                                        self.assertEqual(len(fake_bridge_cls.instances), 1)
                                        bridge = fake_bridge_cls.instances[0]
                                        self.assertTrue(bridge.started)
                                        self.assertTrue(bridge.print_patched)
                                        self.assertEqual(
                                            bridge.telemetry,
                                            [],  # The mocked telemetry producer sends nothing.
                                        )
                                        self.assertFalse(fake_drone.stopped)

                                        telemetry_ready.set()
                                        await _wait_for_print(
                                            mock_print,
                                            "initial telemetry received",
                                        )
                                        listener_release.set()
                                        with self.assertRaises(_ListenerStopped):
                                            await task

            self.assertEqual(len(fake_bridge_cls.instances), 1)
            bridge = fake_bridge_cls.instances[0]
            self.assertTrue(bridge.started)
            self.assertTrue(bridge.print_patched)
            self.assertTrue(bridge.closed)
            self.assertEqual(bridge.logs, [])
            self.assertTrue(telemetry_forwarding_cancelled.is_set())
            self.assertTrue(fake_drone.stopped)
            self.assertTrue(listener_started.is_set())

        asyncio.run(run())


class _ListenerStopped(Exception):
    pass


def _state():
    return types.SimpleNamespace(seq=1, lat=38.0, lon=117.0, alt=100.0)


async def _wait_for_print(mock_print, needle, timeout=0.2):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        printed = [" ".join(str(arg) for arg in call.args) for call in mock_print.call_args_list]
        if any(needle in line for line in printed):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"did not print {needle!r}")


class _SequenceDrone:
    def __init__(self, results):
        self.results = list(results)
        self.timeouts = []

    async def get_state(self, *, timeout=None):
        self.timeouts.append(timeout)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _BlockingDrone:
    def __init__(self, telemetry_ready):
        self.telemetry_ready = telemetry_ready
        self.cfg = None
        self.stopped = False

    async def get_state(self, *, timeout=None):
        await self.telemetry_ready.wait()
        return _state()

    async def stop(self):
        self.stopped = True


class _BridgeFactory:
    def __init__(self):
        self.instances = []

    def __call__(self, **kwargs):
        bridge = _FakeBridge(kwargs)
        self.instances.append(bridge)
        return bridge


class _FakeBridge:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.started = False
        self.print_patched = False
        self.closed = False
        self.logs = []
        self.telemetry = []

    async def start(self):
        self.started = True

    def patch_print(self):
        self.print_patched = True

    def send_log(self, text):
        self.logs.append(text)

    def send_telemetry(self, **fields):
        self.telemetry.append({"type": "telemetry", **fields})

    def close(self):
        self.closed = True


if __name__ == "__main__":
    unittest.main()
