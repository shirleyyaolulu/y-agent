# 第六部分：Tool Registry and Tool Runtime

前面几部分已经把 Agent 的主流程搭起来了：

```text
用户输入
-> LLM 判断是否需要工具
-> Python 执行工具
-> tool result 回传给 LLM
-> LLM 继续判断或给最终答案
```

第六部分的重点是：

```text
不要把“工具定义”和“工具执行细节”都塞在 agent.py 里。
```

这一步开始，Agent 的结构更清楚：

```text
tool_registry.py = 工具目录：有哪些工具，每个工具长什么样
tool_runtime.py  = 工具运行时：一次 tool_call 到底怎么安全执行
agent.py         = 主循环：什么时候调 LLM，什么时候调工具，什么时候结束
```

一句话总结：

```text
Tool Registry 负责“登记工具”。
Tool Runtime 负责“安全执行工具”。
Agent Loop 只负责“编排流程”。
```

## 1. 为什么要拆 Tool Registry

之前工具相关逻辑容易散在几个地方：

```text
给 LLM 看的工具 schema
Python 真正执行的函数 map
参数校验规则
工具描述
```

如果这些信息分散维护，很容易出现一个问题：

```text
LLM 看到的工具名 / 参数
和 Python 实际能执行的工具名 / 参数
不一致
```

所以 `tool_registry.py` 把一个工具需要的信息集中放在 `ToolSpec` 里：

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: callable
```

这四个字段分别对应：

| 字段 | 含义 | 谁使用 |
|---|---|---|
| `name` | 工具名字 | LLM 和 Python 都用 |
| `description` | 什么时候该用这个工具 | LLM 用 |
| `parameters` | 工具参数 schema | LLM 和 runtime 都用 |
| `handler` | 真正执行的 Python 函数 | runtime 用 |

这里最重要的是：

```text
一个 ToolSpec 同时服务两个方向：
1. 生成 OPENAI_TOOLS，告诉模型有哪些工具
2. 生成 TOOL_REGISTRY，让 Python 找到真实 handler
```

## 2. OPENAI_TOOLS 和 TOOL_REGISTRY 的区别

当前 `tool_registry.py` 里有两个核心产物：

```python
TOOL_REGISTRY = {tool.name: tool for tool in TOOL_SPECS}
```

以及：

```python
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": tool_spec.name,
            "description": tool_spec.description,
            "parameters": tool_spec.parameters,
        },
    }
    for tool_spec in TOOL_SPECS
]
```

它们不是一回事：

| 名字 | 作用 | 给谁看 |
|---|---|---|
| `OPENAI_TOOLS` | 工具说明书 | 给 LLM API 看 |
| `TOOL_REGISTRY` | 工具执行表 | 给 Python runtime 看 |

可以这样理解：

```text
OPENAI_TOOLS:
告诉模型：“你可以调用 calculator，它需要 expression 参数。”

TOOL_REGISTRY:
告诉 Python：“如果模型调用 calculator，就执行 tools.calculator(args)。”
```

所以这两个东西必须来自同一份 `TOOL_SPECS`。

这样做的好处是：

```text
新增工具时，只需要加一个 ToolSpec。
模型可见的 schema 和 Python 可执行的 handler 会一起更新。
```

## 3. Tool Runtime 解决什么问题

`tool_runtime.py` 负责处理一次真实的工具调用：

```python
args, result, state = execute_tool_call(tool_call, state, seen_tool_calls)
```

它的输入是：

| 输入 | 含义 |
|---|---|
| `tool_call` | LLM 返回的结构化工具调用 |
| `state` | Agent 当前工作状态 |
| `seen_tool_calls` | 本轮已经执行过的工具调用，用来防重复 |

它的输出是：

| 输出 | 含义 |
|---|---|
| `args` | 解析后的工具参数 |
| `result` | 工具执行结果，JSON 字符串 |
| `state` | 更新后的 Agent 状态 |

这一步把原来 `agent.py` 里的复杂逻辑收进一个函数里。

`agent.py` 就可以变得更像主流程：

```python
for tool_call in message.tool_calls:
    args, result, state = execute_tool_call(tool_call, state, seen_tool_calls)
    tool_message = {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": result,
    }
    messages.append(tool_message)
```

也就是说：

```text
agent.py 不关心工具怎么校验、怎么查表、怎么防重复。
agent.py 只关心：执行完以后，把 tool result 放回 messages。
```

## 4. Tool Runtime 的正确执行顺序

一次工具调用不能直接执行。

正确顺序应该是：

```text
1. 从 tool_call 里取工具名
2. 解析 arguments JSON
3. 确认 arguments 是 dict
4. 从 TOOL_REGISTRY 查工具
5. 根据 schema 校验参数
6. 检查是否重复调用
7. 执行真实 handler
8. 捕获 handler 异常
9. 更新 state
10. 返回 args / result / state
```

对应当前代码里的核心路径：

```python
tool_name = tool_call.function.name
raw_args = tool_call.function.arguments or "{}"
args = json.loads(raw_args)
tool_spec = TOOL_REGISTRY.get(tool_name)
validate_error = validate_args(args, tool_spec.parameters)
result = tool_spec.handler(args)
state = update_state_after_tool(state, tool_name, args, result)
```

这里最容易忽略的是：

```text
每一个错误分支都应该 early return。
```

例如参数 JSON 解析失败：

```python
except json.JSONDecodeError:
    result = tool_error(...)
    state = update_state_after_tool(state, tool_name, {}, result)
    return {}, result, state
```

如果没有 `return`，代码会继续往下跑，可能导致：

```text
明明参数已经非法，后面还是执行了真实工具
明明 tool_spec 是 None，后面还访问 tool_spec.parameters
```

## 5. 这次 bug 说明了什么

你这次遇到的错误是：

```text
TypeError: 'ChatCompletionMessageFunctionToolCall' object is not subscriptable
```

原因是写成了：

```python
tool_name = tool_call["name"]
```

但当前 SDK 返回的 `tool_call` 是对象，不是 dict。

正确写法是：

```python
tool_name = tool_call.function.name
```

这个 bug 很有代表性，它说明：

```text
tool_call 是模型返回的协议对象。
runtime 必须按照 SDK 的真实结构读取它。
```

对当前项目来说：

```text
工具名：tool_call.function.name
参数字符串：tool_call.function.arguments
工具调用 id：tool_call.id
```

其中 `tool_call.id` 不在 runtime 里处理。

它由 `agent.py` 用来生成 tool message：

```python
{
    "role": "tool",
    "tool_call_id": tool_call.id,
    "content": result,
}
```

## 6. validate_args 的作用

`validate_args(args, schema)` 是 runtime 的安全门。

它不负责理解业务逻辑，只做最基础的 schema 检查：

```text
required 参数是否存在
是否出现不允许的额外参数
参数类型是否正确
```

例如 `calculator` 的 schema 是：

```python
{
    "type": "object",
    "properties": {
        "expression": {"type": "string"}
    },
    "required": ["expression"],
    "additionalProperties": False,
}
```

所以这些参数是非法的：

```python
{}                         # 缺少 expression
{"expression": 123}        # expression 不是 string
{"expression": "1+1", "x": 1}  # 有额外参数 x
```

validate 失败后要返回错误结果，而不是继续执行 handler：

```python
if validate_error:
    result = tool_error(...)
    state = update_state_after_tool(state, tool_name, args, result)
    return args, result, state
```

## 7. seen_tool_calls 的作用

Agent 很容易陷入这种循环：

```text
LLM: 调用 search_web({"query": "LangGraph"})
Python: 返回结果
LLM: 又调用 search_web({"query": "LangGraph"})
Python: 又返回结果
...
```

所以 runtime 用 `seen_tool_calls` 防止同一轮里重复执行同一个工具请求：

```python
call_key = (
    tool_name,
    json.dumps(args, sort_keys=True, ensure_ascii=False),
)
```

如果同一个 `tool_name + args` 已经执行过，就返回错误：

```python
error_type="duplicate_tool_call"
```

这个错误会进入 state，下一轮 LLM 可以看到：

```text
这个工具调用已经重复了，不要继续调用，应该基于已有 observation 回答。
```

## 8. update_state_after_tool 为什么也要配合改

runtime 返回的工具结果统一是 JSON 字符串：

```python
result = tool_error(...)
result = tool_spec.handler(args)
```

`state.py` 需要把这个 result 解析后写进 state。

成功时：

```text
search_web -> 写 observations 和 sources
read_url   -> 写 observations 和 sources
save_note  -> 写 notes
其他工具   -> 写 observations
```

失败时：

```text
写入 state["error"]
```

这次你已经把 `update_state_after_tool` 改成兼容两种错误格式：

```python
error = parsed.get("error")
if not error:
    error = {
        "type": parsed.get("error_type", "unknown_error"),
        "message": parsed.get("message", result),
    }
```

这个修改很重要。

因为 `tools.tool_error()` 返回的是：

```json
{"success": false, "error_type": "...", "message": "..."}
```

如果 state 只认识：

```json
{"success": false, "error": {"type": "...", "message": "..."}}
```

那错误就会被记成 `unknown_error`。

## 9. 当前第六部分的边界

现在每个文件的职责应该这样记：

| 文件 | 职责 |
|---|---|
| `tools.py` | 真实工具函数，比如 calculator/search/read_url |
| `tool_registry.py` | 登记工具，生成 `OPENAI_TOOLS` 和 `TOOL_REGISTRY` |
| `tool_runtime.py` | 安全执行一次 tool_call |
| `agent.py` | 控制 Agent loop，把 tool result 放回 messages |
| `state.py` | 把工具结果整理成 Agent 可用的结构化状态 |
| `llm.py` | 调 LLM，并把 `OPENAI_TOOLS` 传给模型 |

最关键的分界线是：

```text
tool_registry.py 不执行工具。
tool_runtime.py 不决定什么时候调用 LLM。
agent.py 不手写每个工具的执行细节。
```

## 10. 新增一个工具时要改哪里

现在新增工具的标准流程应该是：

```text
1. 在 tools.py 写真实函数
2. 在 tool_registry.py 增加一个 ToolSpec
3. 确认 parameters schema 正确
4. 运行一次实际调用或最小测试
```

例如新增 `weather` 工具时，应该加：

```python
ToolSpec(
    name="weather",
    description="Get weather information for a city.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string"},
        },
        "required": ["city"],
        "additionalProperties": False,
    },
    handler=weather,
)
```

不需要再手动改 `OPENAI_TOOLS`。

也不需要在 `agent.py` 里加：

```python
if tool_name == "weather":
    ...
```

因为 runtime 会从 `TOOL_REGISTRY` 自动找到 handler。

## 11. 自检清单

第六部分学完后，你应该能回答这些问题：

1. `OPENAI_TOOLS` 和 `TOOL_REGISTRY` 有什么区别？
2. 为什么它们都应该从同一份 `TOOL_SPECS` 生成？
3. `tool_call.function.name`、`tool_call.function.arguments`、`tool_call.id` 分别用在哪里？
4. 为什么工具参数 JSON 解析失败后必须 early return？
5. 为什么 validate 失败后不能继续执行 handler？
6. `seen_tool_calls` 防止的是什么问题？
7. `tool_runtime.py` 和 `agent.py` 的边界是什么？
8. `update_state_after_tool` 为什么要理解 tool error 的格式？

参考答案：

1. `OPENAI_TOOLS` 给模型看，`TOOL_REGISTRY` 给 Python 执行用。
2. 防止模型看到的 schema 和 Python 实际执行的工具不一致。
3. `function.name` 用来查工具，`function.arguments` 用来解析参数，`id` 用来生成 `role="tool"` 消息里的 `tool_call_id`。
4. 因为参数已经不可信，继续往下会导致错误工具执行或异常。
5. 因为 validate 是执行前的安全门，失败就说明 handler 不应该收到这组参数。
6. 防止 LLM 在同一轮里重复调用相同工具和相同参数，造成循环。
7. runtime 负责一次工具调用的安全执行；agent 负责整体 loop 和消息协议。
8. 因为工具失败也要进入 state，让 LLM 下一轮知道发生了什么错误。

## 12. 一句话背诵版

```text
第六部分是在把工具系统工程化：
Tool Registry 统一登记工具，
Tool Runtime 统一执行和防御，
Agent Loop 只保留编排逻辑。
```

