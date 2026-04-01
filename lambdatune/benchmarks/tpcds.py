import os

_QUERY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "queries", "tpcds")


def get_tpcds_queries():
    query_files = os.listdir(_QUERY_DIR)

    queries = [(d.replace(".sql", ""), open(os.path.join(_QUERY_DIR, d)).read()) for d in query_files]
    queries = sorted(queries, key=lambda k: k[0])

    return queries