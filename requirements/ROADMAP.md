# 私人投资管家待办清单

最后更新：2026-06-03

这个文件用于跟踪当前 Agent 从工程原型走向稳定日常使用还需要完成的事项。

状态说明：

- `[ ]` 未开始
- `[~]` 进行中
- `[x]` 已完成

## 已完成事项

- [x] 创建 `ROADMAP.md`，用于后续持续跟踪项目进度。
- [x] 在 `README.md` 中记录当前可用 Slash 命令。
- [x] 新增 `/contribute`，用于记录工资投入。
- [x] 新增 `/plan`，用于修改年度工资投入目标。
- [x] 取消 Cash Anchor 硬性目标年分红；年复盘只评估实际分红、收益率和框架执行质量。
- [x] 新增 `/holding`，用于新增/更新持仓并重算分红能力。
- [x] `/holding` 支持先不填写 `dividend`，分红字段进入待估算状态，税率默认按 0 处理。
- [x] `/holding` 支持极简位置参数：`/holding <股票代码> <股数> <成本价>`，现价由后续行情查询流程处理。
- [x] 新增 `/holdings`，支持每行一条极简红利持仓批量写入。
- [x] 新增 `/buy`、`/sell`、`/dividend`、`/snapshot`，用于在没有券商持仓 API 时维护本地持仓账本。
- [x] 新增 `/sync longbridge` 占位命令，后续接入长桥只读持仓同步。
- [x] 新增固定 Longbridge 只读工具层，`/sync longbridge` 只允许调用白名单命令 `longbridge positions --format json`。
- [x] Longbridge 同步按策略过滤：Cash Anchor 只接收 QQQI、XQQI、TQQQ，其他美股持仓过滤。
- [x] Longbridge 同步增加 `quote` 只读行情，写入时用 quote 刷新当前价，不再用成本价代替当前价。
- [x] 新增 `/apply longbridge cash_anchor`，确认后把长桥 Cash Anchor 子集写入本地账本。
- [x] 细化 `/absorb` 目标，支持 Cash Anchor 总框架、A 股红利子框架、美股美元收益子框架分别吸收知识。
- [x] 移除知识吸收“观察池”动作，改为“继续讨论 / 同意 / 拒绝”的人工复核流程。
- [x] 知识吸收讨论中每轮调用 LLM，使用原始提案、目标宪法、审计意见、完整讨论日志和最新用户回复。
- [x] 新增 Growth_Engine 本地成长持仓/自选文件、单股 `/growth-review` 命令和每日复盘脚本入口。
- [x] 新增 Growth_Engine 批量写入命令 `/growth-holdings` 和 `/growth-watchlist`，移除单条成长股写入命令入口。
- [x] 清理单条成长股写入命令删除后遗留的无用格式化函数。
- [x] 在 README 中补充项目文件职责分类。
- [x] 新增 `FEISHU_DEFAULT_CHAT_ID`，成长股每日复盘脚本可默认推送到固定飞书会话，`--chat-id` 可临时覆盖。
- [x] 扩展 `/help`，补充账本命令、长桥同步命令和知识吸收 target_id 说明。
- [x] 将 LLM prompt 正文迁移到 `prompts/` 目录，`src/prompts.py` 只保留模板加载和渲染函数。
- [x] 新增 `requirements/` 需求文档目录，用于保存需求、讨论结论、验收标准和实现记录。
- [x] 新增基础路由测试 `tests/test_router.py`。
- [x] 在 README 中记录外部命令白名单、安全边界、Cash Anchor 数据文件和 Skill payload 契约。
- [x] 新增命令别名：`/salary`、`/deposit`、`/target`、`/position`。
- [x] 新增账本和命令注册的离线单元测试。
- [x] 验证 `python3 -m unittest discover -v` 通过 53 个测试。
- [x] 跑通 CLI 命令入口 smoke test：`printf "/help\n" | python3 main.py`。
- [x] 新增飞书长连接入口 `python3 -m src.feishu_long_connection`。
- [x] 新增飞书长连接重启脚本 `scripts/restart_feishu.sh`。
- [x] 抽出 `src/feishu_runtime.py`，让长连接统一处理消息和卡片回调逻辑。
- [x] 移除 HTTP webhook 入口，不再需要公网回调地址。
- [x] 在允许联网后成功跑通 `/absorb` 提案生成。
- [x] 将十年双资金池路线图拆入现金流总纲、A 股红利子框架、美股收益子框架。
- [x] 对十年路线图拆分结果执行 LLM Purist 审计。
  - 第一次审计返回 `[WARN]`，原因是误引入了 TQQQ。
  - 已删除 TQQQ 相关内容。
  - 最终复审返回 `[ALLOW]`。
- [x] 将 Docker 部署相关事项加入待办清单。

## 需要你复核或提供信息

- [x] 复核十年双资金池路线图写入后的三份宪法文件。
  - `frameworks/Cash_Anchor/constitution.md`
  - `frameworks/Cash_Anchor/sub_frameworks/CN_Dividend_Income.md`
  - `frameworks/Cash_Anchor/sub_frameworks/US_Income_Options.md`
- [ ] 确认当前 Cash Anchor 年度工资投入目标。
  - 可用 `/plan contribution=<金额>` 设置真实年度投入目标。
- [ ] 录入真实工资投入流水。
  - 使用 `/contribute <金额> [YYYY-MM-DD] [备注]`。
- [x] 录入真实持仓。
  - 单只使用 `/holding <股票代码> <股数> <成本价>`。
  - 多只使用 `/holdings` 后接多行 `<股票代码> <股数> <成本价>`。
  - `dividend` 可以暂不填写，后续由 Agent 根据公开信息估算。
  - 现价不需要手工输入，后续操作建议应先查询最新行情。
  - 后续日常买卖优先使用 `/buy`、`/sell`、`/dividend` 记录事件，保留流水轨迹。
- [x] 确认飞书宪法补丁审批允许自动执行 Git commit。
- [ ] 在正式验证飞书生产流程前，确认飞书后台已启用长连接，并订阅消息事件和卡片回调。

## P0 - 跑通核心闭环

- [ ] 配置本地 `.env`，让项目可以真实运行。
  - 模型调用需要：`DEEPSEEK_API_KEY` 或选定模型厂商的 API Key。
  - 飞书接入需要：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_VERIFICATION_TOKEN`、`FEISHU_ENCRYPT_KEY`。
  - 行情/新闻 Skill 需要：`IWENCAI_API_KEY`。
- [ ] 校验 `config.yaml` 里的模型名称和 provider 协议是否真实可用。
  - 当前默认使用 `deepseek` 和 `deepseek-v4-pro`。
  - 需要确认该模型名能被当前厂商 API 接受。
- [ ] 补齐 `frameworks/Cash_Anchor/data/` 下的真实本地数据。
  - [ ] `holdings.csv`
  - [~] `portfolio_events.csv` 已有命令支持，真实买卖和分红流水需要你继续输入。
  - [~] `capital_flows.csv` 已有命令支持，真实流水需要你继续输入。
  - [~] `dividend_plan.yaml` 已有命令支持，只保留年度工资投入目标。
- [x] 跑通并记录一次 CLI smoke test。
  - 示例：`printf '红利持仓今年分红怎么看\n' | python3 main.py`
  - 已验证命令入口：`printf "/help\n" | python3 main.py`
- [ ] 跑通并记录一次飞书长连接 smoke test。
  - 正常接收消息。
  - 后台执行 Agent 管道。
  - 用户能看到回复。

## P1 - 让 Skill 返回真实数据

- [~] 统一金融数据 Provider。
  - [x] 新增统一 `src/market_data/` Provider 模块。
  - [x] A 股金融数据入口切到 Yahoo Finance / yfinance。
  - [x] 美股金融数据入口切到 Longbridge。
  - [x] 旧 `hithink-*` 行情、财务、基础信息 Skill 改为兼容入口或别名。
  - [ ] 新闻、公告、研报暂不纳入本阶段。
- [~] 实现长桥美股持仓只读同步。
  - [x] 第一阶段优先调用 Longbridge CLI：`longbridge positions --format json`。
  - [x] 必须封装为固定 Python 函数，不允许 LLM 自由拼接或执行 shell 命令。
  - [x] Python 层只允许白名单命令数组：`["longbridge", "positions", "--format", "json"]`。
  - [x] Cash Anchor 只接收 QQQI、XQQI、TQQQ，其他持仓过滤。
  - [x] CLI 用 OAuth 登录，本地 token 自动保存在 `~/.longbridge/openapi/tokens/<client_id>`。
  - 第二阶段在字段和流程稳定后，再切换为 Python SDK `TradeContext.stock_positions()`。
  - [x] 增加人工确认后写入 Cash Anchor 本地持仓快照的动作：`/apply longbridge cash_anchor`。
  - 同步结果必须保留事件或快照来源，不能覆盖本地账本审计轨迹。
  - 不在自动流程中开放下单、改单、撤单等交易能力。
- [~] 接入 Longbridge CLI 作为美股只读同步来源。
  - 安装：`brew install --cask longbridge/tap/longbridge-terminal` 或官方安装脚本。
  - 登录：`longbridge auth login`。
  - 验证：`longbridge auth status --format json`。
  - [x] 持仓：`longbridge positions --format json`。
  - [x] `/sync longbridge` 只调用固定 Python 工具层读取 CLI JSON，生成同步提案，不直接覆盖账本。
  - [x] 工具层包含超时、JSON 解析、字段校验和错误提示。
- [ ] 评估是否需要 Python SDK 替换 CLI。
  - SDK 包：`longbridge`。
  - 认证优先使用 OAuth；如需传统 API Key，则只放在 `.env`，不提交。
  - SDK 适合后续 Docker/长期运行，CLI 适合当前快速接入和调试。
- [ ] A 股持仓继续以本地账本为主数据源。
  - 不依赖同花顺个人持仓 API。
  - 用 `/buy`、`/sell`、`/dividend` 维护交易事实。
  - 用月度或季度人工对账修正持仓。
- [ ] 增加 A 股对账流程 `/reconcile A`。
  - 对比本地账本与券商 App 截图/导出表。
  - 记录人工确认日期。
  - 超过 30 天未确认时，在分红分析里提示数据可能过期。
- [x] 实现 `hithink-market-query` 的真实执行 payload。
  - 已接入统一市场数据 Provider。
  - 返回结构化行情事实。
- [x] 实现 `news-search` 的真实执行 payload。
  - 尽量返回标题、发布时间、摘要、来源和 URL。
- [x] 实现 `position_snapshot` 的真实执行 payload。
  - 读取本地持仓数据。
  - 私有文件继续保持 Git 忽略。
- [x] 实现 `trade_history` 的真实执行 payload。
  - 从 chat history、research dossiers 或专门账本中读取历史决策。
- [x] 新增 Tool Registry 配置和校验模块。
  - 配置：`configs/tool_registry.yaml`
  - 模块：`src/tool_registry.py`
  - 覆盖框架权限、Agent 权限、风险等级、人工确认和输出 schema。
- [x] 统一 Skill 返回结构。
  - 标准格式：`{status, source, data_type, data, freshness, warnings, error}`。
  - 避免 `None` payload 被误认为“正常但无数据”。
- [x] 为缺少 Skill 凭据增加基础错误处理。
  - 缺少 API Key 时，不应表现得像“市场结果为空”。
- [x] 新增 Decision Record。
  - 写入：`runtime/decisions/YYYY-MM-DD.jsonl`
  - 用于投资审计复盘，和技术 Trace 分离。
- [x] 新增轻量 Budget Manager。
  - 配置：`config.yaml::budgets`
  - 模块：`src/budget_manager.py`
  - 当前先写预算 trace 和超阈值风险标记。

## P1 - 定时任务复盘模块

- [~] 设计独立 Scheduler 模块。
  - 需求文档：`requirements/active/2026-06-02-scheduled-review-module.md`
  - [x] 确认 A 股复盘时间：北京时间 16:30。
  - [x] 确认美股复盘时间：北京时间 06:00。
  - [x] 确认周复盘时间：周日 20:00。
  - [x] 确认跳过周末，节假日通过配置列表维护。
  - [x] 确认运行方式：本机常驻。
- [x] 新增 `src/scheduler/`。
- [x] 新增 `scripts/run_scheduler.py`。
- [x] 将 Growth CN / US 每日复盘接入 Scheduler。
- [x] 将 Growth 周复盘接入 Scheduler。
- [x] 将定时复盘结果推送到 `FEISHU_DEFAULT_CHAT_ID`。
- [x] Scheduler 默认禁用常驻执行，并默认 dry-run，避免未确认前误调用 LLM。
- [x] 增加 Scheduler 失败路径单元测试。
- [x] 确认正式启用前的运行策略：本机常驻。
- [x] 正式启用一周试用：`scheduler.enabled=true`，`dry_run_by_default=false`。

## P1 - 闭合研究档案循环

- [x] 在主流程终态输出后调用 `append_decision_to_dossier(state)`。
- [x] 检测到标的代码时，把被审计拒绝的决策和审计结果写入对应 dossier。
- [ ] 尽可能把飞书人工覆盖决策也写入对应 dossier。
- [ ] 增加一个命令或流程，用于在财报/新闻后更新 dossier 事实。
- [ ] 当 `freshness.is_stale` 为 true 时，在最终回复里提示档案可能过期。

## P1 - Harness Runtime 架构层

- [x] 新增 `src/harness_runtime.py`，提供稳定 Runtime facade。
- [x] 新增 `src/action_card.py`，提供 Action Card 格式基础。
- [x] 新增 `docs/ARCHITECTURE.md`，区分当前实现文档和目标架构文档。
- [ ] 将 Auditor WARN/REJECT 输出接入标准 Action Card。
- [ ] 将 Growth Review 输出接入 Action Card。
- [ ] 将 `/absorb` 前置 Insight Classification：
  - `constitution_patch`
  - `research_dossier_only`
  - `watch_metric`
  - `risk_warning`
  - `reject`

## P1 - 验证飞书生产流程

- [ ] 测试长连接启动。
- [ ] 测试普通消息解析。
- [ ] 测试重复事件抑制。
- [ ] 测试按 chat_id 加锁。
- [ ] 测试未知 Slash 命令处理。
- [x] 测试 `/absorb` 提案生成。
- [ ] 测试宪法补丁审批按钮。
- [ ] 测试审计拒绝后的按钮。
  - `force_execute`
  - `abandon_operation`
- [ ] 复核 `accept_patch_proposal()` 的行为。
  - 当前它会在回调路径里执行本地 `git commit`。
  - 需要决定保留、加配置开关，还是改为只生成补丁并要求手动提交。

## P2 - 改进路由和配置

- [x] 把 `main.py` 里硬编码的 `MAX_ROUTE_RETRIES = 3` 改为读取 `config.yaml`。
- [ ] 改进 `src/master_router.py` 的关键词路由。
  - 增加常见中英文市场词别名。
  - 对模糊请求给出更清楚的 fallback 行为。
- [ ] 改进 `intake_precheck()`，避免默认 Cash Anchor 路由导致不必要的 bounce loop。
- [ ] 在确定性路由稳定后，再考虑增加可选 LLM router。
- [ ] 为常见用户问题增加路由决策测试。

## P2 - 完善观测和成本控制

- [ ] 在 `config.yaml` 中填写真实模型价格。
- [~] Token Monitor 升级为 Budget Manager。
  - [x] workflow 预算配置
  - [x] 每次 LLM 后累计 trace token
  - [ ] 超预算降级策略
- [ ] 在 README 中补充观测面板使用说明。
  - 后续需要为本地观测面板提供非 webhook 的启动方式。
- [ ] 在 dashboard 中增加按错误类型聚合失败 trace 的视图。
- [ ] 在 dashboard 中增加最贵调用视图。
- [ ] 在 dashboard 中增加审计拒绝和人工覆盖视图。
- [ ] 降低 token 和成本提醒噪音。
  - 避免在同一会话里重复发送同一类提醒。

## P2 - 测试

- [x] 新增 `test_router.py`。
- [x] 新增 `test_portfolio_ledger.py`。
- [x] 新增 `/contribute`、`/plan`、`/holding` 的命令注册测试。
- [ ] 新增 `test_research_dossier.py`。
- [ ] 新增 `test_skill_registry.py`。
- [ ] 新增 `test_feishu_payload_parse.py`。
- [ ] 新增离线 pipeline smoke test。
  - 未配置 provider key 时应返回清晰的 provider-not-configured 结果。
  - 网络/API 失败时应被分类，并输出用户可读错误。
- [ ] 为 Cash Anchor 增加一小组样例 fixture 数据。

## P2 - 文档

- [~] 更新 `README.md`，补充当前命令和观测面板使用方式。
  - [x] 当前 Slash 命令已记录。
  - [ ] 观测面板还需要单独说明。
- [ ] 记录必需 `.env` 变量，以及每个工作流分别需要哪些变量。
- [~] 记录 Cash Anchor 私有数据文件格式。
  - [x] 命令管理的账本文件已记录。
  - [x] 持仓命令字段已记录。
- [x] 记录 Skill payload 契约。
- [x] 记录外部命令白名单与安全边界。
  - LLM 不能自由调用 shell。
  - 外部 CLI/API 只能通过固定 Python 工具函数暴露给 agent。
  - 券商相关工具默认只读，不开放交易执行能力。
- [x] 记录安全的宪法补丁流程。

## P2 - 部署和运维

- [x] 保持本地开发无需 Docker 也能运行。
  - CLI 路径：`python3 main.py`
  - 飞书长连接路径：`python3 -m src.feishu_long_connection`
- [ ] 为飞书网关运行时新增 `Dockerfile`。
- [ ] 为长期运行部署新增 `docker-compose.yml`。
- [ ] 将私有/本地状态通过 volume 挂载，而不是打进镜像。
  - `.env`
  - `frameworks/*/data/`
  - `frameworks/*/chat_history/`
  - `frameworks/*/research_dossiers/`
  - `frameworks/*/knowledge_inbox/`
  - `frameworks/*/patch_proposals/`
  - `frameworks/*/patch_archive/`
  - `runtime/`
- [ ] 记录长连接生产运行方式。
  - 不需要公网 callback URL。
  - 需要保持进程常驻。
  - 需要在飞书后台选择长连接并订阅对应事件。
- [ ] 为网关容器增加 restart policy 和基础 health check。
- [ ] 确保 Docker 部署不会提交或暴露私人投资记录。

## 备注

- 2026-05-25 已确认后续架构：本地持仓账本是主数据源，券商 API 只作为同步和对账来源；A 股不依赖同花顺个人持仓 API，美股后续接入长桥只读持仓同步。
- 2026-05-25 已重新评估长桥接入方式。MCP 更适合 AI 客户端临时工具调用，不作为项目主接入；本项目优先接 Longbridge CLI 的只读 JSON 输出，后续再视稳定性切换 Python SDK。
- 2026-05-25 已确认外部命令安全边界：LLM 不能自由调用 longbridge 或 shell，只能触发固定 Python 白名单工具。
- 2026-05-25 已实现 Longbridge 只读同步提案：Cash Anchor 仅保留 QQQI、XQQI、TQQQ，其他长桥持仓过滤。
- 2026-05-25 已用真实 Longbridge CLI 输出验证 `/sync longbridge`：19 个持仓中 Cash Anchor 匹配 QQQI/XQQI 2 个，过滤 17 个其他持仓。
- 2026-05-26 已细化知识吸收目标：`Cash_Anchor/CN_Dividend_Income` 和 `Cash_Anchor/US_Income_Options` 会读写对应子框架文件。
- 2026-05-26 已新增 `/apply longbridge cash_anchor`，并将 worker、auditor、knowledge absorber 的 LLM prompt 统一到 `src/prompts.py`。
- 2026-05-23 已通过 `python3 -m compileall .` 编译检查。
- 一次本地 CLI 试跑已到达 LLM 调用阶段，但在当前环境中模型网络请求失败。
- 2026-05-24 在允许联网后，`/absorb Cash_Anchor ...` 成功生成本地提案 `CASH-20260524-180424`。
- 2026-05-24 已新增 `/contribute`、`/plan`、`/holding` 账本命令，并补充离线单元测试。
- 2026-05-24 已新增飞书长连接入口，长连接模式不需要公网地址。
- 2026-05-25 已移除 HTTP webhook 入口，飞书接入只保留长连接。
- 工作区已有未提交改动，推进本清单时不要 reset 或回滚不相关修改。
