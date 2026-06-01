import json
import time
import uuid 
from pathlib import Path
from context_manager import is_assistant_tool_call, read_tool_call_group


THREADS_DIR = Path("threads")

def now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def thread_path(thread_id):
    return THREADS_DIR / f"{thread_id}.jsonl"

def create_thread():
    thread_id = new_id("th")
    append_item(
        thread_id=thread_id,
        turn_id=None,
        item_type="thread_start",
        data={},

    )
    return thread_id

def append_item(thread_id, turn_id, item_type, data):
    THREADS_DIR.mkdir(exist_ok=True)

    item = {
        "item_id" : new_id("it"),
        "thread_id": thread_id,
        "turn_id": turn_id,
        "type": item_type,
        "data": data,
        "created_at": now(),
    }

    with thread_path(thread_id).open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def load_items(thread_id):
    path = thread_path(thread_id)
    if not path.exists():
        return []
    
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
                else:
                    continue
            except json.JSONDecodeError:
                continue
    return items

def load_thread_messages(thread_id):
    messages = []

    for item in load_items(thread_id):
        if item["type"] in {"user_message", "assistant_message", "tool_result"}:
            message = item["data"].get("message")
            if message:
                messages.append(message)
    return drop_incomplete_tool_call_tail(messages)


def drop_incomplete_tool_call_tail(messages):
    clean = []
    i = 0

    while i < len(messages):
        message = messages[i]
        if is_assistant_tool_call(message):
            group, next_index = read_tool_call_group(messages, i)

            if group is None:
                return clean

            clean.extend(group)
            i = next_index
            continue

        if message.get("role") == "tool":
            # 如果遇到tool消息但没有对应的assistant消息，说明这是不完整的tool调用结果，直接丢弃
            i += 1
            continue

        clean.append(message)
        i += 1
            
    return clean
