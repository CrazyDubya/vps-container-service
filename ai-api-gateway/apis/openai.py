import os
import json
from openai import OpenAI


class OpenAIModel:
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        with open("apis/config.json") as f:
            self.config = json.load(f)["OPENAI_MODELS"]

    def process_openai_model(self, model_name, messages, temperature, max_tokens):
        client = OpenAI(api_key=self.api_key)

        response = client.chat.completions.create(
            model=self.config[model_name]["name"],
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        content = response.choices[0].message.content
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        return content, prompt_tokens, completion_tokens