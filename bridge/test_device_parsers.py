import unittest
from server import parse_adb_devices, parse_hdc_targets


class TestParseAdbDevices(unittest.TestCase):
    def test_empty_list(self):
        out = "List of devices attached\n\n"
        self.assertEqual(parse_adb_devices(out), [])

    def test_single_device(self):
        out = "List of devices attached\nXJ7N18A4G7\tdevice\n"
        self.assertEqual(parse_adb_devices(out), ["XJ7N18A4G7"])

    def test_skips_offline_and_unauthorized(self):
        out = (
            "List of devices attached\n"
            "XJ7N18A4G7\tdevice\n"
            "emulator-5554\toffline\n"
            "ABC123\tunauthorized\n"
        )
        self.assertEqual(parse_adb_devices(out), ["XJ7N18A4G7"])

    def test_multiple_devices(self):
        out = (
            "List of devices attached\n"
            "DEV1\tdevice\n"
            "DEV2\tdevice\n"
        )
        self.assertEqual(parse_adb_devices(out), ["DEV1", "DEV2"])


class TestParseHdcTargets(unittest.TestCase):
    def test_empty_marker(self):
        self.assertEqual(parse_hdc_targets("[Empty]\n"), [])

    def test_blank_input(self):
        self.assertEqual(parse_hdc_targets(""), [])

    def test_single_target(self):
        self.assertEqual(parse_hdc_targets("ABCDEF123\n"), ["ABCDEF123"])

    def test_multiple_targets(self):
        out = "ABCDEF123\nGHIJKL456\n"
        self.assertEqual(parse_hdc_targets(out), ["ABCDEF123", "GHIJKL456"])

    def test_strips_blank_lines(self):
        out = "\nABCDEF123\n\n"
        self.assertEqual(parse_hdc_targets(out), ["ABCDEF123"])


if __name__ == "__main__":
    unittest.main()
