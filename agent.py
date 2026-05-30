from tools import TOOLS
import json

SYSTEM_PROMPT = f"""
You are a helpful research agent. 

Use tools when you need external information, need to read a URL, or need to save a note.

Do not call tools unnecessarily.

If a tool result is too short, failed, or not enough, decide whether another tool call is needed to get the correct answer.

When you have enough information, answer the user directly.

"""

def run_agent(user_input, call_llm, max_step=8):
    messages = [
        {"role":"system", "content": SYSTEM_PROMPT},
        {"role":"user", "content": user_input}
    ]

    for step in range(max_step):
        message = call_llm(messages)

        messages.append(message.model_dump(exclude_none=True))
        
        print(f"\nAssistant message:\n{message}")

        if not message.tool_calls:
            # No tool calls, we assume the assistant is giving the final answer
            return message.content or ""
        
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name

            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                result = json.dumps({
                    "success": False,
                    "error": {
                        "type": "invalid_tool_arguments",
                        "message": tool_call.function.arguments,
                    },
                }, ensure_ascii=False)
            else:
                if tool_name not in TOOLS:
                    result = json.dumps({
                        "success": False,
                        "error": {
                            "type": "tool_not_found",
                            "message": f"Tool '{tool_name}' is not available.",
                        },
                    }, ensure_ascii=False)  
                else:
                    result = TOOLS[tool_name](args)
            
            print(f"\nTool call: {tool_name}")
            print(f"Args: {args if 'args' in locals() else None}")
            print(f"Result: {result[:1000]}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    return "Sorry, I couldn't find the answer within the step limit."
