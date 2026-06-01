from state import create_initial_state
from memory import load_memories
from thread import create_thread, new_id, load_thread_messages, append_item
from context_manager import build_model_messages
from tool_runtime import execute_tool_call

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

def run_agent(user_input, call_llm, max_step=8, thread_id=None):
    if thread_id == None:
        thread_id = create_thread()
    turn_id = new_id("turn")

    history_message = load_thread_messages(thread_id)


    seen_tool_calls = set()
    state = create_initial_state(user_input)
    
    messages = [
        {"role":"system", "content": SYSTEM_PROMPT},
        ] + history_message + [
        {"role":"user", "content": user_input},
    ]
    # turn start 
    append_item(
        thread_id,
        turn_id,
        "turn_started",
        {"user_input": user_input},
    )

    append_item(
        thread_id,
        turn_id,
        "user_message",
        {"message": {"role": "user", "content": user_input}},
    )

    for step in range(max_step):
        long_term_memories = load_memories()
        model_message = build_model_messages(messages, state, long_term_memories)
        message = call_llm(model_message)
        assistant_message = message.model_dump(exclude_none=True)
        messages.append(assistant_message)

        append_item(
            thread_id,
            turn_id,
            "assistant_message",
            {"message": assistant_message},
        )
        
        print(f"\nAssistant message:\n{message}")

        if not message.tool_calls:
            # No tool calls, we assume the assistant is giving the final answer
            final_answer = message.content or ""
            state["final_answer"] = final_answer
            append_item(
                thread_id,  
                turn_id,
                "final_answer",
                {"answer": final_answer},
            )
            
            append_item(
                thread_id,
                turn_id,
                "turn_finished",
                {"state": state},
            )

            return {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "answer": final_answer,
            }
        
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name

            args, result, state = execute_tool_call(tool_call, state, seen_tool_calls)
            
            print(f"\nTool call: {tool_name}")
            print(f"Args: {args if 'args' in locals() else None}")
            print(f"Result: {result[:1000]}")
            tool_message = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            }
            messages.append(tool_message)
            append_item(
                thread_id,
                turn_id,
                "tool_result",
                {"message": tool_message},
            )

    append_item(
        thread_id,
        turn_id,
        "turn_stopped",
        {"reason": "max_step_reached", "state": state},
    )


    return {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "answer": "Stopped: maximum steps reached without a final answer.",
    }


