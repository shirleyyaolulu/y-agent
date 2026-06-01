import json
from tools import tool_error
from tool_registry import TOOL_REGISTRY
from state import update_state_after_tool


def execute_tool_call(tool_call, state, seen_tool_calls):
    tool_name = tool_call.function.name
    raw_args = tool_call.function.arguments or "{}"
    args = {}

    try:
        args = json.loads(raw_args)

    except json.JSONDecodeError:
        result = tool_error(
            f"Tool arguments must be a valid JSON string. Got: {raw_args}",
            error_type="invalid_tool_arguments"
        )
        state = update_state_after_tool(state, tool_name, {}, result)
        return {}, result, state
    
    if not isinstance(args, dict):
        result = tool_error(
            f"Tool arguments must be a JSON object (dictionary). Got: {raw_args}",
            error_type="invalid_tool_arguments"
        )
        state = update_state_after_tool(state, tool_name, {}, result)
        return {}, result, state

    tool_spec = TOOL_REGISTRY.get(tool_name)
    if not tool_spec:
        result = tool_error(
            f"Tool '{tool_name}' is not available.",
            error_type="unknown_tool"
        )
        state = update_state_after_tool(state, tool_name, args, result)
        return args, result, state


    validate_error = validate_args(args, tool_spec.parameters)
    if validate_error:
        result = tool_error(
            f"Invalid arguments for tool '{tool_name}': {validate_error}",
            error_type="invalid_tool_arguments"
        )
        state = update_state_after_tool(state, tool_name, args, result)
        return args, result, state
    
    call_key = (tool_name, json.dumps(args, sort_keys=True, ensure_ascii=False))
    if call_key in seen_tool_calls:
        result = tool_error(
            f"Tool '{tool_name}' has already been called with the same arguments. Skipping to prevent infinite loop.",
            error_type="duplicate_tool_call"
        )
        state = update_state_after_tool(state, tool_name, args, result)
        return args, result, state
    else:
        seen_tool_calls.add(call_key)
        try:
            result = tool_spec.handler(args)
        except Exception as e:
            result = tool_error(
                str(e),
                error_type="tool_runtime_error"
            )
    
    state = update_state_after_tool(state, tool_name, args, result)
    return args, result, state, 


def validate_args(args, schema):
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for name in required:
        if name not in args:
            return f"missing required argument: {name}"

    if schema.get("additionalProperties") is False:
        for name in args:
            if name not in properties:
                return f"unexpected argument: {name}"

    for name, value in args.items():
        expected = properties.get(name, {}).get("type")
        if expected == "string" and not isinstance(value, str):
            return f"{name} must be a string"
        if expected == "integer" and not isinstance(value, int):
            return f"{name} must be an integer"

    return None
