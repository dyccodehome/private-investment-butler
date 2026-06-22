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

        capability = assert_longbridge_command_allowed(["longbridge", "order", "--history", "--format", "json"])
        self.assertEqual(capability.capability_id, "order_history")

        capability = assert_longbridge_command_allowed(["longbridge", "order", "executions", "--history", "--format", "json"])
        self.assertEqual(capability.capability_id, "execution_history")

        capability = assert_longbridge_command_allowed(["longbridge", "kline", "NVDA.US", "--period", "day", "--format", "json"])
        self.assertEqual(capability.capability_id, "candles")

        capability = assert_longbridge_command_allowed(["longbridge", "market-status", "--format", "json"])
        self.assertEqual(capability.capability_id, "market_state")

        capability = assert_longbridge_command_allowed(["longbridge", "trading", "days", "US", "--format", "json"])
        self.assertEqual(capability.capability_id, "trading_calendar")

        capability = assert_longbridge_command_allowed(["longbridge", "market-temp", "US", "--format", "json"])
        self.assertEqual(capability.capability_id, "market_temperature")

        capability = assert_longbridge_command_allowed(["longbridge", "company", "NVDA.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "company_profile")

        capability = assert_longbridge_command_allowed(["longbridge", "valuation", "NVDA.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "valuation")

        capability = assert_longbridge_command_allowed(["longbridge", "financial-report", "snapshot", "NVDA.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "financial_report")

        capability = assert_longbridge_command_allowed(["longbridge", "forecast-eps", "NVDA.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "forecast_eps")

        capability = assert_longbridge_command_allowed(["longbridge", "consensus", "NVDA.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "consensus")

        capability = assert_longbridge_command_allowed(["longbridge", "finance-calendar", "report", "--format", "json"])
        self.assertEqual(capability.capability_id, "finance_calendar")

        capability = assert_longbridge_command_allowed(["longbridge", "news", "NVDA.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "news")

        capability = assert_longbridge_command_allowed(["longbridge", "filing", "NVDA.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "filing")

        capability = assert_longbridge_command_allowed(["longbridge", "topic", "search", "AI", "--format", "json"])
        self.assertEqual(capability.capability_id, "topic")

        capability = assert_longbridge_command_allowed(["longbridge", "option", "chain", "AAPL.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "option_chain")

        capability = assert_longbridge_command_allowed(["longbridge", "option", "quote", "AAPL260417C190000.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "option_quote")

        capability = assert_longbridge_command_allowed(["longbridge", "option", "volume", "AAPL.US", "--format", "json"])
        self.assertEqual(capability.capability_id, "option_volume")

    def test_denies_trading_write_commands(self) -> None:
        with self.assertRaises(PermissionError):
            assert_longbridge_command_allowed(["longbridge", "submit-order", "NVDA.US"])

        with self.assertRaises(PermissionError):
            assert_longbridge_command_allowed(["longbridge", "cancel-order", "123"])

        with self.assertRaises(PermissionError):
            assert_longbridge_command_allowed(["longbridge", "order", "buy", "NVDA.US", "1"])

        with self.assertRaises(PermissionError):
            assert_longbridge_command_allowed(["longbridge", "topic", "create", "--body", "test"])

        with self.assertRaises(PermissionError):
            assert_longbridge_command_allowed(["longbridge", "option", "exercise", "AAPL260417C190000.US"])

    def test_denies_unknown_commands_until_provider_is_fixed(self) -> None:
        with self.assertRaises(PermissionError):
            assert_longbridge_command_allowed(["longbridge", "unknown-read", "--format", "json"])

    def test_read_capability_requires_implemented_provider_by_default(self) -> None:
        self.assertEqual(assert_read_capability("positions").capability_id, "positions")
        self.assertEqual(assert_read_capability("candles").capability_id, "candles")
        self.assertEqual(assert_read_capability("valuation").capability_id, "valuation")
        self.assertEqual(assert_read_capability("news").capability_id, "news")
        self.assertEqual(assert_read_capability("option_chain").capability_id, "option_chain")
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
