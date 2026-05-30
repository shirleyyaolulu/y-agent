from tools import TOOLS
import json
from state import create_initial_state, state_to_context, update_state_after_tool
from memory import load_memories, format_memories_for_context

SYSTEM_PROMPT = f"""
You are a helpful research agent. 

Use tools when you need external information, need to read a URL, or need to save a note.

Do not call tools unnecessarily.

If a tool result is too short, failed, or not enough, decide whether another tool call is needed to get the correct answer.

When you have enough information, answer the user directly.

Use remember_fact only when the user explicitly asks you to remember something for future conversations.
Do not save temporary search results, tool outputs, or ordinary conversation details as long-term memory.

"""

args = {}

def run_agent(user_input, call_llm, max_step=8):
    seen_tool_calls = set()
    state = create_initial_state(user_input)
    
    messages = [
        {"role":"system", "content": SYSTEM_PROMPT},
        {"role":"user", "content": user_input}
    ]

    for step in range(max_step):
        long_term_memories = load_memories()
        model_message = build_model_message(messages, state, long_term_memories)
        message = call_llm(model_message)

        messages.append(message.model_dump(exclude_none=True))
        
        print(f"\nAssistant message:\n{message}")

        if not message.tool_calls:
            # No tool calls, we assume the assistant is giving the final answer
            state["final_answer"] = message.content or ""
            return state["final_answer"]
        
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
                    call_key = (
                        tool_name,
                        json.dumps(args, sort_keys=True, ensure_ascii=False)
                    )
                    if call_key in seen_tool_calls:
                        result = json.dumps({
                            "success": False,
                            "error": {
                                "type": "duplicate_tool_call    ",
                                "message": f"Tool '{tool_name}' with the same arguments has already been called. Use previous observation from state instead of calling again.",
                            },
                        }, ensure_ascii=False)
                    else:
                        seen_tool_calls.add(call_key)
                        result = TOOLS[tool_name](args)

            state = update_state_after_tool(state, tool_name, args, result)
            
            print(f"\nTool call: {tool_name}")
            print(f"Args: {args if 'args' in locals() else None}")
            print(f"Result: {result[:1000]}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    return "Sorry, I couldn't find the answer within the step limit."



def build_model_message(message, state, memories):
    keep_recent = 4
    state_message = {
        "role": "system",
        "content": f"Current explicit agent state:\n{state_to_context(state)}"
    }

    memory_message = {
        "role": "system",
        "content": f"Long-term memories:\n{format_memories_for_context(memories)}"
    }

    recent_messages = message[1:][-keep_recent:]  # Keep recent user and assistant messages
    while recent_messages and is_tool_message(recent_messages[0]):
        recent_messages = recent_messages[1:]

    return [
        message[0],
        memory_message,
        state_message
    ]+recent_messages


def is_tool_message(message):
    return message.get("role") == "tool"


def has_tool_call(message):
    return bool(message.get("tool_calls"))
