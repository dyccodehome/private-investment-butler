from __future__ import annotations

import unittest
from unittest.mock import patch

from src.command_registry import handle_command, help_text, resolve_command


class CommandRegistryTest(unittest.TestCase):
    def test_resolve_command_aliases(self) -> None:
        resolved = resolve_command("/salary 5000")
        self.assertIsNotNone(resolved)
        command, args = resolved
        self.assertEqual(command.name, "contribute")
        self.assertEqual(args, "5000")

        resolved = resolve_command("/target contribution=50000")
        self.assertIsNotNone(resolved)
        command, args = resolved
        self.assertEqual(command.name, "plan")
        self.assertEqual(args, "contribution=50000")

    def test_help_lists_ledger_commands(self) -> None:
        text = help_text()
        self.assertIn("/contribute", text)
        self.assertIn("/plan", text)
        self.assertIn("/holding", text)
        self.assertIn("/absorb", text)
        self.assertIn("Cash_Anchor/CN_Dividend_Income", text)
        self.assertIn("Cash_Anchor/US_Income_Options", text)
        self.assertIn("Growth_Engine/CN_Alpha_Growth", text)
        self.assertIn("Growth_Engine/US_Disruptive_Growth", text)

    def test_plan_usage_message(self) -> None:
        reply = handle_command("/plan", "cli")
        self.assertIsNotNone(reply)
        self.assertIn("用法：/plan", reply or "")

    def test_contribute_rejects_bad_amount(self) -> None:
        reply = handle_command("/contribute abc", "cli")
        self.assertEqual(reply, "投入金额无法解析：abc")

    def test_holding_usage_message(self) -> None:
        reply = handle_command("/holding symbol=600000", "cli")
        self.assertIsNotNone(reply)
        self.assertIn("用法：/holding", reply or "")

    def test_transaction_command_usage_messages(self) -> None:
        self.assertIn("用法：/buy", handle_command("/buy symbol=600000", "cli") or "")
        self.assertIn("用法：/sell", handle_command("/sell symbol=600000", "cli") or "")
        self.assertIn("用法：/dividend", handle_command("/dividend symbol=600000", "cli") or "")

    @patch("src.longbridge_provider.sync_longbridge_positions")
    def test_sync_longbridge_uses_provider(self, sync_positions) -> None:
        sync_positions.return_value = {
            "summary": {"total_positions": 1, "cash_anchor_positions": 1, "excluded_positions": 0},
            "included": [
                {
                    "symbol": "QQQI.US",
                    "name": "QQQI",
                    "quantity": 10,
                    "cost_price": 50,
                    "currency": "USD",
                }
            ],
            "excluded": [],
        }
        reply = handle_command("/sync longbridge", "cli")
        self.assertIsNotNone(reply)
        self.assertIn("长桥持仓同步提案", reply or "")
        self.assertIn("QQQI.US", reply or "")

    @patch("src.longbridge_provider.apply_longbridge_cash_anchor_sync")
    def test_apply_longbridge_uses_provider(self, apply_sync) -> None:
        apply_sync.return_value = {
            "summary": {"updated_count": 1, "skipped_count": 2},
            "updated": [
                {
                    "symbol": "QQQI.US",
                    "name": "QQQI",
                    "shares": 10,
                    "cost_price": 50,
                    "current_price": 55,
                    "annual_dividend_per_share": 6,
                }
            ],
            "skipped": [],
        }
        reply = handle_command("/apply longbridge cash_anchor", "cli")
        self.assertIsNotNone(reply)
        self.assertIn("长桥持仓已写入", reply or "")
        self.assertIn("QQQI.US", reply or "")


if __name__ == "__main__":
    unittest.main()
