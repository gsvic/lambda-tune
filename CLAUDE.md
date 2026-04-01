# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**λ-Tune** is an LLM-based database configuration tuning system (presented at ACM SIGMOD 2025). It uses an LLM (OpenAI, Anthropic, Ollama, Bedrock, or any LiteLLM-supported provider) to generate database configurations (indexes + system parameters) and benchmarks them against TPC-H, TPC-DS, or the Join Order Benchmark to find the best-performing configuration.


## Setup

```bash
# macOS prerequisites
brew install pkg-config mysql-client
export PKG_CONFIG_PATH="/opt/homebrew/opt/mysql-client/lib/pkgconfig"

# Python environment
virtualenv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set database credentials and LLM API key in `lambdatune/resources/config.ini` (gitignored):
```ini
[LAMBDA_TUNE]
llm = gpt-4           ; LiteLLM model string — determines provider
openai_key = <your-key>
anthropic_key =       ; optional

[POSTGRES]
user = <your-pg-user>
```

LiteLLM model string format by provider:
- OpenAI: `gpt-4o`, `gpt-4`
- Anthropic: `anthropic/claude-sonnet-4-6`, `anthropic/claude-opus-4-6`
- Ollama: `ollama/llama3`
- Bedrock: `bedrock/anthropic.claude-sonnet-4-5`

## Running

```bash
# Run tuning with existing configs
PYTHONPATH=$PWD python lambdatune/run_lambdatune.py \
  --configs ./lambdatune/configs/tpch_postgres_1 \
  --out ./test \
  --system POSTGRES

# Generate new configs via LLM and run (system specs auto-detected)
PYTHONPATH=$PWD python lambdatune/run_lambdatune.py \
  --configs new_config --out ./test \
  --system POSTGRES --benchmark job \
  --config_gen --num-configs 5
```

Key CLI arguments: `--system` (POSTGRES/MYSQL), `--benchmark` (tpch/tpcds/job), `--config_gen` (enable LLM generation), `--configs` (path to JSON configs or new dir), `--out` (results dir), `--num-configs` (default: 3), `--indexes-only` (skip system knobs).

`--memory` and `--cores` are optional — auto-detected from the OS if omitted.

LLM provider override (all optional, take precedence over config.ini):
- `--provider` — shorthand: `openai`, `anthropic`, `ollama`, `bedrock`
- `--model` — specific model name or full LiteLLM string (e.g. `claude-sonnet-4-6`, `ollama/mistral`)
- `--api-key` — API key; falls back to env vars then config.ini

```bash
# Launch Streamlit UI
streamlit run lambdatune/ui/Home.py

```

## Architecture

### Core Tuning Pipeline (`lambdatune/`)

**Entry point:** `run_lambdatune.py` — orchestrates config generation → config selection → results output.

**Config generation** (`llm/`): `gpt4.py` builds prompts and calls the LLM via LiteLLM. `compress_query_plans.py` (prompt_generator) collects query execution plans, extracts scan/join conditions via `plan_utils/`, then uses an ILP solver (`ilp_solver.py`) to select the most informative conditions within the token budget. The compressed prompt is sent to the LLM to produce JSON configurations (indexes + system knobs, or indexes only via `--indexes-only`).

**Config selection** (`config_selection/`):
- `configuration.py` — represents a configuration (index set + system parameters)
- `configuration_selector.py` — runs each config against benchmark queries with adaptive timeouts; tracks best-seen execution times and tightens timeout per query accordingly
- `query_order_dp.py` — dynamic programming to find the optimal index creation order (minimizes redundant index builds across queries)
- `query_cluster.py` — groups queries by shared index dependencies

**Database drivers** (`drivers/`): `driver.py` defines the base interface. `postgres.py` and `mysqldriver.py` implement it (connect, execute query, create/drop indexes, set system parameters). DuckDB is also referenced but read-only.

**Benchmarks** (`benchmarks/`): `tpch.py`, `tpcds.py`, `job.py` — contain the benchmark query sets.

### Configuration Format

Generated configs are JSON files stored in the `--configs` directory. Each file defines a list of indexes (table, columns) and system parameter key-value pairs. Pre-generated examples are in `lambdatune/configs/`.
