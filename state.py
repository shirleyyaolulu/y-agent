import json 

def create_initial_state(task):
    return {
        "task": task,
        "plan": [],
        "observations": [],
        "notes": [],
        "sources": [],
        "final_answer": None,
        "error": [],
    }




def parse_tool_result(result):
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return {
            "success": False,
            "error": {
                "type": "invalid_tool_result",
                "message": result,
            },
        }

def update_state_after_tool(state, tool_name, args, result):
    parsed = parse_tool_result(result)

    if not parsed.get("success"):
        state["error"].append({
            "tool": tool_name,
            "args": args,
            "error": parsed.get("error", {"type": "unknown_error", "message": result}),
        })
    else: 
        data = parsed.get("data")
        if tool_name == "search_web": 
            state["observations"].append(
                {
                    "type": "search",
                    "query": args.get("query", ""),
                    "result_count": len(data.get("results", [])),
                }
            )
            for item in data.get("results", []):
                state["sources"].append({
                    "title": item.get("title"),
                    "link": item.get("link"),
                    "snippet": item.get("snippet"),
                })
        elif tool_name == "read_url":
            state["observations"].append(
                {
                    "type": "read_url",
                    "url": args.get("url"),
                    "title": data.get("title"),
                    "content_preview": data.get("content", "")[:500],
                }
            )
            state["sources"].append({
                "title": data.get("title"),
                "url": args.get("url", ""),
            })
        elif tool_name == "save_note":
            state["notes"].append(data)
        else:
            state["observations"].append(
                {
                    "type": tool_name,
                    "args": args,
                    "result": data,
                }
            )


    return state

def state_to_context(state):
    return json.dumps(
        {
            "task": state["task"],
            "observations": state["observations"][-5:],
            "sources": state["sources"][-10:],
            "notes": state["notes"][-5:],
            "error": state["error"][-5:],
        }
    )