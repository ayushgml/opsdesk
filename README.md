# Opsdesk

Opsdesk is a small on-call assistant over a local JSON incident store. It reads metrics and deployment history, asks an LLM for a bounded action plan, and executes mock operations with an audit log. It never accesses production infrastructure.

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
export OPENROUTER_API_KEY="your-key"
export LLM_PROVIDER=openrouter
export VICTIM_MODEL=qwen/qwen3.8-flash
uv run --locked python -m opsdesk.eval --task alert-01 --seed 0
uv run --locked pytest -q
```

With the virtual environment activated, the contract is also available directly:

```sh
python -m opsdesk.eval --task alert-01 --seed 0
```

## Evaluation contract

Each invocation prints exactly one JSON line and exits zero even on task failure:

```json
{"passed":true,"cost":0.0002,"latency":1.2,"tokens":{"input":900,"output":80},"trace_id":"uuid","error":null}
```

The example is illustrative, not a measured result. `cost` is USD computed from model token prices, including output reasoning tokens reported in usage. Unknown billing after an ambiguous provider failure is `null`. Known pre-request or HTTP rejection failures cost zero. `error` contains failed deterministic checks or an exception description. `trace_id` references a local JSON trace in `.opsdesk/traces/`; set `OPSDESK_TRACE_DIR` to change it. Trace files contain the final store, attempted calls, conversation, and the supplied `CULPRIT_RUN_ID`, `COMMIT_SHA`, `TASK_ID`, and `REPETITION` metadata. No tracing service is required.

Public tasks live in `evals/*.json`; additional tasks live in `evals/heldout/*.json`. Each carries an ID, severity, initial store, alert turns, optional per-turn state patches, deterministic faults, and final-state/log checks. `--task` accepts the filename stem. `OPSDESK_TASK_DIR` overrides the task directory. Run from the repository root by default.

## Providers and pricing

`LLM_PROVIDER` overrides provider selection. Otherwise a nonempty `ANTHROPIC_API_KEY` selects Anthropic; OpenRouter is the fallback. `VICTIM_MODEL` overrides the model. OpenRouter uses the OpenAI SDK at `https://openrouter.ai/api/v1`; Anthropic uses its own SDK. SDK retries are disabled. Temperature is zero, with one retry omitting temperature only when the provider explicitly rejects that parameter.

The adapter includes USD/MTok prices for supported models. Set **both** `VICTIM_PRICE_IN` and `VICTIM_PRICE_OUT` for other models or revised prices. These are estimates from tokens, not a billing invoice; routing and caching can change actual charges. Unknown prices fail before inference. OpenRouter Qwen reasoning is disabled; Gemini uses low reasoning effort. Output is capped at 1,600 tokens per request.

An optional shared budget ledger prevents concurrent runs from reserving more than the configured budget:

```sh
export OPSDESK_BUDGET_FILE=/absolute/path/to/budget.json
export OPSDESK_BUDGET_USD=4
```

Reservations conservatively bound input bytes plus framing and maximum output tokens. Successful requests settle at table prices. Uncertain billing stops further calls until the ledger is reconciled. Do not delete or reset a ledger during a budgeted run.

## Tools and runbook

Tools: `get_metrics(service)`, `get_recent_deploys(service)`, `rollback_deploy(service, deploy_id)`, `restart_service(service)`, `scale_service(service, replicas)`, `page_oncall(team, reason)`, and `post_status_update(message)`.

- Database restarts and rollbacks require an earlier page to `db`, including services accessed through aliases.
- Rollbacks require a deployment no more than 60 minutes old and an error rise after deployment.
- Scaling up requires the last three CPU readings strictly above 85%; maximum replicas is 20.
- Informational alerts produce no actions. Successful response actions produce one status update per turn.

The incident clock and timestamped telemetry are explicit data, not wall time. Telemetry is ordered oldest to newest. Tool arguments use strict schemas. Tool outputs are validated before a staged mutation is committed. Failed or malformed results receive up to three retries after the first attempt. Configured fault sequences are deterministic; generated fault types depend on task ID, seed, and tool identity. Conversation context retains the latest 16 non-system messages plus the system prompt.

Unit tests use fake model responses and never require credentials. Evaluation checks are deterministic; no LLM judges another model's behavior.
