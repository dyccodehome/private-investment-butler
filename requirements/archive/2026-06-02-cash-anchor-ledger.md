# Cash Anchor 本地账本

状态：done

创建日期：2026-06-02

## 背景

A 股红利持仓很难稳定通过券商 API 获取完整成本价、当前仓位和历史流水，因此 Cash Anchor 需要以本地账本作为主数据源。

## 目标

- 记录年度工资投入。
- 支持修改年度工资投入目标。
- 支持记录红利股当前持仓，只要求股票、股数和成本价。
- 支持买入、卖出、分红流水。
- 生成本地现金流快照。
- 红利股录入保持极简，分红和现价都由后续流程查询或估算。

## 非目标

- A 股持仓以本地账本为主数据源，不依赖外部券商持仓接口。
- 不开放自动交易。
- 不要求用户录入税率或现价。

## 用户流程

1. 用户用 `/contribute` 记录工资投入。
2. 用户用 `/plan` 设置年度目标。
3. 用户用 `/holding` 或 `/holdings` 录入红利持仓。
4. 用户日常用 `/buy`、`/sell`、`/dividend` 维护流水。
5. 用户用 `/snapshot` 查看当前现金流能力。

## 命令或入口

```text
/contribute 5000
/plan contribution=60000
/holding 600900.SH 1000 24.5
/holdings
600900.SH 1000 24.5
601088.SH 500 31.2
/buy symbol=600900.SH shares=100 price=24.5
/sell symbol=600900.SH shares=100 price=28.3
/dividend symbol=600900.SH amount=850
/snapshot
```

## 数据文件

- 读取：`frameworks/Cash_Anchor/data/*.csv`、`frameworks/Cash_Anchor/data/dividend_plan.yaml`
- 写入：`frameworks/Cash_Anchor/data/holdings.csv`
- 写入：`frameworks/Cash_Anchor/data/capital_flows.csv`
- 写入：`frameworks/Cash_Anchor/data/portfolio_events.csv`
- 写入：`frameworks/Cash_Anchor/data/dividend_plan.yaml`

## 验收标准

- [x] `/contribute` 可记录工资投入并返回年度进度。
- [x] `/plan` 可修改年度工资投入目标。
- [x] `/holding` 支持三字段极简格式。
- [x] `/holdings` 支持多行批量导入。
- [x] 不填 `dividend` 时显示“待估算”。
- [x] 不填现价时标记为“待查询”，账本内部以成本价占位。
- [x] `/buy`、`/sell`、`/dividend` 可维护流水。
- [x] `/snapshot` 可输出本地快照。
- [x] 单元测试覆盖主要命令。

## 待确认问题

- 红利估算逻辑需要后续接入公开分红数据源。
- 操作建议需要先查询最新行情，不能依赖手工录入现价。
- 是否需要 A 股人工对账命令 `/reconcile A`。

## 实现记录

- 已实现于 `src/portfolio_ledger.py` 和 `src/command_registry.py`。
- 2026-06-03：根据用户复核，取消硬性目标年分红；年度复盘改为评估实际分红、收益率和框架执行质量。
