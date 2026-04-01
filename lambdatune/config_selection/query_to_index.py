from __future__ import annotations

from collections import defaultdict

import re

from lambdatune.config_selection.index import Index


class QueryToIndex:
    def __init__(self):
        self.query_to_index = defaultdict(set)

    def add_index_to_query(self, query: str, create_index_command: str):
        self.query_to_index[query].add(create_index_command)

    def get_query_indexes(self, query: str):
        return self.query_to_index[query]


def queries_to_index(queries: list[str], create_index_commands: list[str]):
    """
    Returns a map from query to the indexes that can be used for that query.
    @param queries: The queries to be executed
    @param create_index_commands: The create index commands
    @return:
    """
    index_map = defaultdict(set)
    query_to_index = QueryToIndex()

    for index in create_index_commands:
        index_name = index.split(" ")[2].strip()
        table_column = index.split("ON ")[1].strip()
        table_name = table_column.split("(")[0].strip()
        column_name = table_column.split("(")[1][:-2].strip()

        index_obj = Index(index_name, table_name, column_name)
        index_map[f"{table_name}.{column_name}"] = index_obj

        for p in list(queries):
            query_id = p[0]
            query_str = p[1]

            if re.search(rf'\b{column_name}\b', query_str) and re.search(rf'\b{table_name}\b', query_str):
                query_to_index.add_index_to_query(query_id, index_obj)

    return query_to_index
