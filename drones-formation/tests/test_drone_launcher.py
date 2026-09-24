#!/usr/bin/env python3

import unittest
from pathlib import Path

import drone_launcher


class DroneLauncherHelpersTest(unittest.TestCase):
    def test_valid_drone_ids_are_1_to_24(self):
        self.assertEqual(drone_launcher.DRONE_IDS, tuple(range(1, 25)))
        self.assertTrue(drone_launcher.is_valid_drone_id(1))
        self.assertTrue(drone_launcher.is_valid_drone_id(24))
        self.assertFalse(drone_launcher.is_valid_drone_id(0))
        self.assertFalse(drone_launcher.is_valid_drone_id(25))

    def test_build_run_command_uses_existing_entrypoint(self):
        command = drone_launcher.build_run_command(7, python_executable="python-test")

        self.assertEqual(command[0], "python-test")
        self.assertEqual(Path(command[1]).parts, ("drone-exec", "run.py"))
        self.assertEqual(command[2], "7")

    def test_build_run_command_rejects_invalid_id(self):
        with self.assertRaisesRegex(ValueError, "invalid drone id"):
            drone_launcher.build_run_command(0)

    def test_hidden_creationflags_returns_integer(self):
        self.assertIsInstance(drone_launcher.hidden_creationflags(), int)


if __name__ == "__main__":
    unittest.main()
