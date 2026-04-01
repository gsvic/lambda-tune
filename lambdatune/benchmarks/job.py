import os

_QUERY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "queries", "job")


def get_job_queries():
    query_files = os.listdir(_QUERY_DIR)
    query_files = sorted(query_files, key=lambda x: (int(x.split(".sql")[0][:-1]), x.split(".sql")[0][-1]))

    queries = [(f.split(".sql")[0], open(os.path.join(_QUERY_DIR, f)).read()) for f in query_files]

    return queries