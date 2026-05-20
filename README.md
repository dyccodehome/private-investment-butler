# Private Investment Butler

A local-first multi-agent investment assistant built with pure Python orchestration.

This project is a personal AI application engineering showcase: it demonstrates a hand-rolled agent pipeline for investment reasoning, strategy isolation, progressive disclosure, AOP-style audit, Feishu communication, local conversation logging, and token usage monitoring.

> This repository contains code and public-safe scaffolding only. Personal investment logs, chat history, runtime token ledgers, and credentials are intentionally excluded from Git.

## Highlights

- **Hand-rolled orchestration**: no LangGraph or heavy state-machine framework.
- **Strategy-isolated workers**: each strategy has its own `constitution.md` and private log space.
- **Progressive Skill disclosure**: Skills are loaded only when requested by a worker.
- **AOP audit middleware**: an independent auditor challenges worker decisions before output.
- **Feishu async gateway**: webhook receives quickly, then hands off slow agent work to background tasks.
- **Human-in-the-loop circuit breaker**: rejected decisions can be resolved through interactive callbacks.
- **Local black-box logging**: each strategy records private chat history as local JSONL.
- **Token usage ledger**: model usage is recorded by role, framework, call site, and prompt fingerprint.
- **OpenAI Responses API**: default model is configurable as `gpt-5.5`.

## Architecture

```text
private_investment_butler/
├── AGENTS.md                     # Agent framework document
├── config.yaml                   # Non-secret runtime config
├── main.py                       # Pipeline entry
├── frameworks/                   # Strategy islands
│   ├── Cash_Anchor/
│   ├── CN_Alpha_Growth/
│   └── US_Disruptive_Growth/
├── skills/                       # On-demand Skill instructions and tools
├── src/                          # Core orchestration modules
├── scripts/                      # Local reports and utilities
└── runtime/                      # Local-only runtime ledgers
```

## Strategy Islands

- `Cash_Anchor`: defensive cash-flow anchor for dividends, option premium, and portfolio liquidity.
- `CN_Alpha_Growth`: China alpha growth engine for A-share industrial upgrades and trend discipline.
- `US_Disruptive_Growth`: global disruptive growth engine for AI, biotech, SaaS, and technology moats.

Each strategy owns:

```text
constitution.md
logs/
chat_history/
```

Only `.gitkeep` files are committed under `logs/` and `chat_history/`. Real local records are ignored.

## Core Pipeline

The main lifecycle lives in `main.py`:

1. Semantic routing by `src/master_router.py`
2. Worker intake precheck by `src/sub_agent.py`
3. On-demand Skill loading by `src/skills.py`
4. Worker reasoning through `src/llm_client.py`
5. AOP audit by `src/auditor.py`
6. Feishu/user output through `src/communication_gate.py`
7. Local black-box logging by `src/context_logger.py`
8. Token usage logging by `src/token_monitor.py`

## Configuration

Copy the environment template:

```bash
cp .env.example .env
```

Configure credentials locally:

```bash
OPENAI_API_KEY=...
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_VERIFICATION_TOKEN=...
FEISHU_ENCRYPT_KEY=...
YUQUE_TOKEN=...
IWENCAI_API_KEY=...
```

Do not commit `.env`.

## Run Locally

```bash
python3 -m compileall .
printf 'A股半导体成长股跌破MA120要不要撤\n' | python3 main.py
```

Run the Feishu gateway:

```bash
uvicorn src.feishu_gateway:app --host 0.0.0.0 --port 8000
```

Generate a token report:

```bash
python3 scripts/token_report.py --date 2026-05-17 --top 10
```

## Privacy Boundary

The following are local-only and ignored by Git:

- `.env`
- `frameworks/*/logs/*`
- `frameworks/*/chat_history/*`
- `runtime/token_usage/*`
- Python cache files

This lets the public repository show the engineering design without exposing private investment records.

## Disclaimer

This is an engineering project and personal AI assistant framework. It is not financial advice and should not be used as an automated trading system without independent review and risk controls.
