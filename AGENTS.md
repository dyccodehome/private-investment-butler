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
│   ├── logs/
│   └── chat_history/
├── CN_Alpha_Growth/
│   ├── constitution.md
│   ├── logs/
│   └── chat_history/
└── US_Disruptive_Growth/
    ├── constitution.md
    ├── logs/
    └── chat_history/
```

- `Cash_Anchor`：现金锚点，系统防守端与血包，关注股息、现金流、期权权利金。
- `CN_Alpha_Growth`：中国成长引擎，本土阿尔法，关注 A 股成长、产业升级、MA120 趋势纪律。
- `US_Disruptive_Growth`：全球颠覆性成长，关注美股科技巨头、AI、生物科技、SaaS、TAM 与护城河。

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
- 人工裁决：`user_action`

## 4. 管道生命周期

入口：`main.py::run_pipeline(user_input, chat_id)`

流程：

1. `route_intent(state)`：Master 语义路由到唯一策略岛。
2. `intake_precheck(state)`：子 Agent 接单预检，不匹配则 bounce-back。
3. `stage_one_request_skills(state)`：子 Agent 只读宪法和用户原话，申请所需 Skill。
4. `load_skill(...)`：主管道按需加载 Skill，写入 `disclosed_data`。
5. `stage_two_decide(state)`：子 Agent 调用 OpenAI `gpt-5.5` 生成 If-Then 推演。
6. `audit_before_output(state)`：审计官独立调用模型做反方审计。
7. `enforce_circuit_breaker(state)`：检测 `[REJECT]`，必要时熔断。
8. `_send_terminal_result(...)`：通过通讯网关输出最终结果或人工裁决卡片。
9. `save_chat_session(state)`：把完整会话写入策略岛 `chat_history/`。

## 5. 通讯架构

飞书入口：`src/feishu_gateway.py`

- `/webhook/feishu`
  - 接收飞书消息。
  - 验证 token。
  - 解析 `chat_id` 和文本。
  - 秒回 `{code: 0}`。
  - 后台运行管道。
- `/webhook/callback`
  - 接收交互卡片按钮回调。
  - 处理 `force_execute` / `abandon_operation`。
  - 记录人工裁决到 chat history。

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

iwencai 相关 Skill 已从 `iwencai-investment-engine` 迁入 `skills/`。

## 8. 模型配置

统一配置：`config.yaml`

统一读取：`src/app_config.py`

OpenAI 调用：`src/llm_client.py`

- 默认模型：`gpt-5.5`
- API：OpenAI Responses API
- Key：从环境变量 `OPENAI_API_KEY` 读取，不写入仓库。
- 每个策略可单独配置：
  - `model`
  - `reasoning_effort`
  - `max_output_tokens`

未配置 key 时，模型调用返回 `[OPENAI_NOT_CONFIGURED]`，保证本地管道可测试。

## 9. 审计与熔断

模块：`src/auditor.py`

审计官是独立 LLM 调用，不复用子 Agent 的结论。它根据场景选择人格：

- 日常决策：极端风控官
- 复盘：过拟合纠察员
- 修改框架：逻辑洁癖者

如果审计输出含 `[REJECT]`，系统进入 `AUDIT_REJECTED`，并通过飞书卡片要求人工选择：

- 强行执行
- 放弃操作

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
- 人工裁决

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

## 12. 研究档案与判断保鲜

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

## 13. 配置与密钥

模板：`.env.example`

真实密钥只放环境变量：

- `OPENAI_API_KEY`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_WEBHOOK_URL`
- `FEISHU_VERIFICATION_TOKEN`
- `FEISHU_ENCRYPT_KEY`
- `YUQUE_TOKEN`
- `YUQUE_NAMESPACE`
- `YUQUE_ARCHIVE_DIR`
- `IWENCAI_API_KEY`
- `IWENCAI_API_URL`

`config.yaml` 只记录默认值和环境变量名，不存储真实密钥。

## 14. 本地验证

```bash
python3 -m compileall private_investment_butler

cd private_investment_butler
printf 'A股半导体成长股跌破MA120要不要撤\n' | python3 main.py
python3 scripts/token_report.py --date 2026-05-17
```

启动飞书网关：

```bash
uvicorn src.feishu_gateway:app --host 0.0.0.0 --port 8000
```

## 15. 开发约束

- 不引入重型状态机框架。
- 不跨策略岛读取宪法。
- 不在业务模块硬编码密钥。
- 不绕过 `communication_gate` 输出用户可见消息。
- 不把完整 Skill 文档默认塞进 LLM prompt。
- 不把历史持仓数据当作当前事实。
- 所有最终会话必须进入 `chat_history`。
- 所有 LLM 调用必须经过 `llm_client.py`，并写入 token usage。
