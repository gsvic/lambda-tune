import sys
import time
import threading

import streamlit as st
import configparser
import os
import json

from lambdatune.benchmarks import get_job_queries, get_tpch_queries
from lambdatune.config_selection import Configuration
from lambdatune.utils import get_dbms_driver
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "resources", "config.ini")
from lambdatune.config_selection.configuration_selector import ConfigurationSelector

from lambdatune.ui.common import TPCH, JOB

import shutil

from lambdatune.llm_response import LLMResponse

import plotly.express as px # interactive charts
import pandas as pd

# App title
st.set_page_config(page_title="λ-Tune")

st.markdown("# Tuner")
st.markdown("### Tunes the target database system.")

# Replicate Credentials
# Create a black sidebar
# st.markdown("""
# <style>
#     [data-testid=stSidebar] {
#         background-color: #611100;
#     }
# </style>
# """, unsafe_allow_html=True)

with st.sidebar:
    st.title('λ-Tune')
    st.write('LLM-Assisted Database Tuning')

    st.subheader('Database Systems')
    selected_dbms = st.sidebar.selectbox('Choose a Database System', ['Postgres'], key='selected_dbms')

    st.subheader('Benchmark')
    selected_benchmark = st.sidebar.selectbox('Choose a Benchmark', [TPCH, JOB],
                                          key='selected_benchmark', help="Choose a benchmark to tune the database for")

    # Tuning Settings
    # st.sidebar.subheader('Tuning Settings')
    #
    # # Enable Query Scheduler
    # # Create indexes with default value to True
    # create_indexes = st.sidebar.checkbox('Create Indexes', key='create_indexes', value=True,
    #                                      help="Allow λ-Tune to create indexes on the database to improve query performance.")
    #
    # enable_query_scheduler = st.sidebar.checkbox('Enable Query Scheduler', key='enable_query_scheduler',
    #                                              help="When enabled, query order and index creation order will be "
    #                                                   "optimized for the best performance")
    #
    # create_all_indexes_first = st.sidebar.checkbox('Create All Indexes First', key='create_all_indexes_first',
    #                                                help="When enabled, all indexes will be created before the "
    #                                                     "queries are executed. Index creation and query execution are "
    #                                                     "not interleaved in this case.")

    db = "tpch" if selected_benchmark == TPCH else "job"

    print(f"Selected Benchmark: {selected_benchmark}, DB: {db}")

    # Dropdown menu for the configs
    configs_dir = f"../configs/{db}_{selected_dbms.lower()}_1"

    available_configs = [config for config in os.listdir(configs_dir)]

    print(available_configs)

    available_configs.insert(0, "")
    selected_config = st.selectbox('Explore Available Configurations', available_configs, key='selected_config')

    show_table_columns = st.button("Show Real Table/Columns")
    hide_table_columns = st.button("Hide Real Table/Columns")

    hide = True

    if show_table_columns:
        hide = False

    if hide:
        hide = True

    # Set a timeout in seconds
    st.sidebar.subheader('Query Timeout')
    timeout = st.sidebar.slider('Execution round timeout (seconds)', 5, 50)

    # Add a start button
    start_button = st.sidebar.button('Start Tuning')

    # Configuration Tuner
    gptune = "GPTUNE"
    system = selected_dbms


if selected_config:
    st.info("Configuration Browser")
    response = LLMResponse(os.path.join(configs_dir, selected_config))

    s = response.get_config(hide=hide)

    config = Configuration(s)
    st.info("Hints")
    st.write(list(config.get_configs()))

    st.info("Indexes")
    st.write(list(config.get_indexes().values()))


if start_button:
    if os.path.exists("../../results"):
        shutil.rmtree("../../results")

    st.empty()
    st.info("Tuning Started")

    config_parser = configparser.ConfigParser()
    f = _CONFIG_PATH
    config_parser.read(f)

    gptune = "LAMBDA_TUNE"
    system = selected_dbms.lower()

    enable_query_scheduler: bool = False
    create_all_indexes_first: bool = False
    drop_indexes: bool = config_parser.getboolean(gptune, "drop_indexes")
    create_indexes: bool = False
    results_path: str = config_parser[gptune]["results_path"]
    llm_configs_dir: list[str] = configs_dir
    initial_timeout_seconds: int = timeout

    queries = get_tpch_queries() if selected_benchmark == TPCH else get_job_queries()

    print(llm_configs_dir)

    configurations = [(d.split(".json")[0], d) for d in os.listdir(llm_configs_dir)]
    configurations = [(d[0], LLMResponse(os.path.join(llm_configs_dir, d[1]))) for d in configurations]
    configurations = [(d[0], d[1].get_config()) for d in configurations]
    configurations = [(d[0], Configuration(d[1])) for d in configurations]
    # configurations = [d for d in configurations if d[0].startswith(f"{db}_{system.lower()}")]
    configurations = dict(configurations)

    driver = get_dbms_driver(system.upper(), db=db)

    results_path = "../../results"
    selector = ConfigurationSelector(configs=configurations,
                                     driver=driver,
                                     queries=queries,
                                     enable_query_scheduler=enable_query_scheduler,
                                     create_all_indexes_first=create_all_indexes_first,
                                     create_indexes=create_indexes,
                                     drop_indexes=drop_indexes,
                                     reset_command="ALTER SYSTEM RESET ALL;",
                                     initial_time_out_seconds=timeout,
                                     timeout_interval=2,
                                     max_rounds=5,
                                     output_dir=results_path,
                                     benchmark_name=selected_benchmark,
                                     system=selected_dbms.lower(),
                                     adaptive_timeout=True)

    # Add config progress bars
    config_bars = dict()
    config_texts = dict()
    for config in sorted(configurations.keys()):
        config_texts[config] = st.info(f"[{config}] Queries Completed: {0}/{len(queries)}")
        config_bars[config] = st.progress(0)

    t = threading.Thread(target=selector.select_configuration)
    t.start()

    reports_file_path = os.path.join(results_path, "reports.json")
    current_reports = []
    best_config = None
    best_config_time = sys.maxsize

    completed_configs = set()

    with st.spinner("Evaluating Configurations..."):
        while t.is_alive():

            for config_id in sorted(configurations.keys()):
                if config_id in completed_configs:
                    continue

                config_result_path = f"../../results/{config_id}"
                if os.path.exists(config_result_path):
                    completed = os.listdir(config_result_path)

                    config_texts[config_id].info(
                        f"[{config_id}] Queries Completed: {len(completed)}/{len(queries)}")
                    config_bars[config_id].progress(len(completed) / len(queries))

            if os.path.exists(reports_file_path):
                with open(reports_file_path) as fp:
                    data = json.load(fp)

                    if len(data) > len(current_reports):
                        current_reports = data
                        last_report = current_reports[-1]
                        config_id = last_report["config_id"]
                        completed_query_time = last_report["total_completed_query_execution_time"]
                        num_completed_queries = last_report["queries_completed_total"]

                        config_texts[config_id].info(f"[{config_id}] Queries Completed: {num_completed_queries}/{len(queries)}")
                        config_bars[config_id].progress(num_completed_queries / len(queries))

                        if last_report["completed"]:
                            completed_configs.add(config_id)

                            config_texts[config_id].success(
                                "[{}] Queries Completed: {}/{} (Time: {:.2f})".format(
                                    config_id,
                                    num_completed_queries,
                                    len(queries), completed_query_time))

                            if completed_query_time < best_config_time:
                                best_config_time = completed_query_time
                                best_config = config_id
            time.sleep(2)

    st.success("Best configuration: {} took {:.2f}".format(best_config, best_config_time))