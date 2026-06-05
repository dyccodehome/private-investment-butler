# Private Investment Butler

> A local-first, pure-Python multi-agent runtime for personal A-share and US-stock investment reasoning. It combines strategy-isolated workers, governed data disclosure, market-data fallback, news and announcement intelligence, output contracts, independent audit, Feishu interaction, and local review records.

[Features](#features) · [Architecture](#architecture) · [Quick Start](#quick-start) · [Daily Workflows](#daily-workflows) · [Commands](#commands) · [Review](#review-and-observability) · [Chinese](README.zh-CN.md)

This repository is an engineering system, not a trading bot. It is designed to keep private investment facts local, make every model-visible fact auditable, and prevent LLMs from directly controlling brokerage tools or rewriting strategy rules without approval.

## Scope

| Area | Current design |
| --- | --- |
| Markets | A-shares and US stocks only. Hong Kong stocks are intentionally out of scope for now. |
| Runtime | Local-first Python pipeline controlled by `main.py`, without LangGraph or heavyweight state-machine frameworks. |
| Communication | Feishu long connection for messages and approval cards. CLI is also supported for local testing. |
| Strategies | `Cash_Anchor` for cash flow, dividends, option income, and defensive liquidity. `Growth_Engine` for A-share growth and US disruptive growth. |
| Data access | Governed Skill disclosure through `configs/tool_registry.yaml`; no free-form shell execution by LLMs. |
| Trading | No order placement, order amendment, or order cancellation. Brokerage integrations are read-only and fixed-function. |
| WebUI | Not part of the current product direction. Local observability APIs exist for traces and cost review. |

## Features

| Capability | What it does |
| --- | --- |
| Strategy-isolated agents | The master router sends each request to one strategy island. A worker only reads its own `constitution.md` and selected sub-framework files. |
| Progressive Skill disclosure | Workers request facts through `SkillRequest`; the runtime loads only approved Skills and returns compact payloads. |
| Tool governance | `configs/tool_registry.yaml` defines allowed frameworks, allowed agents, risk level, access type, timeout, output schema, and approval policy. |
| Market-data fallback | A-share quotes use `yfinance`. US quotes use Longbridge first, then fall back to `yfinance`. Each attempt is stored in `source_chain`. |
| Market phase context | Quote payloads include A-share or US session phase, local market time, trading-day flag, partial-bar warning, and current session windows. |
| News and announcement intelligence | Symbol-specific runs can request recent news and formal announcements. Missing provider credentials are represented as data-quality gaps, not invented facts. |
| Data quality summary | Every normalized Skill payload carries `data_quality`, including coverage, freshness, source chain, and limitations. |
| Output contract | Draft decisions are checked for conclusion, key facts, risk or limitations, and next action. Missing sections are recorded for audit and review. |
| Historical judgment snapshot | Local trade history and research dossiers are summarized into the decision snapshot so later reviews can compare new decisions with old reasoning. |
| Independent audit gate | The auditor is a separate LLM call. It selects risk audit, rule-change audit, or process audit, then can warn or trigger a circuit breaker. |
| Human-in-the-loop circuit breaker | Rejected outputs are paused and sent as Feishu approval cards instead of being silently released. |
| Decision records | Terminal decisions are appended to `runtime/decisions/YYYY-MM-DD.jsonl` with trace id, disclosures, audit signal, output contract, and data quality. |
| Scheduled workflows | Daily and weekly review jobs are configured in `config.yaml` and executed through `scripts/run_scheduler.py`. |
| Token and trace monitoring | LLM calls write token usage, estimated cost, trace events, risk flags, and prompt fingerprints to local runtime logs. |
| Knowledge absorption | `/absorb` turns external notes into constitution patch proposals, runs audit, and waits for explicit human approval before writing rules. |

## Architecture

```text
User message or CLI input
  -> main.py::run_pipeline
  -> Master Router
  -> one strategy island
     -> Worker intake precheck
     -> Skill requests
     -> governed Skill disclosure
     -> Worker draft decision
  -> output contract and decision snapshot
  -> Auditor
  -> circuit breaker
  -> communication_gate output
  -> Decision Record, Trace, Token Usage, Chat History
```

Core directories:

```text
private_investment_butler/
├── main.py                         # CLI entry and explicit pipeline control
├── config.yaml                     # Non-secret model, scheduler, budget, and cost config
├── configs/tool_registry.yaml      # Tool governance registry
├── frameworks/
│   ├── Cash_Anchor/
│   │   ├── constitution.md
│   │   └── sub_frameworks/
│   └── Growth_Engine/
│       ├── constitution.md
│       └── sub_frameworks/
├── prompts/                        # System and user prompt templates
├── skills/                         # On-demand Skill descriptions and tool boundaries
├── src/
│   ├── market_data/                # Quote providers and fallback router
│   ├── scheduler/                  # Scheduled review runner
│   ├── state.py                    # AgentState, the single source of runtime truth
│   ├── sub_agent.py                # Worker precheck, context selection, Skill requests
│   ├── skills.py                   # Skill loading and normalized payload envelopes
│   ├── auditor.py                  # Independent audit gate
│   ├── output_contract.py          # Structured output contract and decision snapshot
│   ├── data_quality.py             # Disclosure quality summaries
│   ├── decision_record.py          # Local terminal decision records
│   └── knowledge_absorber.py       # Constitution patch proposals
├── scripts/
│   ├── run_scheduler.py
│   ├── decision_review_report.py
│   └── token_report.py
└── runtime/                        # Local traces, decisions, scheduler state, token usage
```

## Strategy Islands

| Strategy | Sub-frameworks | Role |
| --- | --- | --- |
| `Cash_Anchor` | `CN_Dividend_Income`, `US_Income_Options` | Defensive cash-flow anchor. Tracks A-share dividend income, US income assets, option premium discipline, liquidity, and local ledgers. |
| `Growth_Engine` | `CN_Alpha_Growth`, `US_Disruptive_Growth` | Offensive growth engine. Tracks A-share alpha growth and US disruptive growth through thesis, valuation, liquidity, and trend discipline. |

Each strategy owns private local state:

```text
frameworks/{strategy}/data/
frameworks/{strategy}/chat_history/
frameworks/{strategy}/research_dossiers/
frameworks/{strategy}/knowledge_inbox/
frameworks/{strategy}/patch_proposals/
frameworks/{strategy}/patch_archive/
```

Only public-safe scaffolding should be committed. Real ledgers, chat history, research notes, runtime traces, and credentials should stay local.

## Data Contract

All executable Skill results are normalized before they are shown to workers or auditors:

```json
{
  "status": "ok | error | missing | empty | provider_not_configured | unauthorized",
  "source": "local | yfinance | longbridge | market_intel_news | market_intel_announcements | ...",
  "data_type": "portfolio_snapshot | market_data | news | announcement | research_dossier | trade_history",
  "data": {},
  "freshness": {
    "as_of": "2026-06-04T16:30:00",
    "stale": false,
    "stale_reason": ""
  },
  "warnings": [],
  "error": "",
  "source_chain": [
    {"provider": "longbridge", "status": "error", "error": "not configured"},
    {"provider": "yfinance", "status": "ok", "error": ""}
  ],
  "data_quality": {
    "coverage": {"quote": "ok", "dividend": "missing", "market_phase": "ok"},
    "freshness": "fresh",
    "limitations": ["Dividend fields are not usable as cash-flow truth."]
  }
}
```

Decision outputs are also checked against a local contract:

```text
minimum output = conclusion + key facts + risk or limitations + next action
```

The validation result is stored in the decision snapshot and later included in review statistics.

## Quick Start

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Create local environment variables:

```bash
cp .env.example .env
```

Common variables:

| Variable | Purpose |
| --- | --- |
| `DEEPSEEK_API_KEY` | Default model provider key. |
| `OPENAI_API_KEY` | Optional OpenAI Responses API provider. |
| `GEMINI_API_KEY` | Optional Gemini provider. |
| `FEISHU_APP_ID`, `FEISHU_APP_SECRET` | Feishu long-connection app credentials. |
| `FEISHU_VERIFICATION_TOKEN`, `FEISHU_ENCRYPT_KEY` | Feishu event verification settings. |
| `FEISHU_DEFAULT_CHAT_ID` | Default chat for scheduled pushes. |
| `YUQUE_TOKEN`, `YUQUE_NAMESPACE`, `YUQUE_ARCHIVE_DIR` | Optional knowledge archive integration. |

Run local checks:

```bash
python3 -m unittest discover
python3 -m compileall .
```

Run one CLI question:

```bash
printf 'NVDA 要不要加仓\n' | python3 main.py
```

Start Feishu long connection:

```bash
python3 -m src.feishu_long_connection
```

The Feishu path uses SDK long connection and does not require a public callback URL.

## Daily Workflows

Scheduled jobs live in `config.yaml::scheduler.jobs`.

| Job | Market | Schedule | Purpose |
| --- | --- | --- | --- |
| `growth_cn_daily_review` | CN | Daily 16:30 Asia/Shanghai | A-share growth review after market close. |
| `cash_anchor_cn_dividend_review` | CN | Daily 18:30 Asia/Shanghai | A-share dividend workflow based on financial reports, dividend announcements, and distribution notices. |
| `cash_anchor_us_income_distribution_sync` | US | Daily 07:15 Asia/Shanghai | US income distribution sync and review. |
| `growth_us_daily_review` | US | Daily 06:00 Asia/Shanghai | US growth review after US market close. |
| `growth_weekly_review` | ALL | Sunday 20:00 Asia/Shanghai | Weekly review across growth frameworks. |

Inspect scheduler config:

```bash
python3 scripts/run_scheduler.py --list
```

Dry-run one job:

```bash
python3 scripts/run_scheduler.py --run-once cash_anchor_cn_dividend_review
```

Execute one job:

```bash
python3 scripts/run_scheduler.py --run-once growth_cn_daily_review --execute
```

Run the scheduler loop:

```bash
python3 scripts/run_scheduler.py --run-loop
```

## Commands

Commands work through CLI input and Feishu messages.

| Command | Purpose |
| --- | --- |
| `/help` | Show available commands. |
| `/status` | Show local runtime status. |
| `/usage` | Show token and usage summary. |
| `/frameworks` | List strategy frameworks. |
| `/contribute 5000` | Record salary contribution into Cash Anchor. |
| `/plan contribution=60000` | Update annual contribution target. |
| `/holding 600900.SH 1000 24.5` | Add or update one dividend holding. |
| `/holdings` | Batch update dividend holdings. |
| `/buy`, `/sell`, `/dividend`, `/snapshot` | Maintain local Cash Anchor events and snapshot. |
| `/sync longbridge` | Generate a read-only Longbridge sync proposal. |
| `/apply longbridge cash_anchor` | Apply the approved Cash Anchor subset from Longbridge. |
| `/growth-holdings` | Batch update Growth Engine holdings. |
| `/growth-watchlist` | Batch update Growth Engine watchlist. |
| `/growth-review NVDA.US` | Review one Growth Engine symbol. |
| `/growth-snapshot` | Show local Growth Engine holdings and watchlist. |
| `/absorb <target> <text>` | Generate an audited constitution patch proposal. |

External command boundary:

- LLMs do not call shell commands directly.
- Brokerage access is exposed only through fixed Python functions.
- Longbridge commands use fixed argument arrays and read-only operations.
- No order placement, amendment, or cancellation commands are exposed.

## Review and Observability

Token report:

```bash
python3 scripts/token_report.py --date 2026-06-04 --top 10
```

Decision review and backtest-readiness report:

```bash
python3 scripts/decision_review_report.py --date 2026-06-04
python3 scripts/decision_review_report.py --start-date 2026-06-01 --end-date 2026-06-04 --json
```

Decision records are stored at:

```text
runtime/decisions/YYYY-MM-DD.jsonl
```

Trace and token logs are stored at:

```text
runtime/traces/YYYY-MM-DD.jsonl
runtime/token_usage/YYYY-MM-DD.jsonl
```

## Privacy Boundary

Keep these local:

- `.env`
- `frameworks/*/data/*`
- `frameworks/*/chat_history/*`
- `frameworks/*/research_dossiers/*`
- `frameworks/*/knowledge_inbox/*`
- `frameworks/*/patch_proposals/*`
- `frameworks/*/patch_archive/*`
- `runtime/*`
- Python cache files

The repository should expose architecture and public-safe templates, not personal investment records.

## Disclaimer

This project is a personal engineering framework for investment research and workflow governance. It is not financial advice, not a recommendation engine, and not an automated trading system. Any investment action requires independent judgment, position sizing, and risk control.
