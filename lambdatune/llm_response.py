import json


class LLMResponse:
    def __init__(self, path):
        with open(path) as f:
            data = json.load(f)

            self.prompt = data["prompt"]
            self.response = data["response"]

            # New format: response is already the parsed JSON dict {"commands": [...]}
            # Old format: response is the raw API response with choices[0].message.content
            if self.response and "choices" in self.response:
                self.config = self.response["choices"][0]["message"]["content"]
            else:
                self.config = json.dumps(self.response)

            self.columns_dict = None
            self.tables_dict = None
            self.hidden_table_cols = False

            if "hidden_table_cols" in data:
                self.columns_dict = data["hidden_table_cols"]["columns"]
                self.tables_dict = data["hidden_table_cols"]["tables"]
                self.hidden_table_cols = True

    def has_hidden_table_cols(self):
        return self.hidden_table_cols

    def get_config(self, hide=False):
        config = json.loads(self.config)["commands"]

        if self.has_hidden_table_cols() and not hide:
            for idx, cfg in enumerate(config):
                if "CREATE INDEX" in cfg:
                    tmp = cfg.split("ON")[1]

                    tbl = tmp.split("(")[0].strip()
                    column = tmp.split("(")[1].split(")")[0].strip()

                    real_tbl = self.tables_dict[tbl]
                    real_col = self.columns_dict[column]

                    cfg = cfg.split(" ON ")[0] + f" ON {real_tbl}({real_col});"
                    config[idx] = cfg

        return config
