import time

def get_time(args):
    return time.strftime("%Y-%m-%d %H:%M:%S")

def calculator(args):
    expr = args.get("expression", "")
    return str(eval(expr))

TOOLS = {
    "get_time": get_time,
    "calculator": calculator
}

TOOL_DESCRIPTIONS = {
    "get_time": "Returns the current time in the format YYYY-MM-DD HH:MM:SS.",
    "calculator": "Calculates the mathematical expression provided in the 'expression' argument and returns the result. args: {'expression': '2 + 2'}"
}