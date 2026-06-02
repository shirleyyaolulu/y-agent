from state import create_initial_state
from memory import load_memories
from thread import create_thread, new_id, load_thread_messages, append_item
from context_manager import build_model_messages
from tool_runtime import execute_tool_call
import json
from skill_loader import discover_skill_metadata, load_skills
from skill_router import select_skill_name

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

def run_agent(user_input, call_llm, skill_router_llm=None, max_step=8, thread_id=None, sandbox_policy=None, approval_policy=None):
    if thread_id == None:
        thread_id = create_thread()
    turn_id = new_id("turn")

    history_message = load_thread_messages(thread_id)


    seen_tool_calls = set()
    state = create_initial_state(user_input)

    # 1. skill discovery and routing
    active_skill = None
    selected_skill_name = None
    skill_reason = "Skill router not configured"

    try:
        if skill_router_llm is not None:
            skill_metas = discover_skill_metadata()
            selected_skill_name, skill_reason = select_skill_name(
                user_input=user_input, 
                skill_metas=skill_metas, 
                skill_router_llm=skill_router_llm)
            meta_by_name = {meta.name: meta for meta in skill_metas}
            if selected_skill_name in meta_by_name:
                active_skill = load_skills(meta_by_name[selected_skill_name])
    except Exception as e:
        print(f"Error during skill routing: {e}")
        selected_skill_name = None
        skill_reason = f"Error during skill routing: {e}"
                                                                  

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

    append_item(
        thread_id,
        turn_id,
        "skill_selection",
        {
            "selected": selected_skill_name,
            "reason": skill_reason,
            "skill": (
                {
                    "name": active_skill.name,
                    "description": active_skill.description,
                    "path": active_skill.path,
                }
            ) if active_skill else None,
        },
    )

    for step in range(max_step):
        long_term_memories = load_memories()
        model_message = build_model_messages(
            messages=messages, 
            state=state,
            memories=long_term_memories,
            skill=active_skill)
        
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

            args, result, state = execute_tool_call(
                tool_call=tool_call, 
                state=state, 
                seen_tool_calls=seen_tool_calls,
                sandbox_policy=sandbox_policy,
                approval_policy=approval_policy,
                approval_callback=ask_user_approval
            )
            
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


def ask_user_approval(tool_name, args, reason):
    print("\nApproval required")
    print(f"Tool: {tool_name}")
    print(f"Reason: {reason}")
    print("Args:")
    print(json.dumps(args, ensure_ascii=False, indent=2))
    
    try:
        answer = input("Approve this tool call? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}
