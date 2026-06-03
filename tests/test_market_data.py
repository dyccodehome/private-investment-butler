from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src import skills
from src.market_data import provider_router
from src.market_data.symbol_mapper import infer_market, to_longbridge_symbol, to_yahoo_symbol


class MarketDataTest(unittest.TestCase):
    def test_symbol_mapper_handles_a_share_and_us_symbols(self) -> None:
        self.assertEqual(to_yahoo_symbol("600900"), "600900.SS")
        self.assertEqual(to_yahoo_symbol("600900.SH"), "600900.SS")
        self.assertEqual(to_yahoo_symbol("000333"), "000333.SZ")
        self.assertEqual(to_longbridge_symbol("QQQI"), "QQQI.US")
        self.assertEqual(to_longbridge_symbol("XQQI.US"), "XQQI.US")
        self.assertEqual(infer_market("600900.SH"), "CN")
        self.assertEqual(infer_market("QQQI.US"), "US")

    def test_provider_router_uses_yahoo_for_cn(self) -> None:
        with patch("src.market_data.provider_router.fetch_yahoo_quote") as yahoo, patch(
            "src.market_data.provider_router.fetch_longbridge_quote"
        ) as longbridge:
            yahoo.return_value.to_dict.return_value = {"status": "ok", "source": "yfinance"}
            result = provider_router.fetch_market_data("600900.SH", market="CN")

        self.assertEqual(result["source"], "yfinance")
        yahoo.assert_called_once_with("600900.SH")
        longbridge.assert_not_called()

    def test_provider_router_uses_longbridge_for_us(self) -> None:
        with patch("src.market_data.provider_router.fetch_yahoo_quote") as yahoo, patch(
            "src.market_data.provider_router.fetch_longbridge_quote"
        ) as longbridge:
            longbridge.return_value.to_dict.return_value = {"status": "ok", "source": "longbridge"}
            result = provider_router.fetch_market_data("QQQI", market="US")

        self.assertEqual(result["source"], "longbridge")
        longbridge.assert_called_once_with("QQQI")
        yahoo.assert_not_called()

    def test_longbridge_market_provider_wraps_quote(self) -> None:
        from src.longbridge_provider import LongbridgeQuote
        from src.market_data.longbridge_market_provider import fetch_longbridge_quote

        with patch("src.market_data.longbridge_market_provider.fetch_longbridge_quotes") as fetch_quotes:
            fetch_quotes.return_value = {
                "QQQI.US": LongbridgeQuote(
                    symbol="QQQI.US",
                    current_price=57.12,
                    quote_source="last",
                    timestamp="",
                )
            }
            result = fetch_longbridge_quote("QQQI")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.source, "longbridge")
        self.assertEqual(result.data["provider_symbol"], "QQQI.US")
        self.assertEqual(result.data["current_price"], 57.12)

    def test_yahoo_provider_reports_missing_dependency(self) -> None:
        from src.market_data.yahoo_provider import fetch_yahoo_quote

        with patch("src.market_data.yahoo_provider._import_yfinance", side_effect=ImportError):
            result = fetch_yahoo_quote("600900.SH")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.source, "yfinance")
        self.assertIn("未安装 yfinance", result.error)

    def test_hithink_market_skill_uses_unified_provider(self) -> None:
        skills.SKILL_REGISTRY = {}
        with patch("src.market_data.provider_router.fetch_quote") as fetch_quote:
            result_obj = Mock()
            result_obj.to_dict.return_value = {"status": "ok", "source": "yfinance", "symbol": "600900.SH"}
            fetch_quote.return_value = result_obj
            payload = skills._execute_skill_payload("hithink-market-query", {"symbol": "600900.SH", "market": "CN"})

        self.assertEqual(payload["source"], "yfinance")
        fetch_quote.assert_called_once_with("600900.SH", market="CN")


if __name__ == "__main__":
    unittest.main()
