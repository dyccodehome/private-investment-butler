from __future__ import annotations

import unittest

from src.longbridge_capabilities import (
    assert_longbridge_command_allowed,
    assert_read_capability,
    list_denied_capabilities,
    list_read_capabilities,
)


class LongbridgeCapabilitiesTest(unittest.TestCase):
    def test_allows_registered_readonly_commands(self) -> None:
        capability = assert_longbridge_command_allowed(["longbridge", "positions", "--format", "json"])
        self.assertEqual(capability.capability_id, "positions")

        capability = assert_longbridge_command_allowed(["longbridge", "quote", "NVDA.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "quote")

    def test_denies_trading_write_commands(self) -> None:
        with self.assertRaises(PermissionError):
            assert_longbridge_command_allowed(["longbridge", "submit-order", "NVDA.US"])

        with self.assertRaises(PermissionError):
            assert_longbridge_command_allowed(["longbridge", "cancel-order", "123"])

    def test_denies_unknown_commands_until_provider_is_fixed(self) -> None:
        with self.assertRaises(PermissionError):
            assert_longbridge_command_allowed(["longbridge", "unknown-read", "--format", "json"])

    def test_read_capability_requires_implemented_provider_by_default(self) -> None:
        self.assertEqual(assert_read_capability("positions").capability_id, "positions")
        with self.assertRaises(PermissionError):
            assert_read_capability("fundamentals")
        self.assertEqual(assert_read_capability("fundamentals", require_implemented=False).capability_id, "fundamentals")

    def test_lists_read_and_denied_capabilities(self) -> None:
        implemented = list_read_capabilities(include_planned=False)
        all_read = list_read_capabilities(include_planned=True)
        denied = list_denied_capabilities()

        self.assertLess(len(implemented), len(all_read))
        self.assertTrue(any(item["capability_id"] == "positions" for item in implemented))
        self.assertTrue(any(item["capability_id"] == "submit_order" for item in denied))


if __name__ == "__main__":
    unittest.main()
