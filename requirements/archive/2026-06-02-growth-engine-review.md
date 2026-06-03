# Growth Engine 持仓和自选股复盘

状态：done

创建日期：2026-06-02

## 背景

成长股需要独立于现金流策略维护。本地需要记录持仓和自选股，并支持单股复盘、每日复盘和飞书定时推送。

## 目标

- 本地记录成长股持仓。
- 本地记录成长股自选股。
- 支持批量导入。
- 支持单只股票 LLM 复盘。
- 支持按市场每日复盘。
- 定时脚本可通过默认飞书 chat_id 主动推送。

## 非目标

- 当前版本不自动拉取实时行情、新闻或财报。
- 不把成长股写入 Cash Anchor 账本。
- 不支持自动交易。

## 用户流程

1. 用户用 `/growth-holdings` 批量录入成长持仓。
2. 用户用 `/growth-watchlist` 批量录入成长自选股。
3. 用户用 `/growth-snapshot` 查看本地快照。
4. 用户用 `/growth-review <symbol>` 复盘单只股票。
5. 定时任务调用 `scripts/run_growth_daily_review.py` 输出每日复盘。

## 命令或入口

```text
/growth-holdings
300750.SZ 100 180 195

/growth-watchlist
symbol=300750.SZ name=宁德时代 market=CN priority=high reason=新能源龙头 trigger=利润重新加速

/growth-snapshot market=CN
/growth-review 300750.SZ

python3 scripts/run_growth_daily_review.py --market CN
```

## 数据文件

- 写入：`frameworks/Growth_Engine/data/growth_holdings.csv`
- 写入：`frameworks/Growth_Engine/data/growth_watchlist.csv`
- 读取：`frameworks/Growth_Engine/constitution.md`
- 读取：`frameworks/Growth_Engine/sub_frameworks/*.md`

## 验收标准

- [x] 支持成长持仓本地文件。
- [x] 支持成长自选股本地文件。
- [x] 支持 `/growth-holdings`。
- [x] 支持 `/growth-watchlist`。
- [x] 移除单条写入命令入口。
- [x] 支持 `/growth-review`。
- [x] 支持每日复盘脚本。
- [x] 支持 `FEISHU_DEFAULT_CHAT_ID` 默认推送。
- [x] 单元测试覆盖主要流程。

## 待确认问题

- 后续需要接入行情、新闻和财报数据后再提升复盘质量。
- 定时任务需要确定运行机器和触发时间。

## 实现记录

- 已实现于 `src/growth_portfolio.py`、`scripts/run_growth_daily_review.py`、`src/command_registry.py`。
