# 市场数据 Provider 统一迁移

状态：reviewing

创建日期：2026-06-02

## 背景

当前项目里曾存在多组旧行情/财务 Skill，说明和实现边界依赖专有问句式数据源。用户希望后续金融数据来源统一为：

- A 股金融数据：Yahoo Finance / yfinance
- 美股金融数据：Longbridge

这样可以减少专有 API 依赖，并让数据获取逻辑由固定 Python Provider 控制，而不是让 LLM 自由调用外部工具。

## 目标

- 新增统一市场数据 Provider 模块。
- A 股行情、历史 K 线、分红、基础财务数据优先通过 yfinance 获取。
- 美股行情、持仓、报价、基础数据优先通过 Longbridge 获取。
- Skill 层只做语义入口和兼容别名，不直接写数据抓取逻辑。
- 旧行情、财务和基础信息入口逐步迁移到新 Provider。
- 所有 Provider 返回统一结构：`status`、`source`、`market`、`symbol`、`data`、`error`、`source_chain`、`data_quality`。

## 非目标

- 新闻、公告已迁入标准 Skill payload；研报暂不迁移。
- 暂不实现选股器等复杂自然语言筛选。
- 不开放交易能力。
- 不让 LLM 直接调用 shell、Longbridge CLI 或 yfinance。

## 用户流程

1. 用户录入本地持仓。
2. 用户请求红利股或成长股分析。
3. Agent 根据市场选择 Provider：
   - A 股：yfinance
   - 美股：Longbridge
4. Agent 将行情、分红、财务摘要和本地持仓一起交给 LLM。
5. Agent 输出建议，并明确数据来源和缺口。

## 命令或入口

第一阶段不新增用户命令，先改内部数据流。

后续可新增：

```text
/refresh quotes cash_anchor
/refresh quotes growth
```

用于确认后把最新价写回本地账本。

## 数据文件

- 读取：`frameworks/Cash_Anchor/data/holdings.csv`
- 读取：`frameworks/Growth_Engine/data/growth_holdings.csv`
- 读取：`frameworks/Growth_Engine/data/growth_watchlist.csv`
- 可选写入：本地持仓 CSV 的最新价字段

## 建议模块

```text
src/market_data/
├── __init__.py
├── models.py
├── symbol_mapper.py
├── provider_router.py
├── yahoo_provider.py
└── longbridge_market_provider.py
```

## 验收标准

- [x] `symbol_mapper` 能将 A 股代码映射为 Yahoo Finance 格式。
- [x] `yahoo_provider` 能读取 A 股最新价。
- [x] `yahoo_provider` 能在分红字段不可用时返回明确缺口。
- [x] `longbridge_market_provider` 能读取美股 quote。
- [x] 美股 quote 失败时 fallback 到 yfinance。
- [x] Provider 返回统一结构。
- [x] Provider 返回市场阶段上下文。
- [x] Provider 返回数据质量摘要。
- [x] Cash Anchor 分析前能自动拿到 A 股最新价。
- [x] Growth Engine 复盘能按市场选择数据源。
- [x] `market-data` Skill 接入统一 Provider。
- [x] 数据源失败时，Provider 返回明确缺口。
- [x] 单元测试覆盖 symbol mapping、provider routing 和失败路径。
- [x] 新闻和公告 Skill 已接入免费只读情报 Provider；缺少本地依赖或外部源不可用时返回结构化缺口。

## 待确认问题

- A 股指数、ETF 是否也纳入 Yahoo Finance。港股当前不纳入维护范围。
- Yahoo Finance 数据是否需要缓存，避免频繁请求。
- 是否允许 `/refresh quotes` 写回 CSV，还是只用于当次分析。

## 实现记录

- 2026-06-02：需求已确认，待实现。
- 2026-06-03：新增 `src/market_data/`，包括统一返回结构、A 股 Yahoo Finance 映射、yfinance Provider、Longbridge quote Provider 和 Provider router。旧行情、财务和基础信息入口已收敛到统一 Provider。
- 2026-06-05：行情 Skill 正式改名为 `market-data`；新闻/公告移除专有问句接口，改用 AkShare、YFinance 和 SEC 官方 filings 等免费只读来源。
- 2026-06-03：Growth_Engine 单股复盘和每日复盘在调用 LLM 前会补充 `market_data`，A 股走 yfinance，美股走 Longbridge；失败结果保留在上下文中供 LLM 明确说明缺口。
- 2026-06-03：`portfolio_snapshot` Skill 改为返回 Cash Anchor 增强快照，包含本地账本和只读市场数据，不自动写回 `holdings.csv`。
- 2026-06-04：新增美股行情 fallback、市场阶段上下文、数据质量摘要、新闻/公告标准 payload、输出契约和决策复盘统计。当前进入真实 Provider 和生产链路复核阶段。
