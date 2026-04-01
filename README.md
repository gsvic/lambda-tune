# λ-Tune
The source code of λ-Tune: A Database System Tuning framework based on Large Language Models.

λ-Tune will be presented at ACM SIGMOD 2025, Berlin, Germany. 

Preprint: https://arxiv.org/pdf/2411.03500

## Prerequisites
Ensure you have Python installed on your system. The script is written in Python and requires necessary permissions to 
execute.

### Database System
The user has to provide the credentials of the target database system (Postgres or MySQL) in the `config.ini` file.

### Install Dependencies
#### MacOS


```bash
brew install pkg-config
brew install mysql-client

export PKG_CONFIG_PATH="/opt/homebrew/opt/mysql-client/lib/pkgconfig"

# Create a Virtual Environment
virtualenv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

## Usage

λ-Tune runs with the following command:
`PYTHONPATH=$PWD python lambdatune/run_lambdatune.py --configs $CONFIGS_DIR --out $OUTPUT_FOLDER --system $DBMS`

Where the `$CONFIGS_FOLDER` the folder with the configurations retrieved from the LLM, `$OUTPUT_FOLDER` the folder 
where the benchmark results are saved, and `$DBMS` the database system to tune (Postgres, MySQL).

### Arguments
λ-Tune runs with the following arguments:
```angular2html
--benchmark BENCHMARK     Name of the benchmark to run. Default is "tpch".
--system SYSTEM           System to use for the benchmark. Default is "postgres".
--scenario SCENARIO       Scenario to use for the benchmark. Default is "original_indexes".
--configs CONFIGS         The LLM configs dir
--out OUT                 The results output directory
--config_gen CONFIG_GEN   Retrieves configurations from the LLM.
--cores CORES             The number of cores of the system
--memory MEMORY           The amount of memory (GB) of the system
```

### Getting configurations from the LLM
Users can either use the already existing configurations under the `configs` directory, or, create their own. To do so,
the `config_gen true` argument has to be provided. In that case, the OpenAI API key have to be set using the 
`OPENAI_API_KEY` environmental variable.

### Examples
1. To run the Join Order Benchmark over Postgres using the provided `tpch_postgres_1` configuration directory, 
use the following command:
    ```bash
    PYTHONPATH=$PWD python lambdatune/run_lambdatune.py --configs ./lambdatune/configs/tpch_postgres_1 --out ./test --system POSTGRES
   
2. To run the Join Order Benchmark over Postgres, and generate new configurations for a system with 4 GB of memory 
and 4 cores, use the following command:
    ```bash
    PYTHONPATH=$PWD python lambdatune/run_lambdatune.py --configs new_config --memory 4 --cores 4 --out ./test --system POSTGRES --benchmark job --config_gen true

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
