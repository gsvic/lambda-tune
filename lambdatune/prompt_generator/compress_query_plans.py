import json
import logging
import os.path
import sys
import time
from collections import defaultdict

from lambdatune.benchmarks import *
from lambdatune.drivers import Driver
from lambdatune.plan_utils.postgres_plan_utils import PostgresPlan
from lambdatune.plan_utils import JoinCollectorVisitor
from lambdatune.utils import get_dbms_driver

from lambdatune.llm import get_config_recommendations_with_compression, get_config_recommendations_with_full_queries

from lambdatune.prompt_generator.ilp_solver import ILPSolver


def group_join_conditions(join_conditions):
    joins = defaultdict(list)
    for cond in join_conditions:
        split = cond[0].split(" = ")

        if len(split) < 2:
            continue

        left = split[0]
        right = split[1]
        joins[left].append([right, cond[2]])

    return joins


def generate_conditions(benchmark: str, dbms: str, num_tokens: int, db:str):
    logging.info(f"Generating conditions for {benchmark} on {dbms}")
    driver = get_dbms_driver("POSTGRES", db=db)

    schema = driver.get_db_schema()

    init_queries = dict(get_job_queries() if benchmark == "job" else get_tpch_queries())

    queries = [(q[0], driver.explain(q[1], explain_json=True, execute=False)) for q in init_queries.items()]
    queries = [(q[0], PostgresPlan(q[1])) for q in queries]
    collector = JoinCollectorVisitor(schema)

    for p in list(queries):
        p[1].root.accept(collector)

    sql_queries = [init_queries[q[0]] for q in list(queries)]

    collector.resolve_aliases()

    rel_names = collector.relations
    conditions = [[d, collector.join_conditions[d], collector.join_cost_estimations[d]] for d in collector.join_conditions]
    grouped_conditions = group_join_conditions(conditions)

    num_tokens = num_tokens
    solver = ILPSolver()
    grouped_optimized = solver.optimize_with_dependencies(grouped_conditions, num_tokens)

    return grouped_optimized


def get_prompt(system: str, join_conditions: dict, temperature: float):

    print("Getting prompt with conditions: ", join_conditions)
    prompt = get_config_recommendations_with_compression(dst_system=system, join_conditions=join_conditions, relations=[],
                                                         temperature=temperature, retrieve_response=False)

    return prompt


def get_configurations(prompt: str):
    return get_config_recommendations_with_compression(prompt)


def get_queries(benchmark: str):
    queries = None
    if benchmark == "job":
        queries = dict(get_job_queries() )
    elif benchmark == "tpch":
        queries = dict(get_tpch_queries())
    elif benchmark == "tpcds":
        queries = dict(get_tpcds_queries())

    return queries


def extract_conditions(driver, queries):
    schema = driver.get_db_schema()
    plans = list()
    c = 0
    for q in queries:
        query_id = q[0]
        plan = driver.explain(q[1], explain_json=True, execute=False)

        if plan:
            plans.append((query_id, plan))
            c += 1

    postgres_plans = list()

    for plan in plans:
        query_id = plan[0]

        try:
            pg_plan = PostgresPlan(plan[1])
        except Exception as e:
            logging.warning(f"Exception thrown while processing {query_id}")
            logging.warning(f"Parsing exception: {e}")
            logging.warning(f"Plan: {plan[1]}")
            continue

        postgres_plans.append((query_id, pg_plan))

    collector = JoinCollectorVisitor(db_schema = schema)

    for p in list(postgres_plans):
        p[1].root.accept(collector)

    collector.resolve_aliases()

    conditions = [[d, collector.join_conditions[d], collector.join_cost_estimations[d]] for d in collector.join_conditions]

    for idx, condition in enumerate(conditions):
        cond = condition[0]

        left_tbl, left_col = cond.split(" = ")[0].split(".")
        right_tbl, right_col = cond.split(" = ")[1].split(".")

        left_cond = left_tbl in schema and left_col in schema[left_tbl]
        right_cond = right_tbl in schema and right_col in schema[right_tbl]

        left_operand = f"{left_tbl}.{left_col}" if left_cond else "--"
        right_operand = f"{right_tbl}.{right_col}" if right_cond else "--"

        conditions[idx] = [f"{left_operand} = {right_operand}", condition[1], condition[2]]

    return conditions


def hide_table_column_names(compressed_columns):
    # Hide table/cols
    columns = dict()
    tables = dict()
    fake_compressed = dict()
    idx = 0

    result = dict()

    for left_tbl_col in compressed_columns:
        left_table = left_tbl_col.split(".")[0]
        left_col = left_tbl_col.split(".")[1]

        if left_table not in tables:
            tbl_fake_name = f"tbl_{idx}"
            idx += 1
            tables[tbl_fake_name] = left_table

        if left_col not in columns:
            col_fake_name = f"col_{idx}"
            idx += 1
            columns[col_fake_name] = left_col

        left_key = f"{tbl_fake_name}.{col_fake_name}"

        if left_key not in fake_compressed:
            fake_compressed[left_key] = list()

        for right_tbl_col in compressed_columns[left_tbl_col]:
            right_table = right_tbl_col.split(".")[0]
            right_col = right_tbl_col.split(".")[1]

            if right_table not in tables:
                tbl_fake_name = f"tbl_{idx}"
                idx += 1
                tables[tbl_fake_name] = right_table

            if right_col not in columns:
                col_fake_name = f"col_{idx}"
                idx += 1
                columns[col_fake_name] = right_col

            right_key = f"{tbl_fake_name}.{col_fake_name}"

            fake_compressed[left_key].append(right_key)

    return fake_compressed, tables, columns


def get_configurations_with_full_queries():
    # queries = queries
    q = list(queries.values())
    num_rounds = 3

    for i in range(0, num_rounds):
        for j in range(0, 5):
            dir = f"../configs/{benchmark}_{system}_full_queries_{i+1}/"
            if not os.path.exists(dir):
                os.mkdir(dir)

            temperature = 0.35
            if j == 0:
                temperature = 0

            doc = get_config_recommendations_with_full_queries(dst_system="postgres", queries=q,
                                                         temperature=temperature,
                                                         retrieve_response=True,
                                                         system_specs={"memory": "61GiB", "cores": 8})

            path = f"../configs/{dir}/config_{benchmark}_FULL_QUERIES_indexes_temp_{temperature}_{int(time.time())}.json"
            json.dump(doc, open(path, "w+"), indent=2)


def get_configurations_with_compression_hidden_columns():
    token_budget = 2000

    conditions = extract_conditions(driver, queries.items())
    grouped_conditions = group_join_conditions(conditions)

    indexes = True
    solver = ILPSolver()
    optimized_with_dependencies = solver.optimize_with_dependencies(grouped_conditions, token_budget)
    hidden_cols, tables, columns = hide_table_column_names(optimized_with_dependencies)

    for i in range(0, 1):
        for j in range(0, 1):
            dir = f"../configs/{benchmark}_{system}_hidden_compression_tokens_{token_budget}_{i+1}"

            if not os.path.exists(dir):
                os.mkdir(dir)

            for i in range(0, 5):
                temp = 0 if i == 0 else 0.35
                doc = get_config_recommendations_with_compression(dst_system="postgres",
                                                                  relations=None,
                                                                  temperature=temp,
                                                                  retrieve_response=True,
                                                                  join_conditions=hidden_cols,
                                                                  system_specs={"memory": "61GiB", "cores": 8},
                                                                  indexes=True)
                doc["hidden_table_cols"] = {
                    "tables": tables,
                    "columns": columns
                }

                path = f"../configs/{dir}/config_{benchmark}_tokens_{token_budget}_COMPRESSED_JOIN_CONDITIONS_indexes_temp_{temp}_{int(time.time())}.json"
                json.dump(doc, open(path, "w+"), indent=2)

                print("Done: " + path)


def get_configurations_with_compression(target_db: str, benchmark: str, memory_gb: int, num_cores: int, driver: Driver,
                                        queries: dict, output_dir_path: str, token_budget: int = sys.maxsize,
                                        num_configs: int=5, temperature: float=0.2, indexes_only: bool=False):

    conditions = extract_conditions(driver, queries)
    grouped_conditions = group_join_conditions(conditions)

    solver = ILPSolver()
    optimized_with_dependencies = solver.optimize_with_dependencies(grouped_conditions, token_budget)

    output_dir = os.path.join(output_dir_path)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for i in range(0, num_configs):
        doc = get_config_recommendations_with_compression(dst_system=target_db,
                                                          relations=None,
                                                          temperature=temperature,
                                                          retrieve_response=True,
                                                          join_conditions=optimized_with_dependencies,
                                                          system_specs={"memory": f"{memory_gb}GB", "cores": num_cores},
                                                          indexes_only=indexes_only,
                                                          indexes=True)

        path = os.path.join(output_dir, f"config_{benchmark}_tokens_{token_budget}_{temperature}_{int(time.time())}.json")
        json.dump(doc, open(path, "w+"), indent=2)

        print("Done: " + output_dir)