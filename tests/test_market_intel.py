from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from src import market_intel


class MarketIntelTest(unittest.TestCase):
    def test_generic_query_does_not_infer_us_ticker_from_theme_word(self) -> None:
        with patch.object(market_intel, "_akshare_stock_news") as cn_news, patch.object(
            market_intel, "_yfinance_news"
        ) as us_news:
            cn_news.return_value = {"status": "empty", "items": [], "error": "no cn result"}
            us_news.return_value = {"status": "empty", "items": [], "error": "no us result"}
            payload = market_intel.fetch_company_news({"query": "AI 半导体 最新新闻"})

        self.assertEqual(payload["data"]["symbol"], "")
        self.assertEqual(payload["data"]["market"], "")
        self.assertEqual(
            [item["provider"] for item in payload["source_chain"]],
            ["akshare_stock_news_em", "yfinance_news"],
        )

    def test_us_symbol_uses_yfinance_news(self) -> None:
        with patch.object(market_intel, "_yfinance_news") as us_news, patch.object(
            market_intel, "_akshare_stock_news"
        ) as cn_news:
            us_news.return_value = {
                "status": "ok",
                "items": [{"title": "Nvidia files latest update", "url": "https://example.com"}],
                "error": "",
            }
            payload = market_intel.fetch_company_news({"symbol": "NVDA", "market": "US"})

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["source"], "market_intel_news")
        self.assertEqual(payload["data"]["items"][0]["title"], "Nvidia files latest update")
        us_news.assert_called_once_with("NVDA")
        cn_news.assert_not_called()

    def test_cn_notice_filter_searches_title_and_name_fields(self) -> None:
        class Frame:
            def to_dict(self, orient: str) -> list[dict[str, str]]:
                if orient != "records":
                    raise AssertionError(f"unexpected orient: {orient}")
                return [
                    {
                        "代码": "600900",
                        "名称": "长江电力",
                        "公告标题": "2025年度分红公告",
                        "公告类型": "权益分派",
                        "公告日期": "2026-06-05",
                        "网址": "https://example.com/notice",
                    }
                ]

        fake_akshare = types.SimpleNamespace(stock_notice_report=lambda symbol, date: Frame())
        with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
            market_intel, "_recent_dates", return_value=["20260605"]
        ):
            result = market_intel._akshare_stock_notices(query="年度分红", symbol="", days=1)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["items"][0]["title"], "2025年度分红公告")


if __name__ == "__main__":
    unittest.main()
