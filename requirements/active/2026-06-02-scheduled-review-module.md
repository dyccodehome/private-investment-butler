# 定时任务复盘模块

状态：reviewing

创建日期：2026-06-02

## 背景

当前项目只有 `scripts/run_growth_daily_review.py` 这种单次脚本。用户希望增加独立的定时任务模块，按固定时间点自动执行复盘，并通过飞书主动推送结果。

## 目标

- 新增独立模块管理定时任务。
- 支持 A 股收盘后复盘。
- 支持美股收盘后复盘。
- 支持周日晚上周复盘。
- 支持跳过周末和手工配置的节假日。
- 支持不同任务调用不同工作流。
- 支持通过 `FEISHU_DEFAULT_CHAT_ID` 主动推送。
- 定时任务配置可读、可改、可测试。
- 任务失败要记录日志，并推送简短错误摘要。

## 非目标

- 不在第一阶段引入复杂任务队列。
- 不做分布式调度。
- 不做 Web 管理后台。
- 不自动交易。

## 建议目录

```text
src/scheduler/
├── __init__.py
├── jobs.py
├── runner.py
└── config.py

scripts/
└── run_scheduler.py
```

## 建议任务类型

```text
cash_anchor_cn_premarket_review
cash_anchor_cn_close_review
growth_us_premarket_review
growth_us_close_review
market_data_refresh
```

第一阶段建议只做：

- `growth_us_premarket_review`
- `growth_us_close_review`

第二阶段再加：

- `cash_anchor_cn_premarket_review`
- `cash_anchor_cn_close_review`
- `market_data_refresh`

## 配置方案

建议放在 `config.yaml`，不要写死在代码里：

```yaml
scheduler:
  enabled: false
  timezone: Asia/Shanghai
  dry_run_by_default: true
  skip_weekends_for_daily: true
  skip_holidays: true
  holidays:
    CN: []
    US: []
  jobs:
    growth_us_close_review:
      enabled: true
      type: growth_us_close_review
      time: "17:20"
      time_timezone: America/New_York
      market: US
      schedule: daily
    growth_us_premarket_review:
      enabled: true
      type: growth_us_premarket_review
      time: "08:40"
      time_timezone: America/New_York
      market: US
      schedule: daily
    growth_weekly_review:
      enabled: true
      type: growth_weekly_review
      market: ALL
      schedule: weekly
      weekday: sunday
      time: "20:00"
```

当前已进入一周试用：`scheduler.enabled=true`，并且 `dry_run_by_default=false`。启动本机常驻进程后，到点会真实调用 LLM 并推送飞书。需要暂停时，把 `scheduler.enabled` 改回 `false`。

美股任务已支持 `time_timezone: America/New_York`，按美东时间判断触发点后自动换算到北京时间。

## 用户流程

1. 用户检查配置：

```bash
python3 scripts/run_scheduler.py --list
```

2. 用户干跑单个任务：

```bash
python3 scripts/run_scheduler.py --run-once growth_us_premarket_review
python3 scripts/run_scheduler.py --run-once growth_us_close_review
python3 scripts/run_scheduler.py --run-once growth_weekly_review
```

3. 用户确认执行策略后，把 `config.yaml` 的 `scheduler.enabled` 改为 `true`，在本机启动常驻进程：

```bash
python3 scripts/run_scheduler.py --run-loop
```

4. 到达配置时间后执行对应 job。
5. job 调用现有复盘函数。
6. 结果发送到 `FEISHU_DEFAULT_CHAT_ID`。

真实执行单次任务需要显式加 `--execute`：

```bash
python3 scripts/run_scheduler.py --run-once growth_us_close_review --execute
```

## 数据文件

- 读取：`.env`
- 读取：`config.yaml`
- 读取：Growth / Cash Anchor 本地持仓文件
- 写入：`runtime/scheduler/*.jsonl`

## 设计建议

优先使用纯 Python 轻量循环，不先引入 APScheduler：

- 依赖少。
- Docker 和本地都容易跑。
- 当前任务数量少。
- 单元测试更简单。

如果未来任务变复杂，再切到 APScheduler。

## 验收标准

- [x] 新增 `scripts/run_scheduler.py`。
- [x] Scheduler 能读取 `config.yaml`。
- [x] Scheduler 能识别启用和禁用的 job。
- [x] 支持 A 股每日 16:30 复盘配置。
- [x] 支持美股每日 06:00 复盘配置。
- [x] 支持周日 20:00 周复盘配置。
- [x] 支持跳过周末。
- [x] 支持手工维护 CN/US 节假日列表。
- [x] 复盘结果可推送飞书。
- [x] 失败时写入 runtime 日志。
- [x] 第一阶段采用本机常驻进程。
- [x] 单元测试覆盖 job 选择、时间判断、干跑路径。
- [x] 单元测试覆盖失败路径。
- [x] 支持任务执行锁，避免同一个 job 被重复触发并发运行。
- [x] 支持美股任务按美东时间触发，自动处理夏令时和冬令时换算。

## 待确认问题

- 美股夏令时切换日前后仍需生产运行观察。

## 实现记录

- 2026-06-02：方案待用户确认。
- 2026-06-03：已新增 `src/scheduler/`、`scripts/run_scheduler.py` 和 `config.yaml` 配置；默认禁用常驻执行，只允许干跑检查。已加入 A 股每日 16:30、美股每日 06:00、周日 20:00 周复盘。
- 2026-06-03：已补充 Scheduler 单元测试，覆盖配置解析、时间判断、周末跳过、干跑不调用 LLM/飞书、失败日志和错误推送。
- 2026-06-03：用户确认第一阶段运行方式为本机常驻。
- 2026-06-03：用户确认开启一周试用，`scheduler.enabled=true`，`dry_run_by_default=false`。
- 2026-06-07：已接入交易日历缓存，美股交易日用本地规则，A 股交易日可通过 AkShare 刷新。
- 2026-06-07：已新增 job 级别文件锁，锁目录为 `runtime/scheduler/locks/`；重复触发同一任务会跳过并在 `runs.jsonl` 中记录 `skipped`。
- 2026-06-07：已新增 `time_timezone` 配置，美股开盘前和收盘后任务改为按 `America/New_York` 的 08:30/08:40/17:10/17:20 触发，自动换算到北京时间。
