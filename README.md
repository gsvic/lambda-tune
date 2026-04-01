# λ-Tune
The source code of λ-Tune: A Database System Tuning framework based on Large Language Models.

λ-Tune will be presented at ACM SIGMOD 2025, Berlin, Germany. 

Preprint: https://arxiv.org/pdf/2411.03500

## Prerequisites
Ensure you have Python installed on your system. The script is written in Python and requires necessary permissions to
execute.

### Database System
Provide the credentials of the target database system (Postgres or MySQL) in `lambdatune/resources/config.ini`:

```ini
[LAMBDA_TUNE]
llm = gpt-4
openai_key = <your-openai-key>
anthropic_key =          ; optional — for Anthropic models

[POSTGRES]
user = <your-pg-user>
```

> **Note:** `config.ini` is gitignored and will never be committed.

### Install Dependencies
#### MacOS

```bash
brew install pkg-config mysql-client
export PKG_CONFIG_PATH="/opt/homebrew/opt/mysql-client/lib/pkgconfig"

virtualenv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
PYTHONPATH=$PWD python lambdatune/run_lambdatune.py --configs $CONFIGS_DIR --out $OUTPUT_FOLDER --system $DBMS
```

Where `$CONFIGS_DIR` is the folder with LLM-generated configurations, `$OUTPUT_FOLDER` is where benchmark results are
saved, and `$DBMS` is the database system to tune (`POSTGRES` or `MYSQL`).

### Arguments

```
--benchmark BENCHMARK     Benchmark to run: tpch (default), tpcds, job
--system SYSTEM           Database system: POSTGRES (default), MYSQL
--configs CONFIGS         Path to configs dir, or new dir name when using --config_gen
--out OUT                 Results output directory
--config_gen CONFIG_GEN   Generate new configurations via LLM (true/false)
--cores CORES             Number of CPU cores of the system
--memory MEMORY           Amount of memory in GB

--provider PROVIDER       LLM provider: openai (default), anthropic, ollama, bedrock
--model MODEL             Model name or full LiteLLM string (see examples below)
--api-key API_KEY         API key for the provider (overrides config.ini and env vars)
```

### LLM Providers

λ-Tune uses [LiteLLM](https://github.com/BerriAI/litellm) and supports any provider it covers.
The `--provider` and `--model` flags override `config.ini` at runtime.

| Provider | `--provider` | Example `--model` | Auth |
|---|---|---|---|
| OpenAI | `openai` | `gpt-4`, `gpt-4o` | `OPENAI_API_KEY` or `openai_key` in config.ini |
| Anthropic | `anthropic` | `claude-3-5-sonnet-20241022` | `ANTHROPIC_API_KEY` or `anthropic_key` in config.ini |
| Ollama (local) | `ollama` | `llama3`, `mistral` | None |
| AWS Bedrock | `bedrock` | `anthropic.claude-3-sonnet-20240229-v1:0` | AWS env vars |

You can also pass a fully qualified LiteLLM model string directly via `--model` without `--provider`:
```bash
--model anthropic/claude-3-5-sonnet-20241022
```

### Examples

1. Run TPC-H over Postgres using an existing configuration directory:
    ```bash
    PYTHONPATH=$PWD python lambdatune/run_lambdatune.py \
      --configs ./lambdatune/configs/tpch_postgres_1 \
      --out ./test \
      --system POSTGRES
    ```

2. Generate new configurations via OpenAI GPT-4 and run the Join Order Benchmark:
    ```bash
    PYTHONPATH=$PWD python lambdatune/run_lambdatune.py \
      --configs new_config --memory 4 --cores 4 \
      --out ./test --system POSTGRES \
      --benchmark job --config_gen true
    ```

3. Use Anthropic Claude instead of OpenAI:
    ```bash
    PYTHONPATH=$PWD python lambdatune/run_lambdatune.py \
      --configs new_config --memory 4 --cores 4 \
      --out ./test --system POSTGRES --config_gen true \
      --provider anthropic --model claude-3-5-sonnet-20241022 \
      --api-key $ANTHROPIC_API_KEY
    ```

4. Use a local Ollama model (no API key required):
    ```bash
    PYTHONPATH=$PWD python lambdatune/run_lambdatune.py \
      --configs new_config --memory 4 --cores 4 \
      --out ./test --system POSTGRES --config_gen true \
      --provider ollama --model llama3
    ```

## Citation
```bibtex
@article{giannakouris2025lambda,
  title={$\lambda$-tune: Harnessing large language models for automated database system tuning},
  author={Giannakouris, Victor and Trummer, Immanuel},
  journal={Proceedings of the ACM on Management of Data},
  volume={3},
  number={1},
  pages={1--26},
  year={2025},
  publisher={ACM New York, NY, USA}
}
```
