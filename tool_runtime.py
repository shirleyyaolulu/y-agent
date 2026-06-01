import json
from tools import tool_error
from tool_registry import TOOL_REGISTRY
from state import update_state_after_tool
from policy import check_policy, interactive_policy


def execute_tool_call(
        tool_call, 
        state, 
        seen_tool_calls,
        sandbox_policy=None,
        approval_policy=None,
        approval_callback=None,
        ):
    
    default_sandbox_policy, default_approval_policy = interactive_policy()
    if sandbox_policy is None:
        sandbox_policy = default_sandbox_policy
    if approval_policy is None:
        approval_policy = default_approval_policy
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
        decision = check_policy(tool_spec, sandbox_policy, approval_policy)
        if decision.action == "deny":
            result = tool_error(
                f"Policy denied execution of tool '{tool_name}'. Reason: {decision.reason}",
                error_type="policy_denied"
            )
            state = update_state_after_tool(state, tool_name, args, result)
            return args, result, state
        
        if decision.action == "ask":
            if approval_callback is None:
                result = tool_error(
                    f"Tool '{tool_name}' requires approval but no approval callback is provided.",
                    error_type="approval_required"
                )
                state = update_state_after_tool(state, tool_name, args, result)
                return args, result, state
            approved = approval_callback(tool_name, args, decision.reason)
            if not approved:
                result = tool_error(
                    f"Execution of tool '{tool_name}' was not approved by the user. Reason: {decision.reason}",
                    error_type="approval_denied"
                )
                state = update_state_after_tool(state, tool_name, args, result)
                return args, result, state
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
