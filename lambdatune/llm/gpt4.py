from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
import json
import os

import tiktoken

from lambdatune.utils import get_llm, get_openai_key


encoding = tiktoken.encoding_for_model(get_llm())


def get_response(text: str, temperature: float):
    response = client.chat.completions.create(model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a helpful Database Administrator."},
        {"role": "user", "content": text}
    ],
    temperature=temperature,
    max_tokens=4096)

    return response


def output_format():
    format = """{\n\tcommands: [list of the SQL commands]\n}"""
    return (f"Your response should strictly consist of a python-compatible JSON response of the following schema. "
            f"Do not include any additional text in the prompt, such as descriptions or intros. Return just a"
            f"python-compatible list only."
            f"\n{format}")


def get_config_recommendations_with_compression(dst_system,
                           relations,
                           temperature: float,
                           retrieve_response: bool = False,
                           join_conditions: dict = dict(),
                           system_specs=None,
                           indexes: bool = False,
                           indexes_only: bool = False,
                           hints=None):
    """
    Generate a prompt for the user to provide configuration recommendations for a system. The prompt includes
    @param dst_system: The system for which the recommendations are requested
    @param relations: The relations and their occurrences in the workload
    @param join_conditions: The join conditions and their occurrences in the workload
    @param system_specs: The system specs
    @return: The prompt and the response
    """
    if not indexes_only:
        prompt = (f"Recommend some configuration parameters for {dst_system} to optimize the system's performance. "
                  f"Such parameters might include system-level configurations, like memory, query optimizer "
                  f"hints (such as join strategies, scan costs, parallelism, etc), "
                  f"or query-level configurations.")

        if True:
            prompt += "Include index recommendations (CREATE INDEX)."
        else:
            prompt += "Do not include index recommendations."
    else:
        prompt = "Give me index recommendations for the following input workload. The index names should be unique.\n"

    if relations:
        prompt += f"\nThe relations and their occurrences in the workload are the following:\n"
        for rel in relations:
            prompt += f"{rel}, {relations[rel]}\n"

    if join_conditions:
        prompt += (f"\n\nEach row in the following list has the following format:\n"
                   f"{{a join key A}}:{{all the joins with A in the workload}}.\n\n")

        for cond in join_conditions:
            prompt += f"{cond}: {join_conditions[cond]}\n"

    if system_specs:
        prompt += f"\nThe workload runs on a system with the following specs:"

        for spec in system_specs.items():
            prompt += f"{spec[0]}: {spec[1]}\n"

    if hints:
        prompt += f"Hints: {hints}"

    prompt += "\n" + output_format()

    # print(len(encoding.encode(prompt)))

    print(prompt)

    resp = None

    if retrieve_response:
        resp = get_response(prompt, temperature=temperature)
        resp = json.loads(str(resp))

    # num_tokens = len(encoding.encode(prompt))

    return {
        "prompt": prompt,
        "response": resp
    }

def get_config_recommendations_with_full_queries(dst_system, queries, temperature, retrieve_response: bool = False,
                                      system_specs=None):

    prompt = (f"Recommend some configuration parameters for {dst_system} to optimize the system's performance. "
              f"Such parameters might include system-level configurations, like memory, query optimizer or query-level "
              f"configuration.")

    if True:
        prompt += "Include index recommendations (CREATE INDEX)."
    else:
        prompt += "Do not include index recommendations."

    if queries:
        prompt += f"\nThe queries are the following\n"
        for query in queries:
            prompt += f"{query}\n"

    if system_specs:
        prompt += f"\nThe workload runs on a system with the following specs:"

        for spec in system_specs.items():
            prompt += f"{spec[0]}: {spec[1]}\n"

    prompt += output_format()

    # print(prompt)
    num_tokens = len(encoding.encode(prompt))
    print(num_tokens)

    resp = None

    if retrieve_response:
        resp = get_response(prompt, temperature=temperature)
        resp = json.loads(str(resp))

    # num_tokens = len(encoding.encode(prompt))

    return {
        "prompt": prompt,
        "response": resp
    }


def get_config_recommendations_with_ranked_conditions(dst_system,
                                      retrieve_response: bool = False,
                                      join_conditions=list(),
                                      system_specs=None):

    prompt = (f"Recommend some configuration parameters for {dst_system} to optimize the system's performance. "
              f"Include parameters of the following categories: 1. system-level configurations 2. memory "
              f"3. query optimization and 4. index recommendations (CREATE INDEX). "
              f"Provide a response that consists only from a comma-separated list of individual SQL commands. "
              f"Split the response into multiple lines if needed. ")

    prompt += f"\nThe join conditions are the following:\n"
    for cond in join_conditions:
        prompt += f"{cond}\n"

    if system_specs:
        prompt += f"\nThe workload runs on a system with the following specs:"

        for spec in system_specs.items():
            prompt += f"{spec[0]}: {spec[1]}\n"

    prompt += output_format()

    num_tokens = len(encoding.encode(prompt))

    response = None

    if retrieve_response:
        response = get_response(prompt)
        response = [d.replace("\"", "").replace(",", "") for d in response.split("\n")]

    return {
        "prompt": prompt,
        "response": response,
        "num_tokens": num_tokens,
    }


def get_configs(prompt: str):
    response = get_response(prompt)
    resp = [d.replace("\"", "").replace(",", "") for d in response.split("\n")]

    return resp


def fix_query_plan(old_plan, new_plan, config, system, system_specs):
    prompt = f"""
    Given the following query plan from {system}

    {old_plan}

    The system specs are the following. {system_specs}
    
    The following configuration was set 
    
    {config}
    
    the plan changed as follows:
    
    {new_plan}
    
    The new plan causes a query regression.
    
    Provide list of configurations to fix this regression.
    
    Classify the configurations to the following categories: memory, query planning decisions, indexes.

    The output should be python-compatible JSON.The structure per recommended configuration should be the following:

    {{
        "explanation": briefly explain why the plan changed and the regression causes,
        "configurations": {{
            "category_name": [
                {{
                    "configuration name": "the name"
                    "configuration value": "the exact value only"
                    "needs_restart": "True if the systems needs to restart, False otherwise",
                    "sql command": The SQL command to set that configuration
                }}
            ]
        }}
    }}
    
    Even if the plans are identical, provide some configuration to further improve the performance.

    The output should be strictly only the python compatible JSON response. Do not include any additional text and explanations.
    """

    print(prompt)

    return get_response(prompt)