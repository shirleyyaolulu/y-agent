import os
import json

from openai import OpenAI
from tool_registry  import OPENAI_TOOLS

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

def call_llm(messages):
    res = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=messages,
        tools=OPENAI_TOOLS,
        tool_choice= "auto",
        temperature=0,
    )

    print(f"LLM call with messages: {json.dumps(messages, indent=2)} \n")
    return res.choices[0].message


def call_llm_plain(messages):
    resp = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=messages,
        temperature=0,
    )
    return resp.choices[0].message