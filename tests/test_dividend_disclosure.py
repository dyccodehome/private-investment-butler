from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from src.dividend_disclosure import (
    build_financial_report_review_items,
    build_cn_dividend_disclosure_review,
    classify_dividend_candidate_types,
    fetch_dividend_filing_candidates,
    format_cn_dividend_disclosure_review,
    list_cn_dividend_holdings,
    parse_cash_dividend_per_share,
    parse_distribution_dates,
)
from src.portfolio_ledger import Holding, PortfolioEvent


class DividendDisclosureTest(unittest.TestCase):
    def test_cn_holdings_are_merged_by_canonical_symbol(self) -> None:
        holdings = [
            Holding("000333.SZ", "美的集团", "A股", "CNY", 200, 65, 65, 0, 0),
            Holding("000333", "美的集团", "A股", "CNY", 300, 76, 76, 0, 0),
            Holding("QQQI.US", "QQQI", "US", "USD", 10, 50, 50, 0, 0),
        ]

        result = list_cn_dividend_holdings(holdings)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].symbol, "000333")
        self.assertEqual(result[0].shares, 500)
        self.assertEqual(result[0].source_rows, ("000333.SZ", "000333"))

    def test_parse_cash_dividend_per_share_supports_common_announcement_phrases(self) -> None:
        self.assertEqual(parse_cash_dividend_per_share("每股派发现金红利1.75元（含税）"), 1.75)
        self.assertEqual(parse_cash_dividend_per_share("每10股派发现金红利43.00元"), 4.3)
        self.assertEqual(parse_cash_dividend_per_share("2025年度利润分配方案为10派5.01元"), 0.501)

    def test_classifies_dividend_filing_candidates(self) -> None:
        self.assertEqual(classify_dividend_candidate_types("2025年年度报告")[0], "financial_report")
        self.assertEqual(classify_dividend_candidate_types("2025年度利润分配方案为10派8.2元")[0], "profit_distribution")
        self.assertEqual(classify_dividend_candidate_types("2025年度权益分派实施公告")[0], "equity_distribution_implementation")
        self.assertEqual(
            parse_distribution_dates("股权登记日2026年6月10日 除权除息日2026年6月11日 现金红利发放日2026年6月11日"),
            {
                "record_date": "2026年6月10日",
                "ex_dividend_date": "2026年6月11日",
                "cash_payment_date": "2026年6月11日",
            },
        )

    def test_review_uses_manual_financial_report_workflow(self) -> None:
        holdings = [
            Holding("600900.SH", "长江电力", "A股", "CNY", 1000, 24, 24, 0, 0),
        ]

        snapshot = build_cn_dividend_disclosure_review(holdings=holdings, events=[], as_of=date(2026, 6, 4))

        self.assertEqual(snapshot["status"], "manual_financial_report_review_required")
        self.assertEqual(snapshot["provider"]["name"], "market_intel 财报/公告核验")
        self.assertIn("候选核验项", snapshot["provider"]["note"])
        self.assertIn("行情源返回的股息字段", snapshot["source_policy"]["rejected_sources"])
        self.assertIn("财报", snapshot["daily_review_step"])
        self.assertEqual(snapshot["financial_report_review_items"][0]["priority"], "high")
        self.assertEqual(snapshot["announcement_results"][0]["symbol"], "600900")

    def test_financial_report_review_items_merge_symbols_and_rank_missing_dividend_high(self) -> None:
        holdings = [
            Holding("000333.SZ", "美的集团", "A股", "CNY", 200, 65, 65, 0, 0),
            Holding("000333", "美的集团", "A股", "CNY", 300, 76, 76, 1.0, 0),
            Holding("600900.SH", "长江电力", "A股", "CNY", 1000, 24, 24, 0, 0),
        ]
        events = [
            PortfolioEvent("2026-05-20", "dividend", "000333.SZ", 0, 0, 500, "CNY", "manual", "已到账"),
        ]

        items = build_financial_report_review_items(holdings, events, as_of=date(2026, 6, 4))

        self.assertEqual([item.symbol for item in items], ["600900", "000333"])
        self.assertEqual(items[0].priority, "high")
        self.assertEqual(items[1].priority, "low")
        self.assertEqual(items[1].shares, 500)

    def test_dividend_review_enriches_filing_candidates(self) -> None:
        review_items = build_financial_report_review_items(
            [Holding("600900.SH", "长江电力", "A股", "CNY", 1000, 24, 24, 0, 0)],
            [],
            as_of=date(2026, 6, 4),
        )
        with patch("src.dividend_disclosure.fetch_filings") as fetch_filings:
            fetch_filings.return_value = {
                "status": "ok",
                "source": "market_intel_filings",
                "data": {
                    "items": [
                        {
                            "symbol": "600900",
                            "name": "长江电力",
                            "title": "2025年度利润分配方案为10派8.2元",
                            "category": "利润分配",
                            "published_at": "2026-05-30",
                            "url": "https://example.com/notice",
                            "source": "东方财富公告",
                            "provider": "akshare_stock_notice_report",
                        },
                        {
                            "symbol": "600900",
                            "name": "长江电力",
                            "title": "2025年度权益分派实施公告",
                            "summary": "每10股派发现金红利8.2元。股权登记日2026年6月10日，除权除息日2026年6月11日，现金红利发放日2026年6月11日。",
                            "category": "权益分派实施",
                            "published_at": "2026-06-05",
                            "url": "https://example.com/implementation",
                            "source": "东方财富公告",
                            "provider": "akshare_stock_notice_report",
                        }
                    ]
                },
                "data_quality": {"coverage": {"filing": "ok"}},
                "source_chain": [{"provider": "akshare_stock_notice_report", "status": "ok"}],
                "error": "",
            }

            results = fetch_dividend_filing_candidates(review_items, limit_per_symbol=2)

        self.assertEqual(results[0]["candidate_count"], 2)
        self.assertEqual(results[0]["candidates"][0]["cash_dividend_per_share"], 0.82)
        self.assertEqual(results[0]["classified_candidate_counts"]["profit_distribution"], 2)
        self.assertEqual(results[0]["classified_candidate_counts"]["equity_distribution_implementation"], 1)
        self.assertEqual(results[0]["recognized_cash_dividend_per_share"], [0.82])
        self.assertEqual(results[0]["ledger_update_suggestions"][0]["action"], "update_holding_annual_dividend_per_share")
        self.assertEqual(results[0]["ledger_update_suggestions"][1]["action"], "record_dividend_cash_event")
        self.assertEqual(results[0]["ledger_update_suggestions"][1]["suggested_gross_amount"], 820.0)
        fetch_filings.assert_called_once()

        text = format_cn_dividend_disclosure_review(
            {
                "holding_count": 1,
                "announcement_results": results,
                "matched_announcement_count": 1,
                "financial_report_review_items": [
                    {"priority": "high", "symbol": "600900", "name": "长江电力", "reason": "需核验分红。"}
                ],
            }
        )

        self.assertIn("公告拆分", text)
        self.assertIn("权益分派实施候选 1", text)
        self.assertIn("可识别每股分红 0.82", text)
        self.assertIn("账本更新建议", text)


if __name__ == "__main__":
    unittest.main()
