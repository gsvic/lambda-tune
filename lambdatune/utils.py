import configparser
import logging

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

def reset_system_indexes():
    driver = get_dbms_driver(system="mysql", db="tpch", user="dbbert", password="dbbert")
    driver.drop_all_non_pk_indexes()
