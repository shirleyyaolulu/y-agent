from state import state_to_context
from memory import format_memories_for_context
from message_protocal import is_assistant_tool_call, is_tool_message, read_tool_call_group

DEFAULT_MAX_RECENT_CHUNKS = 6



def make_memory_message(memories):
    return {
        "role": "system",
        "content": f"Long-term memories:\n{format_memories_for_context(memories)}"
    }

def make_state_message(state):
    return {
        "role": "system",
        "content": f"Current explicit agent state:\n{state_to_context(state)}"
    }

def make_summary_message(summary):
    if not summary:
        return None
    return {
        "role": "system",
        "content": "Compacted previous context:\n" + summary
    }

def build_protocol_chunks(messages):
    # 返回的是二维的数组，每个元素都是一个chunk，chunk是一个消息列表，包含一个assistant消息和它对应的tool结果消息
    chunks = []
    i = 0 

    while i < len(messages):
        message = messages[i]

        if is_assistant_tool_call(message):
            group, next_index = read_tool_call_group(messages, i)

            if group:
                chunks.append(group)
                i = next_index
                continue
            else:
                i += 1
                continue

        if is_tool_message(message):
            # 如果遇到tool消息但没有对应的assistant消息，说明这是不完整的tool调用结果，直接丢弃
            i += 1
            continue
        chunks.append([message])
        i += 1

    return chunks
    

def select_recent_messages(messages, max_recent_chunks=DEFAULT_MAX_RECENT_CHUNKS):
    history_message = messages[1:]
    chunks = build_protocol_chunks(history_message)
    selected_chunks = chunks[-max_recent_chunks:]
    selected_messages = []
    for chunk in selected_chunks:
        selected_messages.extend(chunk)
    return selected_messages


def build_model_messages(messages, 
                        state, 
                        memories,
                        compacted_summary=None,
                        max_recent_chunks=DEFAULT_MAX_RECENT_CHUNKS):
    system_message = messages[0]

    context_messages = [system_message,
                        make_memory_message(memories),
                        make_state_message(state)
                        ]
    
    summary_message = make_summary_message(compacted_summary)
    if summary_message:
        context_messages.append(summary_message)
    
    recent_messages = select_recent_messages(messages, max_recent_chunks)

    return context_messages + recent_messages
