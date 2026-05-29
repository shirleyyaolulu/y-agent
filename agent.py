import json
from tools import TOOL_DESCRIPTIONS, TOOLS

SYSTEM_PROMPT = f"""
You are an agent.

You can either call a tool or give a final answer. 

{TOOL_DESCRIPTIONS}

When calling a tool, respond ONLY JSON:
{{"tool_name":"tool_name", "args":{{...}}}}

When finished, respond ONLY JSON:
{{"final":"..."}}

"""

def run_agent(user_input, call_llm, max_step=8):
    messages = [
        {"role":"system", "content": SYSTEM_PROMPT},
        {"role":"user", "content": user_input}
    ]

    for step in range(max_step):
        output = call_llm(messages)
        print(f"LLM Output: {output}")

        try:
            response = json.loads(output)
        except json.JSONDecodeError:
            return f"Error: LLM output is not valid JSON. Output: {output}"
        
        if "final" in response:
            return response["final"]
        
        tool_name = response.get("tool_name")
        args = response.get("args", {})

        if tool_name not in TOOLS:
            return f"Unknown tool: {tool_name}."
        else:
            try:
                result = TOOLS[tool_name](args)
            except Exception as e:
                return f"Error occurred while calling tool {tool_name}: {e}"
        
        print(f"Tool Name: {tool_name}, Input: {args}, Output: {result}")

        messages.append({"role":"assistant", "content": output})
        messages.append({
            "role":"user",
            "content": f"Tool result from {tool_name}: {result}"
        })
    return "Stopped: reached max steps"
