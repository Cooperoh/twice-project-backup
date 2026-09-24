#!/usr/bin/env python3

import unittest

from config import UAV_BASE_CFGS, UAV_CFGS


class UAVConfigTest(unittest.TestCase):
    def test_uav_configs_cover_1_to_24_without_zero(self):
        ids = [cfg["id"] for cfg in UAV_CFGS]

        self.assertEqual(len(UAV_CFGS), 24)
        self.assertEqual(ids, list(range(1, 25)))
        self.assertNotIn(0, ids)

    def test_flight_controller_transport_is_selected_by_runtime(self):
        self.assertTrue(all("fc_transport" not in cfg for cfg in UAV_BASE_CFGS))
        self.assertTrue(all("fc_transport" not in cfg for cfg in UAV_CFGS))

    def test_command_and_flight_control_udp_ports_follow_id_rules(self):
        configs = {cfg["id"]: cfg for cfg in UAV_CFGS}

        expected = {
            1: (57001, 6012, 6013),
            12: (57012, 6122, 6123),
            24: (57024, 6242, 6243),
        }
        for uav_id, (cmd_port, udp_bind_port, udp_target_port) in expected.items():
            with self.subTest(uav_id=uav_id):
                cfg = configs[uav_id]
                self.assertEqual(cfg["tag"], f"DRONE{uav_id}")
                self.assertEqual(cfg["fc_id"], uav_id)
                self.assertEqual(cfg["cmd_port"], cmd_port)
                self.assertEqual(cfg["udp_bind_port"], udp_bind_port)
                self.assertEqual(cfg["udp_target_port"], udp_target_port)


if __name__ == "__main__":
    unittest.main()
