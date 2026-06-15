from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import cash_anchor_watchlist


class CashAnchorWatchlistTest(unittest.TestCase):
    def test_upsert_cash_watch_item_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _watchlist_paths(Path(tmp))
            with _patch_watchlist_paths(paths):
                result = cash_anchor_watchlist.upsert_cash_watch_item(
                    symbol="600900.SH",
                    name="长江电力",
                    market="A股",
                    category="dividend",
                    priority="high",
                    watch_reason="核心红利",
                    trigger_condition="股息率回到目标区间",
                )
                snapshot = cash_anchor_watchlist.build_cash_watchlist_snapshot(market="CN")

        self.assertEqual(result["watch_action"], "created")
        self.assertEqual(snapshot["summary"]["watchlist_count"], 1)
        self.assertEqual(snapshot["watchlist"][0]["market"], "CN")
        self.assertEqual(snapshot["watchlist"][0]["symbol"], "600900.SH")

    def test_upsert_replaces_existing_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _watchlist_paths(Path(tmp))
            with _patch_watchlist_paths(paths):
                cash_anchor_watchlist.upsert_cash_watch_item(symbol="QQQI.US", market="US", priority="medium")
                result = cash_anchor_watchlist.upsert_cash_watch_item(symbol="QQQI.US", market="US", priority="high")
                rows = cash_anchor_watchlist.read_cash_watchlist()

        self.assertEqual(result["watch_action"], "updated")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].priority, "high")


def _watchlist_paths(root: Path) -> dict[str, Path]:
    framework = root / "Cash_Anchor"
    data = framework / "data"
    templates = framework / "data_templates"
    templates.mkdir(parents=True)
    (templates / "cash_watchlist.csv").write_text(
        "symbol,name,market,category,priority,watch_reason,trigger_condition,status,last_review_at,notes\n",
        encoding="utf-8",
    )
    return {
        "framework": framework,
        "data": data,
        "templates": templates,
        "watchlist": data / "cash_watchlist.csv",
    }


def _patch_watchlist_paths(paths: dict[str, Path]):
    return patch.multiple(
        cash_anchor_watchlist,
        CASH_ANCHOR_DIR=paths["framework"],
        DATA_DIR=paths["data"],
        TEMPLATE_DIR=paths["templates"],
        WATCHLIST_PATH=paths["watchlist"],
    )


if __name__ == "__main__":
    unittest.main()
