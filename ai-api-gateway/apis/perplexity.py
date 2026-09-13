import os
import json
from openai import OpenAI


class PerplexityModel:
    def __init__(self):
        self.api_key = os.environ.get("PERPLEXITY_API_KEY")
        with open("apis/config.json") as f:
            self.config = json.load(f)["PERPLEXITY_MODELS"]

    def process_perplexity_model(self, model_name, messages, temperature, max_tokens):
        client = OpenAI(api_key=self.api_key, base_url="https://api.perplexity.ai")

        response = client.chat.completions.create(
            model=self.config[model_name]["name"],
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        content = response.choices[0].message.content
        input_tokens = getattr(response.usage, 'prompt_tokens', 0)
        output_tokens = getattr(response.usage, 'completion_tokens', 0)
        
        return content, input_tokens, output_tokens