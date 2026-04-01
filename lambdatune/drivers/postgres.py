import json
import logging
import os.path

import psycopg2
import time

import platform

from collections import defaultdict

from lambdatune import plan_utils
from .driver import Driver


class PostgresPlan:
    def __init__(self, plan_json):
        self.info = plan_json

        self.actual_time = self.info["plan"]["Actual Total Time"] if "Actual Total Time" in self.info["plan"] else None
        self.indexes = self.get_indexes()
        self.scans = plan_utils.extract_scans_from_plan(plan_json["plan"])

    def get_actual_time(self):
        return self.actual_time

    def get_indexes(self):
        return plan_utils.extract_indices_from_plan(self.info["plan"])

    def get_nodes_flat(self, plan):
        nodes = list()

        cost = plan["Actual Total Time"]
        node = {"type": plan["Node Type"]}

        if "Plans" in plan:
            children = plan["Plans"]
            node["children"] = children

            for child in children:
                cost -= child["Actual Total Time"]
                nodes.extend(self.get_nodes_flat(child))

        node["cost"] = cost
        nodes.append(node)

        return nodes


class PostgresDriver(Driver):
    def __init__(self, conf):
        self.config = conf

        c = 0

        while True:
            try:
                if "password" in self.config:
                    self.conn = psycopg2.connect(database=self.config["db"], user=self.config["user"],
                        password=self.config["password"]
                    )
                else:
                    self.conn = psycopg2.connect("dbname='%s' user='%s'" % (self.config["db"], self.config["user"]))
                break
            except Exception as e:
                c += 1

                if c > 3:
                    raise e

                logging.error(e)

                time.sleep(10)

        self.cursor = self.conn.cursor()
        self.cursor.connection.autocommit = True
        self.cursor.connection.autocommit = True

    def get_cursor(self):
        return self.cursor

    def enable_index(self, index_name):
        self.cursor.execute("UPDATE pg_index SET indisvalid = TRUE WHERE indexrelid = '{}'::regclass;".format(index_name))

    def enable_indexes(self, index_set):
        for index in index_set:
            print("Enabling index: {}".format(index))
            self.enable_index(index)

        print("Enabled {} indexes.".format(len(index_set)))

    def enable_all_indexes(self):
        self.enable_indexes(self.get_all_indexes_full())

    def disable_index(self, index_name):
        print("Disabling index {}".format(index_name))
        self.cursor.execute(
            "UPDATE pg_index SET indisvalid = FALSE WHERE indexrelid = '{}'::regclass;".format(index_name))

    def disable_indexes(self, index_set):
        for index_name in index_set:
            self.disable_index(index_name)

    def explain(self, query, execute=True, analyze=False, explain_json=False, config=None, results_path=None,
                timeout: int=None):

        cursor = self.conn.cursor()

        if config:
            for conf in config:
                print(f"Setting config: {conf}")
                cursor.execute(conf)


        explain_cmd = "EXPLAIN "

        if explain_json:
            explain_cmd += "(FORMAT JSON)"

        explain_cmd = f"{explain_cmd} {query}"
        cursor.execute(explain_cmd)
        plan = cursor.fetchall()

        if not explain_json:
            try:
                plan = '\n'.join([d[0] for d in plan])
            except Exception as e:
                logging.warning(e)
                plan = None
        else:
            try:
                plan = plan[0][0][0]
            except Exception as e:
                logging.warning(f"Failed to parse plan with error: {e}")

        explain_cmd = f"EXPLAIN "

        if analyze or explain_json:
            explain_cmd += "( "

            if analyze:
                explain_cmd += "ANALYZE"

            if explain_json:
                if explain_cmd[-2:] != "( ":
                    explain_cmd += ", "
                explain_cmd += "FORMAT JSON"

            explain_cmd += " )"

        duration = None

        if execute:
            start = time.time()

            if timeout:
                cursor.execute(f"SET statement_timeout={timeout}")

            try:
                if analyze:
                    explain_cmd = f"{explain_cmd} {query}"
                    cursor.execute(explain_cmd)

                    if explain_json:
                        plan = cursor.fetchall()[0][0][0]
                    else:
                        plan = cursor.fetchall()
                        plan = '\n'.join([d[0] for d in plan])
                else:
                    cursor.execute(query)

                duration = (time.time() - start) * 1_000
            except Exception as e:
                duration = "TIMEOUT"

        if timeout:
            try:
                cursor.execute(f"RESET statement_timeout")
            except Exception as e:
                logging.warning(f"Failed to reset statement_timeout: {e}")

        out = {
            "execTime": duration,
            "config": config,
            "plan": plan
        }

        if results_path:
            json.dump(out, open(results_path, "w+"), indent=2)

        cursor.close()

        return out

    def explain_json(self, query, analyze=False, verbose=False, config=None, dump_path=None):
        if config:
            for conf in config:
                self.cursor.execute("SET {} = '{}'".format(conf, config[conf]))

        explain_cmd = "EXPLAIN ( FORMAT JSON "

        if analyze:
            explain_cmd += ", ANALYZE"

        if verbose:
            explain_cmd += ", VERBOSE"

        explain_cmd += " ) "

        self.cursor.execute("{} {}".format(explain_cmd, query))

        plan = self.cursor.fetchall()[0][0][0]["Plan"]

        if config:
            print("Resetting config")
            self.cursor.execute("RESET ALL;")

        actual_total_time = None

        if analyze:
            actual_total_time = plan["Actual Total Time"]

        out = {
            "execTime": actual_total_time,
            "config": config,
            "plan": plan
        }

        if dump_path:
            json.dump(out, open(dump_path, "w+"), indent=2)

        return out

    def get_all_indexes_full(self):
        self.cursor.execute("""
        SELECT
            indexname
        FROM
            pg_indexes
        WHERE
            schemaname = 'public'
        ORDER BY
            tablename,
            indexname;
        """)

        indexes = [d[0] for d in self.cursor.fetchall()]

        return indexes

    def drop_all_non_pk_indexes(self):
        indexes = self.get_all_indexes()

        for index in indexes:
            logging.info(f"Dropping index: {index}")
            self.cursor.execute(f"DROP INDEX {index}")

    def get_all_indexes(self):
        self.cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename NOT LIKE 'pg%'")

        indexes = [d[0] for d in self.cursor.fetchall()]
        indexes = [d for d in indexes if not d.endswith("_pkey")]

        return indexes

    def get_plan(self, query, analyze=False, verbose=False, config=None, dump_path=None):
        plan_json = self.explain_json(query, analyze, verbose, config, dump_path)

        return PostgresPlan(plan_json)

    def reset_configuration(self, restart_system=True):
        self.conn.autocommit = True
        self.cursor.execute("ALTER SYSTEM RESET ALL;")

        if restart_system:
            PostgresDriver.restart_system()

        self.__init__(self.config)

    def get_db_schema(self) -> dict:
        self.cursor.execute("""
            SELECT 
                table_name,
                column_name
            FROM 
                information_schema.columns
            WHERE
                table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY 
                table_schema, table_name, ordinal_position;
        """)

        tuples = self.cursor.fetchall()

        schema = defaultdict(list)

        for tuple in tuples:
            table = tuple[0]
            col = tuple[1]

            schema[table].append(col)

        return schema
    def get_table_cardinalities(self) -> dict:
        self.cursor.execute("ANALYZE")

        self.cursor.execute("""
        SELECT relname, n_live_tup 
        FROM pg_stat_user_tables;
        """)

        r = self.cursor.fetchall()

        return dict(r)

    def inject_num_rows(self, table, num_rows):
        query = f"""
        UPDATE pg_class
        SET reltuples = {num_rows}
        WHERE oid = '{table}'::regclass;
        """

        self.cursor.execute(query)

    def inject_num_distinct_values(self, table, att_name, num_distinct_values):
        query = f"""
        UPDATE pg_statistic
        SET stadistinct = {num_distinct_values}
        FROM pg_class c, pg_attribute a
        WHERE c.oid = pg_statistic.starelid
        AND a.attnum = pg_statistic.staattnum
        AND a.attrelid = c.oid
        AND c.relname = '{table}'
        AND a.attname = '{att_name}';
        """

        self.cursor.execute(query)

    def get_num_distinct_values(self, table, att_name):
        query = f"""
        SELECT stadistinct
        FROM pg_statistic ps, pg_class c, pg_attribute a
        WHERE c.oid = ps.starelid
        AND a.attnum = ps.staattnum
        AND a.attrelid = c.oid
        AND c.relname = '{table}'
        AND a.attname = '{att_name}';
        """

        self.cursor.execute(query)

        return self.cursor.fetchall()[0][0]

    def get_tables_num_rows(self):
        query = """
        SELECT
            relname,
            reltuples
        FROM
            pg_class
        WHERE
            relkind = 'r'
        AND relname NOT LIKE 'pg_%'
        AND relname NOT LIKE 'sql_%'
        ORDER BY
            relname;
        """

        self.cursor.execute(query)

        return dict(self.cursor.fetchall())

    def reduce_num_distinct_values(self, table, attr, perc):
        assert 0.0 <= perc <= 1.0

        num_distinct_values = self.get_num_distinct_values(table, attr)
        reduced_num_distinct_values = num_distinct_values * perc

        print(f"Reducing distinct values from {num_distinct_values} to {reduced_num_distinct_values}")

        self.inject_num_distinct_values(table, attr, reduced_num_distinct_values)

    def set_configuration(self, config, restart=True, reset=False):
        self.conn.rollback()
        self.conn.autocommit = True
        if config:
            if reset:
                logging.info("Resetting Postgres")
                self.cursor.execute("ALTER SYSTEM RESET ALL;")

            for cf in config:
                try:
                    logging.info("Setting config: " + cf)
                    self.cursor.execute(cf)
                except Exception as e:
                    print(e)

        if restart:
            PostgresDriver.restart_system()
            logging.info("waiting 5 secs...")
            time.sleep(5)
            self.__init__(self.config)

    def get_current_global_config(self):
        """
        Retrieves the current configuration in JSON format
        :return:
        """
        self.cursor.execute("SHOW ALL")

        result = self.cursor.fetchall()
        result = dict([(tuple[0], tuple[1]) for tuple in result])

        return result

    @staticmethod
    def restart_system():
        if platform.system() == "Darwin":
            restart_cmd = "brew services restart postgresql"
        elif platform.system() == "Linux":
            restart_cmd = "echo dbbert | sudo -S service postgresql restart"
        else:
            raise Exception(f"System {platform.system()} is not supported.")
        logging.info("Restarting Postgres")
        p = os.popen(restart_cmd).read()
        logging.info("Done!")