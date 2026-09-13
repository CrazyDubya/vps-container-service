
import json
import os

from monsterapi import client


class MonsterAPI:
    def __init__(self):
        self.api_key = os.environ.get("MONSTER_API_KEY")
        with open("apis/config.json") as f:
            self.config = json.load(f)["MONSTER_MODELS"]

    def process_monster_model(self, model_name, prompt, parameters):
        client_instance = client()

        response = client_instance.get_response(model=self.config[model_name]["name"], data={
            "prompt": prompt,
            **parameters
        })

        process_id = response["process_id"]
        result = client_instance.wait_and_get_result(process_id)

        return result