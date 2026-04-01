import configparser
import logging
import os

from pkg_resources import resource_filename
from lambdatune.drivers import PostgresDriver, MySQLDriver


def get_dbms_driver(system, db=None, user=None, password=None):
    """ Get the driver for the specified DBMS """

    config_parser = configparser.ConfigParser()
    f = resource_filename("lambdatune", "resources/config.ini")
    config_parser.read(f)

    if not user:
        user = config_parser[system]["user"] if system in config_parser else None

    if not password:
        password = config_parser[system].get("password") if system in config_parser else None

    if not db:
        db = config_parser["LAMBDA_TUNE"].get("database")

    config_parser = configparser.ConfigParser()
    f = resource_filename("lambdatune", "resources/config.ini")
    config_parser.read(f)

    logging.info(f"Getting DBMS driver for {system} with user {user} and db {db}")

    if system.lower() == "postgres":
        driver = PostgresDriver({
            "user": user,
            "password": password,
            "db": db})
    elif system.lower() == "mysql":
        driver = MySQLDriver({
            "user": user,
            "password": password,
            "db": db})
    else:
        raise Exception(f"Unsupported DBMS: {system}")

    return driver


def get_llm():
    config_parser = configparser.ConfigParser()
    f = resource_filename("lambdatune", "resources/config.ini")
    config_parser.read(f)
    llm = config_parser["LAMBDA_TUNE"]["llm"]

    return llm


def get_openai_key():
    config_parser = configparser.ConfigParser()
    f = resource_filename("lambdatune", "resources/config.ini")
    config_parser.read(f)
    key = config_parser["LAMBDA_TUNE"]["openai_key"]

    return key

def configure_llm():
    """
    Configure LiteLLM API keys from config.ini and environment variables.

    Environment variables take precedence. Supported keys in [LAMBDA_TUNE]:
      openai_key    -> maps to OPENAI_API_KEY  / litellm.openai_key
      anthropic_key -> maps to ANTHROPIC_API_KEY / litellm.anthropic_key

    For Bedrock, use standard AWS environment variables (AWS_ACCESS_KEY_ID, etc.).
    For Ollama, no key is needed — just set llm = ollama/<model>.
    """
    import litellm

    config_parser = configparser.ConfigParser()
    f = resource_filename("lambdatune", "resources/config.ini")
    config_parser.read(f)

    section = config_parser["LAMBDA_TUNE"] if "LAMBDA_TUNE" in config_parser else {}

    openai_key = os.getenv("OPENAI_API_KEY") or section.get("openai_key")
    if openai_key and openai_key != "-":
        litellm.openai_key = openai_key

    anthropic_key = os.getenv("ANTHROPIC_API_KEY") or section.get("anthropic_key")
    if anthropic_key and anthropic_key != "-":
        litellm.anthropic_key = anthropic_key


def reset_system_indexes():
    driver = get_dbms_driver(system="mysql", db="tpch", user="dbbert", password="dbbert")
    driver.drop_all_non_pk_indexes()
