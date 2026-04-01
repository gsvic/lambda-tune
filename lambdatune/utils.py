import configparser
import logging
import os

from lambdatune.drivers import PostgresDriver, MySQLDriver

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "config.ini")

# Provider → (model prefix in LiteLLM, default model)
_PROVIDER_CONFIG = {
    "openai":    ("",           "gpt-4o"),
    "anthropic": ("anthropic/", "claude-sonnet-4-6"),
    "ollama":    ("ollama/",    "llama3"),
    "bedrock":   ("bedrock/",   "anthropic.claude-sonnet-4-5"),
}

_llm_override: str = None


def resolve_model(provider: str, model: str = None) -> str:
    """
    Build the full LiteLLM model string from a provider shorthand and optional model name.

    If model already contains '/' it is returned as-is (already fully qualified).

    Examples:
        resolve_model("anthropic")                              -> "anthropic/claude-3-5-sonnet-20241022"
        resolve_model("anthropic", "claude-3-haiku-20240307")  -> "anthropic/claude-3-haiku-20240307"
        resolve_model("openai",    "gpt-4o")                   -> "gpt-4o"
        resolve_model("ollama",    "mistral")                  -> "ollama/mistral"
    """
    if model and "/" in model:
        return model  # already a fully qualified LiteLLM model string

    if provider not in _PROVIDER_CONFIG:
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Supported: {', '.join(_PROVIDER_CONFIG)}"
        )

    prefix, default_model = _PROVIDER_CONFIG[provider]
    return f"{prefix}{model or default_model}"


def set_llm(model: str) -> None:
    """Override the model for this process, taking precedence over config.ini."""
    global _llm_override
    _llm_override = model


def get_dbms_driver(system, db=None, user=None, password=None):
    """ Get the driver for the specified DBMS """

    config_parser = configparser.ConfigParser()
    f = _CONFIG_PATH
    config_parser.read(f)

    if not user:
        user = config_parser[system]["user"] if system in config_parser else None

    if not password:
        password = config_parser[system].get("password") if system in config_parser else None

    if not db:
        db = config_parser["LAMBDA_TUNE"].get("database")

    config_parser = configparser.ConfigParser()
    f = _CONFIG_PATH
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


def get_llm() -> str:
    """Return the active model string. CLI override takes precedence over config.ini."""
    if _llm_override:
        return _llm_override
    config_parser = configparser.ConfigParser()
    f = _CONFIG_PATH
    config_parser.read(f)
    return config_parser["LAMBDA_TUNE"]["llm"]


def get_openai_key():
    config_parser = configparser.ConfigParser()
    f = _CONFIG_PATH
    config_parser.read(f)
    key = config_parser["LAMBDA_TUNE"]["openai_key"]

    return key

def configure_llm(api_key: str = None) -> None:
    """
    Configure LiteLLM API keys.

    Resolution order (highest priority first):
      1. api_key argument (e.g. passed from --api-key CLI flag)
      2. Environment variables (OPENAI_API_KEY, ANTHROPIC_API_KEY, …)
      3. config.ini [LAMBDA_TUNE] openai_key / anthropic_key

    For Bedrock use standard AWS env vars (AWS_ACCESS_KEY_ID, etc.).
    For Ollama no key is needed.
    """
    import litellm

    config_parser = configparser.ConfigParser()
    f = _CONFIG_PATH
    config_parser.read(f)

    section = config_parser["LAMBDA_TUNE"] if "LAMBDA_TUNE" in config_parser else {}

    model = get_llm()
    provider = model.split("/")[0] if "/" in model else "openai"

    if api_key:
        # Route the explicit key to the right provider
        if provider == "anthropic":
            litellm.anthropic_key = api_key
        else:
            litellm.openai_key = api_key
        return

    openai_key = os.getenv("OPENAI_API_KEY") or section.get("openai_key")
    if openai_key and openai_key != "-":
        litellm.openai_key = openai_key

    anthropic_key = os.getenv("ANTHROPIC_API_KEY") or section.get("anthropic_key")
    if anthropic_key and anthropic_key != "-":
        litellm.anthropic_key = anthropic_key


def detect_cpu_cores() -> int:
    """Return the number of logical CPU cores on this machine."""
    return os.cpu_count() or 1


def detect_memory_gb() -> int:
    """Return total physical memory in GB, detected from the OS."""
    # macOS / BSD
    try:
        import subprocess
        mem = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], stderr=subprocess.DEVNULL))
        return max(1, mem // (1024 ** 3))
    except Exception:
        pass
    # Linux
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return max(1, int(line.split()[1]) // (1024 ** 2))
    except Exception:
        pass
    # psutil (optional)
    try:
        import psutil
        return max(1, psutil.virtual_memory().total // (1024 ** 3))
    except ImportError:
        pass
    logging.warning("Could not detect system memory; defaulting to 4 GB.")
    return 4


def reset_system_indexes():
    driver = get_dbms_driver(system="mysql", db="tpch", user="dbbert", password="dbbert")
    driver.drop_all_non_pk_indexes()
