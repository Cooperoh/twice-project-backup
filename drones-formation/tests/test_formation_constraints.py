#!/usr/bin/env python3

import unittest

from formation_constraints import (
    calculate_formation_turn,
    calculate_formation_turn_table,
    format_formation_turn_chinese,
)


class FormationConstraintsTest(unittest.TestCase):
    def test_matches_document_example_for_fourth_row_outer_aircraft(self):
        result = calculate_formation_turn(
            {
                "cruise_speed": 120,
                "min_speed": 90,
                "max_speed": 160,
                "bank_angle_deg": 30,
                "tolerance_distance": 2000,
                "turn_time": 120,
                "n": 3,
                "d": 600,
            }
        )

        self.assertAlmostEqual(result["default_turn_radius_m"], 2542.46, delta=0.01)
        self.assertAlmostEqual(result["default_turn_rate_deg_s"], 2.704, delta=0.001)
        self.assertAlmostEqual(result["actual_turn_radius_m"], 2606.57, delta=0.01)
        self.assertAlmostEqual(result["actual_turn_rate_deg_s"], 2.638, delta=0.001)
        self.assertAlmostEqual(
            result["max_turn_time_at_default_turn_s"], 108.93, delta=0.01
        )
        self.assertAlmostEqual(
            result["max_heading_change_at_default_turn_deg"], 294.57, delta=0.01
        )
        self.assertAlmostEqual(result["max_spacing_at_default_turn_m"], 585.24, delta=0.01)
        self.assertEqual(result["limiting_side"], "outer")
        self.assertTrue(result["feasible"])
        self.assertNotIn("中文结果", result)

        chinese = format_formation_turn_chinese(result)
        self.assertIn("1. 主机默认值", chinese)
        self.assertIn("2. 当前参数下实际需要值", chinese)
        self.assertIn("3. 如果仍按主机默认转弯半径飞", chinese)
        self.assertIn("最多可转向：294.57 deg", chinese)
        self.assertIn("主导约束：外侧僚机最大速度约束", chinese)

    def test_defaults_tolerance_distance_to_twenty_seconds_of_cruise_speed(self):
        implicit = calculate_formation_turn(
            {"cruise_speed": 100, "turn_time": 20, "n": 1, "spacing": 100}
        )
        explicit = calculate_formation_turn(
            {
                "cruise_speed": 100,
                "turn_time": 20,
                "tolerance_distance": 2000,
                "n": 1,
                "spacing": 100,
            }
        )

        self.assertEqual(
            implicit["max_spacing_at_default_turn_m"],
            explicit["max_spacing_at_default_turn_m"],
        )
        self.assertEqual(implicit["actual_turn_radius_m"], explicit["actual_turn_radius_m"])

    def test_heading_change_overrides_turn_time(self):
        result = calculate_formation_turn(
            {
                "cruise_speed": 120,
                "turn_time": 999,
                "heading_change_deg": 27.042682320438898,
                "n": 1,
                "spacing": 100,
            }
        )

        self.assertAlmostEqual(result["effective_turn_time_s"], 10.0, delta=0.001)
        self.assertAlmostEqual(result["default_heading_change_deg"], 27.0427, delta=0.001)

    def test_batch_table_returns_one_result_per_row(self):
        result = calculate_formation_turn_table(
            [
                {"n": 1, "spacing": 100},
                {"n": 2, "d": 200},
            ]
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["n"], 1)
        self.assertEqual(result[1]["spacing_m"], 200.0)

    def test_negative_max_spacing_result_is_not_clipped(self):
        result = calculate_formation_turn(
            {
                "cruise_speed": 120,
                "min_speed": 90,
                "max_speed": 100,
                "tolerance_distance": 80,
                "turn_time": 10,
                "n": 1,
                "spacing": 100,
            }
        )

        self.assertLess(result["max_spacing_at_default_turn_m"], 0.0)
        self.assertFalse(result["feasible"])
        self.assertEqual(result["limiting_side"], "outer")

    def test_invalid_required_values_raise_value_error(self):
        invalid_rows = [
            {"n": 0, "spacing": 100},
            {"n": 1, "spacing": 0},
            {"n": 1, "spacing": 100, "cruise_speed": 0},
            {"n": 1, "spacing": 100, "turn_time": -1},
            {"n": 1, "spacing": 100, "bank_angle_deg": 0},
        ]

        for row in invalid_rows:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    calculate_formation_turn(row)


if __name__ == "__main__":
    unittest.main()
