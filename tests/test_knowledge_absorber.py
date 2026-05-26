from __future__ import annotations

import unittest

from src.knowledge_absorber import parse_absorb_args, resolve_absorb_target


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


if __name__ == "__main__":
    unittest.main()
