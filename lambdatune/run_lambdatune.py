import configparser
import logging
import argparse

from lambdatune.utils import get_dbms_driver
from pkg_resources import resource_filename

from lambdatune.benchmarks import get_job_queries, get_tpch_queries, get_tpcds_queries
from lambdatune.config_selection.configuration_selector import ConfigurationSelector

from lambdatune.prompt_generator.compress_query_plans import get_configurations_with_compression


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Script to run benchmarks.')
    parser.add_argument('--benchmark', type=str, default='tpch',
                        help='Name of the benchmark to run. Default is "tpch".')
    parser.add_argument('--system', type=str, default='POSTGRES',
                        help='System to use for the benchmark. Default is "POSTGRES".')
    parser.add_argument('--scenario', type=str, default='original_indexes',
                        help='Scenario to use for the benchmark. Default is "original_indexes".')

    parser.add_argument("--configs", type=str, help="The LLM configs dir")
    parser.add_argument("--out", type=str, help="The results output directory")

    parser.add_argument("--config_gen", type=bool, default=False,
                        help="Retrieves configurations from the LLM.")

    parser.add_argument("--cores", type=int, help="The number of cores of the system")
    parser.add_argument("--memory", type=int, help="The amount of memory (GB) of the system")

    args = parser.parse_args()

    llm_configs_dir = args.configs
    output_dir = args.out
    benchmark = args.benchmark
    system = args.system
    config_gen = args.config_gen

    memory = args.memory
    cores = args.cores

    # Parse config file
    config_parser = configparser.ConfigParser()
    f = resource_filename("lambdatune", "resources/config.ini")
    config_parser.read(f)

    scenario = "original_indexes"

    enable_query_scheduler = True
    adaptive_timeout = True
    create_indexes = True
    drop_indexes = True
    create_all_indexes_first = False
    compressor = True
    no_queries_in_prompt = False

    logging.info(f"LLM Config Dir: {llm_configs_dir}")

    driver = get_dbms_driver(system, db=benchmark)
    queries = None

    if benchmark == "tpch": queries = get_tpch_queries()
    elif benchmark == "tpcds": queries = get_tpcds_queries()
    elif benchmark == "job": queries = get_job_queries()
    else:
        raise Exception("Benchmark {} does not exist. Pick one from {tpch, tpcds, job}"%(benchmark))

    if config_gen:
        get_configurations_with_compression(output_dir_path=llm_configs_dir,
                                            driver=driver,
                                            queries=queries,
                                            target_db="postgres",
                                            benchmark="tpch",
                                            memory_gb=memory,
                                            num_cores=cores,
                                            num_configs=3)

    timeouts = [10]

    configurations = ConfigurationSelector.load_configs(llm_configs_dir, system=system)

    for timeout in timeouts:
        selector = ConfigurationSelector(configs=configurations,
                                         driver=driver,
                                         queries=queries,
                                         enable_query_scheduler=True,
                                         create_all_indexes_first=False,
                                         create_indexes=True,
                                         drop_indexes=True,
                                         reset_command="ALTER SYSTEM RESET ALL;",
                                         initial_time_out_seconds=timeout,
                                         timeout_interval=10,
                                         max_rounds=5,
                                         benchmark_name=benchmark,
                                         system=system,
                                         adaptive_timeout=adaptive_timeout,
                                         output_dir=output_dir
                                         )

        selector.select_configuration()
