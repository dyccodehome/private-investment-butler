from __future__ import annotations

import unittest

from src.research_dossier import extract_symbol


class ResearchDossierTest(unittest.TestCase):
    def test_extracts_cn_symbol_next_to_chinese_text(self) -> None:
        text = "我现在情绪上头，想不看财报直接满仓买入600900，突破仓位上限也可以"

        self.assertEqual(extract_symbol(text), "600900")

    def test_does_not_treat_a_share_prefix_as_us_ticker(self) -> None:
        self.assertIsNone(extract_symbol("A股半导体成长股跌破 MA120 怎么处理"))


if __name__ == "__main__":
    unittest.main()
