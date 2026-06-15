# Private Investment Butler Agent Framework

本项目是一个本地优先、纯 Python 手搓编排的私人投资管家多智能体系统。系统不依赖 LangGraph 等状态机框架，核心生命周期由 `main.py` 中显式控制流驱动。

## 1. 系统拓扑

采用 Orchestrator-Workers 星型拓扑：

- Master Agent：`main.py` + `src/master_router.py`
  - 负责接收用户输入、语义路由、处理子 Agent 弹回、控制管道流转。
- Worker Agents：`src/sub_agent.py`
  - 每次只加载一个策略岛的 `constitution.md`。
  - 不跨策略读取文档，避免策略逻辑污染。
- Auditor：`src/auditor.py`
  - AOP 切面审计中间件。
  - 在最终输出前独立调用模型进行反方审计。

## 2. 三大策略岛

所有策略物理隔离在 `frameworks/` 下：

```text
frameworks/
├── Cash_Anchor/
│   ├── constitution.md
│   ├── sub_frameworks/
│   ├── logs/
│   └── chat_history/
└── Growth_Engine/
    ├── constitution.md
    ├── sub_frameworks/
    ├── logs/
    └── chat_history/
```

- `Cash_Anchor`：现金锚点，系统防守端与血包，关注股息、现金流、期权权利金。
- `Growth_Engine`：成长引擎，系统进攻端，仅保留美股颠覆性成长子框架；正式标的来源为长桥 universe。

## 3. 全局状态

唯一事实来源是 `src/state.py` 中的 `AgentState`。

它承载：

- 用户原话：`user_input`
- 通讯会话：`chat_id`
- 路由结果：`framework_id`
- 路由弹回：`bounce_back` / `bounce_reason`
- 技能申请：`requested_skills`
- 已披露数据：`disclosed_data`
- 子 Agent 草案：`draft_decision`
- 审计日志：`audit_log`
- 熔断信号：`audit_signal`
- 最终回复：`final_answer`
- 人工确认：`user_action`

## 4. 管道生命周期

入口：`main.py::run_pipeline(user_input, chat_id)`

流程：

1. `route_intent(state)`：Master 语义路由到唯一策略岛。
2. `intake_precheck(state)`：子 Agent 接单预检，不匹配则 bounce-back。
3. `stage_one_request_skills(state)`：子 Agent 只读宪法和用户原话，申请所需 Skill。
4. `load_skill(...)`：主管道按需加载 Skill，写入 `disclosed_data`。
5. `stage_two_decide(state)`：子 Agent 调用策略配置中的 DeepSeek `deepseek-v4-pro` 生成 If-Then 推演。
6. `audit_before_output(state)`：审计官独立调用模型做反方审计。
7. `enforce_circuit_breaker(state)`：检测 `[REJECT]`，必要时熔断。
8. `_send_terminal_result(...)`：通过通讯网关输出最终结果或人工确认卡片。
9. `save_chat_session(state)`：把完整会话写入策略岛 `chat_history/`。

## 5. 通讯架构

飞书入口：`src/feishu_long_connection.py`

- 使用飞书 Python SDK 长连接接收事件，不需要公网回调地址。
- 订阅 `im.message.receive_v1` 接收用户消息。
- 订阅 `card.action.trigger` 接收交互卡片按钮回调。
- 收到普通文本后交给 `src.feishu_runtime.handle_feishu_text_message(...)`。
- 收到卡片按钮后交给 `src.feishu_runtime.handle_feishu_card_callback(...)`。

统一输出口：`src/communication_gate.py`

所有用户可见输出必须走：

```python
communication_gate.send(chat_id, text)
communication_gate.send_card(chat_id, title, text, actions)
```

不要在业务管道里直接调用飞书 API。

## 6. 并发锁

模块：`src/session_lock.py`

按 `chat_id` 加锁：

- 同一个聊天会话只允许一个管道运行。
- 管道运行中再次发消息，直接秒回冷静提示。
- 当前为内存锁，未来多进程部署可替换为 Redis。

## 7. Skill 渐进披露

模块：`src/skills.py`

规则：

- 系统启动不加载所有 Skill 正文。
- `list_skill_ids()` 只扫描 `skills/*/SKILL.md` 元信息。
- 只有当子 Agent 明确申请 Skill 时，主管道才调用 `load_skill(...)`。
- `LoadedSkill.to_payload()` 默认只返回 skill id、描述、路径、参数，不把完整 `SKILL.md` 塞进 LLM prompt。

外部金融数据接入统一收敛在固定 Python Provider 和 `skills/` 边界内。

## 7.1 外部命令与券商数据边界

LLM 不允许自由调用 shell、拼接命令或直接访问券商 CLI/API。

所有外部数据接入必须通过固定 Python 工具层实现：

- 每个能力对应一个明确函数，例如 `sync_longbridge_positions()`。
- Python 工具内部使用白名单命令数组调用外部程序，例如 `["longbridge", "positions", "--format", "json"]`。
- 不允许把用户输入直接拼进 shell 字符串。
- 不开放下单、改单、撤单等交易命令。
- 对外部命令输出必须做 JSON 解析、字段校验、错误分类和超时控制。
- 工具层只能返回结构化结果或同步提案，不能让 LLM 直接覆盖本地账本。

`/sync longbridge` 的目标是触发固定只读同步流程，而不是让模型自行决定执行什么命令。

## 8. 模型配置

统一配置：`config.yaml`

统一读取：`src/app_config.py`

模型调用：`src/llm_client.py`

- 默认 provider：`deepseek`
- 默认模型：`deepseek-v4-pro`
- 支持 provider：`openai`、`deepseek`、`gemini`
- Key：从环境变量读取，不写入仓库。
- 每个策略可单独配置：
  - `provider`
  - `model`
  - `reasoning_effort`
  - `max_output_tokens`
- 横向 Agent 可在 `agents:` 下单独配置模型：
  - `auditor`
  - `knowledge_absorber`

协议适配：

- `openai`：Responses API
- `deepseek`：OpenAI-compatible Chat Completions
- `gemini`：Gemini `generateContent`

未配置 key 时，模型调用返回 `[PROVIDER_NOT_CONFIGURED]`，保证本地管道可测试。

## 9. 审计与熔断

模块：`src/auditor.py`

审计模块是独立 LLM 调用，不复用子 Agent 的结论。设计原则是：

- 模型物理隔离：审计模块通过 `LLMClient.for_agent("auditor")` 读取 `agents.auditor` 配置，不共享子 Agent 会话和策略模型配置。
- 审计重点动态切换：主管道把状态交给审计模块时，根据触发场景注入不同 System Prompt。

当前内置审计重点：

- `风险审计`
  - 触发：子 Agent 给出买入、加仓、补仓、建仓、增持等提案。
  - 重点：检查回撤、仓位、估值、财报、流动性和用户情绪。
- `规则变更审计`
  - 触发：`/absorb` 或任何修改、添加、重写框架宪法的动作。
  - 重点：检查规则变更是否具备跨周期适用性，避免为了短期波动、单一个股故事或社媒情绪修改核心规则。
- `流程审计`
  - 触发：其他普通输出。
  - 重点：检查事实充分性、规则一致性和风险表达。

如果审计输出含 `[REJECT]`，系统进入 `AUDIT_REJECTED`，并通过飞书卡片要求人工确认：

- 继续执行
- 放弃操作

全局 LLM 输出风格：

- 措辞准确、简洁、中性。
- 不使用角色扮演式、夸张、情绪化或修饰性的表达。
- 不使用“首席”“主人”“极端”“终极”“唤醒”“对撞”“轰炸”等词。
- 优先说明事实、判断依据、风险、待确认事项和下一步动作。
- 面向用户的回复避免仪式感文案，直接给出结论和可执行信息。

## 10. 会话黑匣子

模块：`src/context_logger.py`

每次完整会话结束后追加写入：

```text
frameworks/{framework_id}/chat_history/YYYY-MM-DD.jsonl
```

记录内容包括：

- 用户原话
- 路由结果
- 已披露数据摘要
- 子 Agent 草案
- 审计官意见
- 最终回复
- 人工确认

用途：周末复盘 Agent 可读取本周所有 jsonl，生成行为审计报告。

## 11. Token 监控

模块：`src/token_monitor.py`

每次 LLM 调用后追加写入：

```text
runtime/token_usage/YYYY-MM-DD.jsonl
```

记录字段：

- `model`
- `agent_role`
- `framework_id`
- `call_site`
- `input_tokens`
- `output_tokens`
- `reasoning_tokens`
- `total_tokens`
- `latency_ms`
- `prompt_fingerprint`

报表脚本：

```bash
python3 scripts/token_report.py --date 2026-05-17 --top 10
```

用途：

- 找出 token 消耗最大的策略岛。
- 找出 worker/auditor 谁最耗。
- 找出 Top 昂贵调用点。
- 后续针对性拆分宪法、压缩 prompt、分级审计。

## 12. 全链路追踪与成本治理

模块：

- `src/trace_logger.py`
- `src/cost_meter.py`
- `src/observability_api.py`

Trace 事件流写入：

```text
runtime/traces/YYYY-MM-DD.jsonl
```

每个事件包含：

- `trace_id`
- `span_id`
- `event_type`
- `agent_role`
- `framework_id`
- `latency_ms`
- `token_usage`
- `risk_flags`
- `metadata`

当前打点覆盖：

- 飞书消息接收与会话锁
- Master 路由
- 子 Agent bounce-back
- Skill 申请与披露
- LLM 调用完成
- 子 Agent 草案生成
- 审计开始与结束
- 熔断触发
- 人工按钮回调
- 最终消息发送
- 会话黑匣子保存

成本治理配置在 `config.yaml::cost_management`。价格按每百万 token 配置，默认全部为 0，
避免代码硬编码厂商价格。`token_usage` 记录会写入 `estimated_cost_usd`。

本地观测页面：

```text
http://localhost:8000/observability
```

API：

```text
/api/observability/summary
/api/traces
/api/traces/{trace_id}
```

## 13. 研究档案与判断保鲜

模块：`src/research_dossier.py`

每个策略岛可以维护自己的个股研究档案：

```text
frameworks/{framework_id}/research_dossiers/{SYMBOL}.json
```

真实档案默认被 Git 忽略，只提交目录 `.gitkeep` 和 schema 模板：

```text
frameworks/research_templates/dossier_schema.json
```

研究档案解决的问题不是“保存笔记”，而是让投资判断跟随事实持续更新：

- 记录公司基本面、行业周期、估值、买入理由、看多逻辑。
- 记录风险点、退出条件、执行纪律和开放问题。
- 记录每次 Agent 与用户围绕该标的形成的判断。
- 检查 `last_fact_update_at` 是否超过 `stale_after_days`。

核心原则：

```text
资本市场里，过期的判断比没有判断更危险。
```

当用户问题涉及个股分析、财报、买入理由、退出条件、风险点、论据或研究档案时，
子 Agent 必须申请 `research_dossier` Skill。主管道披露档案快照后，LLM 再把：

```text
信息 -> 论据 -> 量化验证 -> 风险管理 -> 执行建议 -> 复盘更新
```

连成闭环。

## 14. 宪法再造与知识吸收

模块：`src/knowledge_absorber.py`

入口命令：

```text
/absorb <framework_id> <文章链接、摘录或你的思考>
```

它用于把外部碎片知识转化为投资框架补丁提案，而不是把文章原文塞进长期上下文。

流程：

```text
碎片输入
  -> 要素提炼
  -> 适用边界识别
  -> 与 Constitution.md 冲突检测
  -> 反方审计
  -> Patch Proposal JSON
  -> 人工按钮确认
```

每个策略岛都有三类本地私有目录：

```text
frameworks/{framework_id}/knowledge_inbox/
frameworks/{framework_id}/patch_proposals/
frameworks/{framework_id}/patch_archive/
```

这些真实内容默认被 Git 忽略，避免把个人阅读材料、草案和决策过程公开。

飞书中的 `/absorb` 必须异步处理：长连接收到消息后立即返回 SDK 回调线程，后台生成提案，再推送审批卡片。

审批按钮：

- `同意并打入宪法`
- `进入观察池`
- `拒绝修改`

同意打补丁前必须检查目标 `constitution.md` 是否有未提交改动。若存在人工草稿，必须拒绝自动写入，避免把人工修改和自动补丁混成一次提交。

## 15. 配置与密钥

模板：`.env.example`

真实密钥只放环境变量：

- `OPENAI_API_KEY`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`
- `FEISHU_ENCRYPT_KEY`
- `YUQUE_TOKEN`
- `YUQUE_NAMESPACE`
- `YUQUE_ARCHIVE_DIR`

`config.yaml` 只记录默认值和环境变量名，不存储真实密钥。

## 16. 本地验证

```bash
python3 -m compileall private_investment_butler

cd private_investment_butler
printf 'A股半导体成长股跌破MA120要不要撤\n' | python3 main.py
python3 scripts/token_report.py --date 2026-05-17
```

启动飞书长连接：

```bash
python3 -m src.feishu_long_connection
```

## 17. 开发约束

- 不引入重型状态机框架。
- 不跨策略岛读取宪法。
- 不在业务模块硬编码密钥。
- 不绕过 `communication_gate` 输出用户可见消息。
- 不把完整 Skill 文档默认塞进 LLM prompt。
- 不把历史持仓数据当作当前事实。
- 所有最终会话必须进入 `chat_history`。
- 所有 LLM 调用必须经过 `llm_client.py`，并写入 token usage。
