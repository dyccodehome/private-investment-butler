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
            payload = market_intel.fetch_company_news("AI 半导体 最新新闻", query="AI 半导体 最新新闻")

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
            payload = market_intel.fetch_company_news("NVDA", market="US", query="NVDA 最新新闻")

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

    def test_cn_notice_filter_requires_identity_when_symbol_is_known(self) -> None:
        class Frame:
            def to_dict(self, orient: str) -> list[dict[str, str]]:
                return [
                    {
                        "代码": "300831",
                        "名称": "派瑞股份",
                        "公告标题": "关于授权董事会制定2026年中期分红方案的公告",
                        "公告类型": "重大事项",
                    },
                    {
                        "代码": "600900",
                        "名称": "长江电力",
                        "公告标题": "2025年年度权益分派实施公告",
                        "公告类型": "权益分派",
                    },
                ]

        fake_akshare = types.SimpleNamespace(stock_notice_report=lambda symbol, date: Frame())
        with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
            market_intel, "_recent_dates", return_value=["20260605"]
        ):
            result = market_intel._akshare_stock_notices(
                query="600900 长江电力 财报 分红 公告",
                symbol="600900",
                days=1,
            )

        self.assertEqual({item["symbol"] for item in result["items"]}, {"600900"})

    def test_market_event_context_merges_news_and_announcements(self) -> None:
        with patch.object(market_intel, "fetch_company_news") as fetch_news, patch.object(
            market_intel, "fetch_company_announcements"
        ) as fetch_announcements:
            fetch_news.return_value = {
                "status": "ok",
                "source": "market_intel_news",
                "data_type": "news",
                "data": {"items": [{"title": "news", "url": "https://example.com/news"}]},
                "freshness": {},
                "warnings": [],
                "error": "",
                "source_chain": [{"provider": "news", "status": "ok"}],
                "data_quality": {"coverage": {"news": "ok"}},
            }
            fetch_announcements.return_value = {
                "status": "empty",
                "source": "market_intel_announcements",
                "data_type": "announcement",
                "data": {"items": []},
                "freshness": {},
                "warnings": [],
                "error": "no announcement",
                "source_chain": [{"provider": "announcement", "status": "empty"}],
                "data_quality": {"coverage": {"announcement": "missing"}},
            }

            payload = market_intel.fetch_market_event_context("600900 长江电力 高风险买入")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["data"]["symbol"], "600900")
        self.assertEqual(payload["data_quality"]["coverage"], {"news": "ok", "announcement": "missing"})
        self.assertEqual(payload["source_chain"][0]["data_type"], "news")


if __name__ == "__main__":
    unittest.main()
