#!/usr/bin/env python3

import asyncio
import json
import socket
import unittest

from bridge import FGCBridge


class FGCBridgeTest(unittest.TestCase):
    def test_udp_member_routing_changes_with_each_message(self):
        receivers = {}
        bridge = None
        try:
            for drone_id in (2, 3, 4):
                receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                receiver.bind(("127.0.0.1", 0))
                receiver.settimeout(0.03)
                receivers[drone_id] = receiver
            bridge = FGCBridge(
                bind_ip="127.0.0.1",
                peers={drone_id: sock.getsockname() for drone_id, sock in receivers.items()},
            )
            for members in ([1, 2, 2], [1, 3, 4], [], None, [1, 99]):
                payload = {"type": "lead_broadcast", "leader_id": 1, "targets": members}
                bridge.send_to_peers(payload)
                for drone_id, receiver in receivers.items():
                    if drone_id in (members or []):
                        received, _ = receiver.recvfrom(4096)
                        self.assertEqual(json.loads(received), payload)
                    # Nonmembers get nothing; members get exactly one copy.
                    with self.assertRaises(socket.timeout):
                        receiver.recvfrom(4096)
        finally:
            if bridge is not None:
                bridge.close()
            for receiver in receivers.values():
                receiver.close()

    def test_gui_send_does_not_stop_command_receiver(self):
        gui_port = _reserve_unused_udp_port()
        bridge = FGCBridge(
            bind_ip="127.0.0.1",
            bind_port=0,
            gui_host="127.0.0.1",
            gui_port=gui_port,
            peers=[],
            name="TEST",
        )
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            asyncio.run(self._exercise_command_after_gui_send(bridge, sender))
        finally:
            sender.close()
            bridge.close()

    async def _exercise_command_after_gui_send(self, bridge, sender):
        await bridge.start()
        rx_addr = bridge.sock.getsockname()
        tx_addr = bridge.tx_sock.getsockname()
        self.assertNotEqual(rx_addr[1], tx_addr[1])

        bridge.send_gui({"type": "log", "text": "gui not listening"})
        await asyncio.sleep(0.05)

        payload = {"cmd": "formation_start", "targets": [1], "form_type": 1, "spacing": 100}
        sender.sendto(json.dumps(payload).encode("utf-8"), rx_addr)
        received = await asyncio.wait_for(bridge.next_cmd(), timeout=1.0)
        self.assertEqual(received["cmd"], "formation_start")
        self.assertEqual(received["targets"], [1])


def _reserve_unused_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


if __name__ == "__main__":
    unittest.main()
