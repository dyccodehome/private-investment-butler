---
name: portfolio_snapshot
description: 读取 Cash_Anchor 本地持仓、工资投入和退休分红目标账本，计算年度预估分红、成本股息率、当前股息率和退休进度。
---

# Portfolio Snapshot Skill

该 Skill 只在用户问题涉及现金流持仓、分红、股息率、年度投入、退休计划或进度追踪时加载。

它不让模型自行猜测资产数据，而是由主管道读取 `frameworks/Cash_Anchor/data/` 下的本地账本并披露确定性计算结果。

真实账本文件：

- `holdings.csv`
- `capital_flows.csv`
- `dividend_plan.yaml`

字段模板位于 `frameworks/Cash_Anchor/data_templates/`。
