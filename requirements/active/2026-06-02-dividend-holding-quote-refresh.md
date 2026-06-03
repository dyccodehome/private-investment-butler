# 红利股分析前自动查询最新价和分红信息

状态：implementing

创建日期：2026-06-02

## 背景

用户录入红利股时只希望提供股票、股数和成本价。现价、股息和后续操作建议应由 Agent 在分析时自行查询公开信息后给出，避免用户手工维护现价。

## 目标

- `/holding` 和 `/holdings` 不要求用户输入现价。
- 手工录入时，账本内部 `current_price` 暂用成本价占位，并标记 `current_price=pending_quote`。
- 后续红利股分析或操作建议前，Agent 应先通过 Yahoo Finance 查询 A 股最新行情。
- 分红能力计算前，应优先通过 Yahoo Finance 查询或估算最新每股年分红。
- 如果行情或分红数据源不可用，回复必须明确说明数据缺口，不能把成本价当成实时价格。
- 美股金融数据统一使用 Longbridge，只读调用。

## 非目标

- 不开放自动交易。
- 不依赖同花顺个人持仓 API。
- 不要求用户录入税率。
- 暂不迁移新闻、公告和研报数据源。

## 用户流程

1. 用户录入红利股：

```text
/holding 600900.SH 1000 24.5
```

2. 用户请求分析或操作建议。
3. Agent 查询最新价和分红信息。
4. Agent 基于成本价、最新价、估算股息率和现金流框架给出建议。

## 命令或入口

```text
/holding 600900.SH 1000 24.5
/holdings
600900.SH 长江电力 1000 24.5
601088.SH 中国神华 500 31.2
```

后续分析入口暂沿用自然语言和 `/snapshot`，后续可新增专门命令。

## 数据文件

- 读取：`frameworks/Cash_Anchor/data/holdings.csv`
- 写入：`frameworks/Cash_Anchor/data/holdings.csv`
- 后续需要读取：Yahoo Finance A 股行情、分红、基础财务数据
- 后续需要读取：Longbridge 美股行情、分红、基础财务数据

## 验收标准

- [x] `/holding` 三字段可写入。
- [x] `/holdings` 三字段多行可写入。
- [x] `/holdings` 支持 `股票代码 股票名称 股数 成本价`。
- [x] 不传现价时，回复显示“当前价：待查询”。
- [x] 不传现价时，notes 写入 `current_price=pending_quote`。
- [x] 红利股分析前自动查询最新价。
- [x] 红利股分析前自动查询或估算每股年分红。
- [x] 数据源不可用时 Provider 明确提示，不给出伪实时数据。
- [x] 新增统一 market data provider。
- [x] A 股 provider 使用 yfinance。
- [x] 美股 provider 使用 Longbridge。
- [x] 旧 `hithink-*` 行情和财务 Skill 改成新 provider 的兼容入口或别名。

## 待确认问题

- Yahoo Finance 的 A 股数据质量是否满足日常决策要求，需要实测验证。
- 新闻、公告、研报是否后续另选内容数据源。

## 实现记录

- 2026-06-02：已完成三字段录入、带股票名称的批量录入和待查询标记。
- 2026-06-02：已确认后续金融数据源方案：A 股用 Yahoo Finance，美股用 Longbridge；新闻、公告、研报暂不纳入本阶段。
- 2026-06-03：已新增统一 Provider 基础层和旧 Skill 兼容入口；下一步接入红利股分析上下文。
- 2026-06-03：`portfolio_snapshot` Skill 已切到增强快照，红利股分析前会附带 Provider 查询结果；行情或分红缺失会以 `status=error` 或 `dividend_status=missing` 保留在上下文。
