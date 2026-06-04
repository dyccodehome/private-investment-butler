from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.knowledge_absorber import (
    PatchProposal,
    load_patch_proposal,
    parse_absorb_args,
    patch_proposal_path,
    resolve_absorb_target,
    save_patch_proposal,
)


class KnowledgeAbsorberTest(unittest.TestCase):
    def test_parse_absorb_sub_framework_target(self) -> None:
        target_id, text = parse_absorb_args(
            "Cash_Anchor/CN_Dividend_Income 高股息必须检查分红覆盖率"
        )

        self.assertEqual(target_id, "Cash_Anchor/CN_Dividend_Income")
        self.assertEqual(text, "高股息必须检查分红覆盖率")

    def test_resolve_absorb_sub_framework_target(self) -> None:
        target = resolve_absorb_target("Cash_Anchor/US_Income_Options")

        self.assertEqual(target["framework_id"], "Cash_Anchor")
        self.assertEqual(target["target_file"], "sub_frameworks/US_Income_Options.md")
        self.assertEqual(target["target_name"], "美股美元收益子框架")

    def test_unknown_absorb_target_lists_available_targets(self) -> None:
        with self.assertRaises(ValueError) as context:
            parse_absorb_args("Cash_Anchor/Unknown text")

        message = str(context.exception)
        self.assertIn("未知吸收目标", message)
        self.assertIn("Cash_Anchor/CN_Dividend_Income", message)

    def test_resolve_growth_sub_framework_target(self) -> None:
        target = resolve_absorb_target("Growth_Engine/US_Disruptive_Growth")

        self.assertEqual(target["framework_id"], "Growth_Engine")
        self.assertEqual(target["target_file"], "sub_frameworks/US_Disruptive_Growth.md")
        self.assertEqual(target["target_name"], "美股成长子框架")

    def test_patch_proposal_path_normalizes_sub_framework_target(self) -> None:
        self.assertEqual(
            patch_proposal_path("Cash_Anchor/CN_Dividend_Income", "CASH-TEST"),
            patch_proposal_path("Cash_Anchor", "CASH-TEST"),
        )

    def test_save_and_load_patch_proposal_normalizes_storage_framework(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frameworks = Path(tmp) / "frameworks"
            proposal = PatchProposal(
                patch_id="CASH-TEST",
                framework_id="Cash_Anchor/CN_Dividend_Income",
                target_id="Cash_Anchor/CN_Dividend_Income",
                target_file="sub_frameworks/CN_Dividend_Income.md",
                target_name="A 股红利子框架",
            )

            with patch("src.knowledge_absorber.FRAMEWORKS_DIR", frameworks):
                path = save_patch_proposal(proposal)
                loaded = load_patch_proposal("Cash_Anchor/CN_Dividend_Income", "CASH-TEST")

        self.assertEqual(path, frameworks / "Cash_Anchor" / "patch_proposals" / "CASH-TEST.json")
        self.assertEqual(loaded.framework_id, "Cash_Anchor")


if __name__ == "__main__":
    unittest.main()
