import json
import time
from pathlib import Path

MEMORY_DIR = Path("memory")
MEMORY_FILE = MEMORY_DIR / "memories.jsonl"


ALLOWED_MEMORY_TYPES = {
    "preference",
    "profile",
    "project",
    "fact",
}


def save_memory(memory_type, content, metadata=None):
    if memory_type not in ALLOWED_MEMORY_TYPES:
        memory_type = "fact"

    MEMORY_DIR.mkdir(exist_ok=True)


    item = {
        "type": memory_type,
        "content": content, 
        "metadata" : metadata or {},
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
    
    with MEMORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    return item


def load_memories(limit=20): 
    if not MEMORY_FILE.exists():
        return []
    
    memories = []
    with MEMORY_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                memories.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    return memories[-limit:]

def format_memories_for_context(memories):
    if not memories:
        return "No long-term memories found."
    
    lines = []
    for item in memories:
        lines.append(
            f"- [{item['type']}] {item['content']}"
        )

    return "\n".join(lines)


