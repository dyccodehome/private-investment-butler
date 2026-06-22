from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src import longbridge_options_provider as options_provider


class LongbridgeOptionsProviderTest(unittest.TestCase):
    def test_fetch_option_chain_uses_fixed_readonly_command(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [
                        {
                            "call_symbol": "AAPL260417C190000.US",
                            "put_symbol": "AAPL260417P190000.US",
                            "standard": "true",
                            "strike": "190",
                        }
                    ]
                ),
                "stderr": "",
            },
        )()
        with patch("src.longbridge_options_provider.subprocess.run", return_value=completed) as run:
            payload = options_provider.fetch_option_chain("AAPL.US", "2026-04-17", timeout_seconds=4)

        self.assertEqual(
            run.call_args.args[0],
            ["longbridge", "option", "chain", "AAPL.US", "--date", "2026-04-17", "--format", "json"],
        )
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertEqual(run.call_args.kwargs["timeout"], 4)
        self.assertEqual(payload["summary"]["strike_count"], 1)

    def test_fetch_option_quotes_uses_fixed_readonly_command(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [
                        {
                            "symbol": "AAPL260417C190000.US",
                            "last": "12.35",
                            "implied_volatility": "0.2341",
                            "delta": "0.4812",
                        }
                    ]
                ),
                "stderr": "",
            },
        )()
        with patch("src.longbridge_options_provider.subprocess.run", return_value=completed) as run:
            payload = options_provider.fetch_option_quotes(["AAPL260417C190000.US"], timeout_seconds=4)

        self.assertEqual(
            run.call_args.args[0],
            ["longbridge", "option", "quote", "AAPL260417C190000.US", "--format", "json"],
        )
        self.assertEqual(payload["summary"]["quote_count"], 1)
        self.assertEqual(payload["data"]["quotes"][0]["delta"], 0.4812)

    def test_build_options_context_snapshot_is_partial_tolerant(self) -> None:
        with patch("src.longbridge_options_provider.fetch_option_expirations") as expirations, patch(
            "src.longbridge_options_provider.fetch_option_volume"
        ) as volume, patch("src.longbridge_options_provider.fetch_option_volume_daily") as daily, patch(
            "src.longbridge_options_provider.fetch_option_chain"
        ) as chain:
            expirations.return_value = {
                "data": {"expirations": ["2026-04-17"]},
                "summary": {"expiration_count": 1},
            }
            volume.return_value = {"data": {"call_vol": "100", "put_vol": "180", "pc_ratio": "1.8"}, "summary": {}}
            daily.return_value = {"data": {"rows": [{"date": "2026-04-16", "pc_vol": 1.8, "pc_oi": 0.7}]}, "summary": {}}
            chain.side_effect = RuntimeError("chain unavailable")

            snapshot = options_provider.build_options_context_snapshot(symbols=["AAPL.US"], market="US")

        self.assertEqual(snapshot["data_quality"]["status"], "partial")
        self.assertEqual(snapshot["summary"]["symbols_with_expirations"], 1)
        self.assertEqual(snapshot["summary"]["symbols_with_volume"], 1)
        self.assertEqual(snapshot["symbol_data"]["AAPL.US"]["risk_summary"]["put_call_signal"], "put_pressure_extreme")
        self.assertTrue(any("chain unavailable" in item for item in snapshot["data_quality"]["limitations"]))


if __name__ == "__main__":
    unittest.main()
