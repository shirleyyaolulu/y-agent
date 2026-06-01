def has_tool_call(message):
    return bool(message.get("tool_calls"))


def is_tool_message(message):
    return message.get("role") == "tool"


def is_assistant_tool_call(message):
    return message.get("role") == "assistant" and has_tool_call(message)


def expected_tool_call_ids(message):
    return [tool_call["id"] for tool_call in message.get("tool_calls", [])]


def read_tool_call_group(messages, start_index):
    message = messages[start_index]

    if not is_assistant_tool_call(message):
        return None, start_index

    group = [message]
    next_index = start_index + 1

    for tool_call_id in expected_tool_call_ids(message):
        if next_index >= len(messages):
            return None, start_index + 1

        tool_message = messages[next_index]
        if (
            not is_tool_message(tool_message)
            or tool_message.get("tool_call_id") != tool_call_id
        ):
            return None, start_index + 1

        group.append(tool_message)
        next_index += 1

    return group, next_index