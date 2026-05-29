import os
import json

from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

def call_llm(messages):
    res = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=messages,
        temperature=0.2,
        max_tokens=512,
    )

    print(f"LLM call with messages: {json.dumps(messages, indent=2)} \n")
    return res.choices[0].message.content