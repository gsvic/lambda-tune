from __future__ import annotations

import os
import json
import time
import logging

from collections import defaultdict

from lambdatune.drivers import PostgresDriver, MySQLDriver
from lambdatune.config_selection import Configuration, queries_to_index
from lambdatune.config_selection import generate_query_clusters
from lambdatune.config_selection.query_to_index import QueryToIndex
from lambdatune.config_selection.query_cluster import QueryCluster
from lambdatune.config_selection.query_order_dp import compute_optimal_order

from lambdatune.llm_response import LLMResponse


logging.basicConfig(level=logging.DEBUG)


class ConfigurationSelector:
    def __init__(self, driver: PostgresDriver, queries: list[str], configs: list[str], reset_command: str, adaptive_timeout: bool,
                 enable_query_scheduler: bool, create_all_indexes_first: bool, create_indexes: bool, drop_indexes: bool,
                 initial_time_out_seconds: int, timeout_interval: int, max_rounds: int,
                 benchmark_name: str, system: str, output_dir: str = None):
        """
        @param driver: The database driver used to execute the queries
        @param configs: The configurations to be tested
        @param reset_command: The command used to reset the configuration
        """
        logging.info("Initializing Configuration Selector with the following parameters")
        logging.info(f"Reset Command: {reset_command}")
        logging.info(f"Enable Query Scheduler: {enable_query_scheduler}")
        logging.info(f"Adaptive Tiimeout: {adaptive_timeout}")
        logging.info(f"Create All Indexes First: {create_all_indexes_first}")
        logging.info(f"Create Indexes: {create_indexes}")
        logging.info(f"Drop Indexes: {drop_indexes}")
        logging.info(f"Initial Timeout Seconds: {initial_time_out_seconds}")
        logging.info(f"Timeout Interval: {timeout_interval}")
        logging.info(f"Max Rounds: {max_rounds}")
        logging.info(f"Benchmark Name: {benchmark_name}")
        logging.info(f"System: {system}")

        if enable_query_scheduler and create_all_indexes_first:
            raise Exception("enable_query_scheduler and create_all_indexes_first "
                            "cannot be set true at the same time. Consider modifying the config.ini file.")

        if enable_query_scheduler and not create_indexes:
            raise Exception("Enabling enable_query_scheduler requires create_indexes to be set true. "
                            "Consider modifying the config.ini file.")

        if not create_indexes and drop_indexes:
            raise Exception("drop_indexes cannot be se to true while create_indexes is set to false. "
                            "Consider modifying the config.ini file.")

        self.configs = configs
        self.driver = driver
        self.queries = dict(queries)
        self.enable_query_scheduler = enable_query_scheduler
        self.adaptive_timeout = adaptive_timeout
        self.create_all_indexes_first = create_all_indexes_first
        self.drop_indexes = drop_indexes
        self.create_indexes = create_indexes
        self.initial_time_out_seconds = initial_time_out_seconds
        self.max_rounds = max_rounds
        self.timeout_interval = timeout_interval
        self.results_dir = output_dir
        self.table_cardinalities = self.driver.get_table_cardinalities()

        logging.info(f"Results dir: {self.results_dir}")

    def reset_configuration(self, drop_indexes: bool, restart_system: bool = True):
        logging.info("Resetting configuration")

        if drop_indexes:
            self.driver.drop_all_non_pk_indexes()

        # Reset the system configuration
        self.driver.reset_configuration(restart_system=restart_system)

    def get_query_index_dependencies(self, index_configs):
        query_to_index = queries_to_index(self.queries.items(), index_configs)

        return query_to_index

    def sort_query_clusters(self, clusters):
        """
        Sorts the query clusters based on the cost of creating the indexes in that cluster, using dynamic programming.
        @param clusters: The clusters to be sorted
        @return: The sorted clusters
        """
        cluster_indexes = dict()
        index_costs = dict()
        frequencies = defaultdict(int)

        for cluster in clusters:
            index_set = set()

            for index in cluster.get_indexes():
                index_set.add(index)

                if index.get_table_name() in self.table_cardinalities:
                    index_costs[index] = self.table_cardinalities[index.get_table_name()]

            cluster_indexes[cluster.get_cluster_id()] = index_set
            frequencies[cluster.get_cluster_id()] = len(cluster.get_queries())

        if len(clusters) > 1:
            clusters_tmp = list()
            clusters_map = dict([(cluster.get_cluster_id(), cluster) for cluster in clusters])

            ordered_clusters = compute_optimal_order(cluster_indexes.keys(), cluster_indexes, index_costs,
                                                     frequency=None)

            for cluster in ordered_clusters[1]:
                clusters_tmp.append(clusters_map[cluster])

            return clusters_tmp

        return clusters

    def select_configuration(self):
        rounds_ran = 0
        current_timeout = self.initial_time_out_seconds

        # Completed queries per config
        completed_queries = defaultdict(list)

        # Execution time per config
        total_query_execution_time_per_config = defaultdict(float)

        # Completed query execution time per config
        total_completed_query_execution_time_per_config = defaultdict(float)

        # Best Execution Time Seen
        best_execution_time = float("inf")

        # Indexes created per config
        indexes_created_per_config = defaultdict(set)

        completed_configs = []

        if self.results_dir:
            os.makedirs(self.results_dir, exist_ok=True)

        configs = list(self.configs.items())
        configs = sorted(configs, key=lambda x: x[0])

        if len(configs) == 0:
            raise Exception("No configurations were found.")

        start: float = time.time()
        while rounds_ran < self.max_rounds:
            round_results: set = {}

            for current_configuration in configs:
                config_start = time.time()

                # Indexes created in this configuration
                indexes_created = set()

                completed: bool = True
                round_query_execution_time: float = 0.0
                round_completed_query_execution_time: float = 0.0
                round_completed_queries: int = 0
                round_index_creation_time: float = 0.0
                config_id: str = current_configuration[0].split(".json")[0]
                config: Configuration = current_configuration[1]

                # Path to store the results of this configuration
                config_path = f"{self.results_dir}/{config_id}"

                if not os.path.exists(config_path):
                    os.makedirs(config_path, exist_ok=True)

                # Reset Config
                config_reset_time_start = time.time()
                self.reset_configuration(restart_system=False, drop_indexes=self.drop_indexes)
                config_reset_time = time.time() - config_reset_time_start
                logging.debug(f"Resetting config took: {config_reset_time}")

                indexes: QueryToIndex = self.get_query_index_dependencies(config.get_index_commands())

                # Set the system configuration
                reconfiguration_start = time.time()
                self.driver.set_configuration(config.get_configs(), restart=True, reset=True)
                reconfiguration_time = time.time() - reconfiguration_start

                queries_left = [query_id for query_id in self.queries if query_id not in completed_queries[config_id]]

                logging.info(f"Trying config: {config_id}")
                remaining_time = current_timeout

                queries_to_execute = queries_left

                if self.enable_query_scheduler:
                    queries_to_execute = list()
                    clusters: list[QueryCluster] = generate_query_clusters(queries_left, indexes)
                    clusters = self.sort_query_clusters(clusters)

                    for cluster in clusters:
                        queries_to_execute.extend(cluster.get_queries())
                        logging.debug(f"Cluster: {cluster.get_cluster_id()}, #Indexes: {[str(index) for index in cluster.get_indexes()]}, "
                                      f"Queries: {cluster.get_queries()}")

                # Creates all the indexes included in the configuration before query execution
                if self.create_indexes and self.create_all_indexes_first:
                    for query in queries_to_execute:
                        query_indexes = indexes.get_query_indexes(query)
                        for index in query_indexes:
                            if index not in indexes_created:
                                try:
                                    logging.info(f"Creating index: {index}")
                                    index_creation_time_start = time.time()
                                    self.driver.cursor.execute(index.get_create_index_statement())
                                    round_index_creation_time += time.time() - index_creation_time_start
                                    indexes_created_per_config[config_id].add(index)
                                    indexes_created.add(index)
                                except Exception as e:
                                    logging.warning(f"Error creating index: {index}")
                                    logging.warning(f"Error message: {e}")

                # If there is at least one completed configuration, then best_execution_time should be < float('inf')
                # In such a case, we set the current timeout as the best execution time we have seen so far, minus
                # the time spent on query execution in that configuration.
                if best_execution_time < float('inf'):
                    current_timeout = best_execution_time - total_completed_query_execution_time_per_config[config_id]
                    remaining_time = current_timeout
                    logging.info(f"Found best execution time. Setting timeout to {best_execution_time} - "
                                 f"{total_completed_query_execution_time_per_config[config_id]} = {current_timeout}")

                driver_config: dict = self.driver.get_current_global_config();

                round_completed_query_times = dict()

                for query_id in queries_to_execute:
                    query_str = self.queries[query_id]

                    if query_id in completed_queries[config_id]:
                        continue

                    logging.info(f"Running query: {query_id} with timeout: {remaining_time}")

                    # Creates only the indexes associated with the current query
                    if self.create_indexes and not self.create_all_indexes_first:
                        query_indexes = indexes.get_query_indexes(query_id)
                        logging.info(f"Created Indexes: {indexes_created}")
                        logging.info(f"Query Indexes: {len(query_indexes)}")

                        for index in query_indexes:
                            if index not in indexes_created:
                                logging.info(f"Creating index: {index}")
                                index_creation_time_start = time.time()

                                try:
                                    self.driver.get_cursor().execute(index.get_create_index_statement())
                                except Exception as e:
                                    logging.error(e)

                                round_index_creation_time += time.time() - index_creation_time_start
                                indexes_created_per_config[config_id].add(index)
                                indexes_created.add(index)
                            else:
                                pass

                    query_exec_start = time.time()
                    r = self.driver.explain(query_str,
                                            execute=True,
                                            timeout=remaining_time*1000,
                                            results_path=f"{config_path}/{query_id}.json")
                    query_exec_time = time.time() - query_exec_start
                    round_query_execution_time += query_exec_time

                    # Remaining time for the rest of the queries
                    remaining_time -= query_exec_time

                    if remaining_time <= 0 or r["execTime"] == "TIMEOUT":
                        completed = False
                        break

                    round_completed_query_times[query_id] = query_exec_time
                    completed_queries[config_id].append(query_id)
                    round_completed_query_execution_time += query_exec_time
                    total_completed_query_execution_time_per_config[config_id] += query_exec_time
                    round_completed_queries += 1

                total_query_execution_time_per_config[config_id] += round_query_execution_time

                if not completed:
                    logging.info("Config exceeded timeout")
                else:
                    if total_query_execution_time_per_config[config_id] < best_execution_time:
                        best_execution_time = total_query_execution_time_per_config[config_id]

                    logging.info(f"Config {config_id} succeeded!")
                    logging.debug(f"Created Indexes: {len(indexes_created)}, "
                                  f"Total Indexes: {len(config.get_indexes())}")

                    completed_configs.append([config_id, total_query_execution_time_per_config[config_id]])

                report = {
                    "config_id": config_id,
                    "total_query_execution_time": total_query_execution_time_per_config[config_id],
                    "total_completed_query_execution_time": total_completed_query_execution_time_per_config[config_id],
                    "best_execution_time": best_execution_time,
                    "duration_seconds": time.time() - start,
                    "start_time": config_start,
                    "report_ts": time.time(),
                    "round_num_indexes_created": len(indexes_created),
                    "round_index_creation_time": round_index_creation_time,
                    "round_query_execution_time": round_query_execution_time,
                    "round_completed_queries": round_completed_queries,
                    "round_config_reset_time": config_reset_time,
                    "round_reconfiguration_time": reconfiguration_time,
                    "queries_completed_total": len(completed_queries[config_id]),
                    "num_indexes_created_total": len(indexes_created_per_config[config_id]),
                    "num_indexes_total": len(config.get_indexes()),
                    "completed": completed,
                    "timeout": current_timeout,
                    "alpha": self.timeout_interval,
                    "driver_config": driver_config,
                    "lambda_tune_config": list(config.get_configs()),
                    "created_indexes": self.driver.get_all_indexes(),
                    "round_completed_query_times": round_completed_query_times
                }

                round_results[config_id] = report

                reports_output = f"{self.results_dir}/reports.json"

                if os.path.exists(reports_output):
                    with open(reports_output, "r") as f:
                        reports = json.load(f)
                else:
                    reports = []

                reports.append(report)

                with open(reports_output, "w") as f:
                    f.write(json.dumps(reports, indent=2))
                    f.flush()

                logging.info(json.dumps(report, indent=2))

                if self.adaptive_timeout:
                    if current_timeout < round_index_creation_time:
                        current_timeout = round_index_creation_time

                # Always keep the best execution time as the current timeout
                if best_execution_time < float('inf'):
                    current_timeout = best_execution_time

            configs = sorted(configs, key=lambda x: -len(completed_queries[x[0]]))

            logging.info("New config order")
            for cfg_idx in dict(configs):
                throughput = round_completed_queries
                logging.info(f"{cfg_idx}: {throughput}")

            if completed_configs:
                break

            current_timeout *= self.timeout_interval

        completed_configs = sorted(completed_configs, key=lambda x: x[1])

        self.reset_configuration(restart_system=True, drop_indexes=self.drop_indexes)

        # self.evaluate(reports_output)

    def evaluate(self, reports_output):
        logging.info("Evaluating Completed Configurations")

        with open(reports_output, "r") as f:
            reports = json.load(f)

        for report in reports:
            if not report["completed"]:
                continue

            config_id = report["config_id"]
            config = self.configs[config_id]

            print(f"Evaluating Config: {config_id}")

            configs = config.get_configs()
            indexes = config.get_indexes()

            self.reset_configuration(restart_system=False, drop_indexes=self.drop_indexes)
            self.driver.set_configuration(configs, restart=True, reset=True)

            cursor = self.driver.get_cursor()
            if self.create_indexes:
                for index in indexes.values():
                    try:
                        cursor.execute(index)
                    except Exception as e:
                        logging.warning(f"Error creating index: {index}")
                        logging.warning(f"Error message: {e}")

            # Verify config
            for config in configs:
                try:
                    print("Config: " + config)
                    parts = config.split()
                    value = parts[-1]
                    name = parts[-3]
                    cursor.execute(f"SELECT @@{name}")
                    print(f"Actual value {cursor.fetchall()[0]}")
                except Exception as e:
                    print(e)

            start = time.time()
            time_spent = 0
            for query_id in self.queries:
                logging.info(f"Running query {query_id}")
                query_str = self.queries[query_id]
                s = time.time()
                cursor.execute(query_str)
                dur = time.time() - s
                time_spent += dur
                print(f"Took: {dur}")
                print(f"Time spent: {time_spent}")

            end = time.time()

            report["evaluation_time"] = end - start
            report["config"] = list(configs)

            if self.create_indexes:
                report["created_indexes"] = list(indexes)

            with open(reports_output, "w") as f:
                f.write(json.dumps(reports, indent=2))
                f.flush()

        self.reset_configuration(restart_system=True, drop_indexes=self.drop_indexes)

        try:
            cursor.close()
        except Exception as e:
            logging.error(e)

    @staticmethod
    def load_configs(llm_configs_dir, system: str):
        configs_tmp = os.listdir(llm_configs_dir)

        configurations = []  # [(d[0], json.load(open(os.path.join(llm_configs_dir, d[1])))) for d in configurations]

        for d in configs_tmp:
            print(f"Loading: {d}")
            commands = LLMResponse(os.path.join(llm_configs_dir, d)).get_config()

            # TODO: Postgres workaround, remove this
            if system.lower() == "postgres":
                commands_tmp = list()
                for command in commands:
                    if "SET" in command and "ALTER SYSTEM" not in command:
                        command = command.replace("SET", "ALTER SYSTEM SET")
                    commands_tmp.append(command)
                commands = commands_tmp

            configurations.append((d, commands))

        configs = dict(configurations)
        configurations = [(cfg[0], Configuration(config_commands=set(cfg[1]))) for cfg in configs.items()]

        return dict(configurations)
