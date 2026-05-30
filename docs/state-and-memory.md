# 第三部分：State and Memory

前两部分已经解决了一个核心问题：

```text
LLM 如何表达“我要调用工具”？
Python 如何真正执行工具？
```

第三部分开始，重点变成：

```text
工具执行完以后，Agent 应该记住什么？
下一轮 LLM 应该基于哪些信息继续判断？
怎样避免重复调用、上下文越来越长、结果丢失？
```

一句话总结：

```text
前两部分让 Agent 会调用工具。
第三部分让 Agent 会整理和使用自己的工作记忆。
```

## 1. 和前两部分的对比

```text
第一部分：最小 Agent Loop
LLM 在 content 里输出 JSON，Python 解析 JSON 后调用工具。

第二部分：正式 Tool Calling
LLM 在 message.tool_calls 里返回结构化工具调用，Python 执行工具，再用 role=tool 回传结果。

第三部分：State / Memory
Python 不只是把 messages 越堆越长，而是额外维护一个结构化 state。
```

核心变化：

```text
messages = 对话历史，主要是给 LLM API 看的协议上下文
state    = Agent 自己维护的结构化记忆
```

前两部分里，状态基本等于 `messages`：

```python
messages.append(message.model_dump(exclude_none=True))
messages.append({
    "role": "tool",
    "tool_call_id": tool_call.id,
    "content": result,
})
```

第三部分开始，多了一个显式状态对象：

```python
state = create_intial_state(user_input)
```

这一步的含义是：Agent 不再只依赖聊天记录，而是开始自己整理任务过程。

## 2. State 里应该放什么

当前 `state.py` 里的初始状态是：

```python
{
    "task": task,
    "plan": [],
    "observations": [],
    "notes": [],
    "sources": [],
    "final_answer": None,
    "error": [],
}
```

每个字段可以这样理解：

| 字段 | 作用 |
| --- | --- |
| `task` | 用户最初的问题 |
| `plan` | Agent 的计划，当前还没有真正使用 |
| `observations` | 工具执行后得到的事实观察 |
| `notes` | 用户或 Agent 保存下来的笔记 |
| `sources` | 搜索或网页读取得到的来源 |
| `final_answer` | 最终答案 |
| `error` | 工具调用失败、参数错误、重复调用等问题 |

重点：`state` 不是把所有消息复制一遍，而是把工具结果变成更容易复用的结构化信息。

## 3. 工具结果如何进入 State

第三部分最关键的代码是：

```python
state = update_state_after_tool(state, tool_name, args, result)
```

它发生在工具执行之后：

```text
LLM returns tool_calls
-> Python executes tool
-> result
-> update_state_after_tool
-> append tool message
-> next LLM call
```

也就是说，工具结果会走两条路：

```text
1. 放进 messages
   让正式 tool calling 协议可以继续工作。

2. 放进 state
   让 Agent 自己记住重要信息。
```

这两条路都需要。只放 `messages`，上下文会越来越长；只放 `state`，正式 tool calling 协议又不完整。

## 4. State 不是 Memory 的全部

这里的 memory 不是数据库，也不是长期记忆系统。当前项目里的 memory 更准确地说是：

```text
单次任务执行过程中的工作记忆
```

它只在这次 `run_agent(...)` 执行期间存在。程序结束后，这个 `state` 就没了。

所以当前阶段不要把 memory 想复杂。先掌握三件事：

```text
1. 记录工具结果
2. 压缩上下文
3. 避免重复调用
```

## 5. 为什么还要 build_model_message

LLM 不会自动看到 Python 里的 `state`。

即使你写了：

```python
state["observations"].append(...)
```

模型本身也不知道。你必须把 state 转成消息，再发给模型：

```python
state_message = {
    "role": "system",
    "content": f"Current explicit agent state:\n{state_to_context(state)}"
}
```

所以第三部分多了：

```python
model_message = build_model_message(messages, state)
message = call_llm(model_message)
```

这里有一个重要变化：

```text
第二部分：call_llm(messages)
第三部分：call_llm(model_message)
```

`model_message` 不是完整原始历史，而是：

```text
system prompt
+ 当前压缩后的 state
+ 最近几条 messages
```

这就是第三部分的核心思路：不要把全部历史都塞给模型，而是把重要状态整理后再给模型。

## 6. State 压缩的意义

当前代码里：

```python
recent_messages = message[1:][-keep_recent:]
```

表示只保留最近几条消息。

`state_to_context` 里也只取一部分：

```python
"observations": state["observations"][-5:],
"notes": state["notes"][-5:],
"error": state["error"][-5:],
```

这很重要，因为真实 Agent 不能无限堆上下文。

如果每一轮都把完整网页、完整搜索结果、完整工具日志塞回去，会有几个问题：

```text
1. token 越来越多
2. 模型更难抓重点
3. 成本变高
4. 旧错误可能干扰新判断
```

所以 state and memory 的难点不是“保存所有东西”，而是“保存下一步决策真正需要的东西”。

## 7. 去重也是一种 Memory

当前 `agent.py` 里有：

```python
seen_tool_calls = set()
```

每次调用工具前，会生成一个 key：

```python
call_key = (
    tool_name,
    json.dumps(args, sort_keys=True, ensure_ascii=False)
)
```

如果同一个工具和同一组参数已经调用过，就返回一个错误结果：

```python
"type": "duplicate_tool_call"
```

这个逻辑的意义是：

```text
Agent 应该使用已经观察到的信息，而不是重复做同一件事。
```

这也是 memory 的一种：记住“我已经调用过什么”。

## 8. 第三部分的学习重点

这一部分不要只盯着“怎么写一个 dict”。真正要理解的是这几个问题：

```text
1. messages 和 state 分别解决什么问题？
2. 工具结果为什么既要回到 messages，又要更新 state？
3. state_to_context 为什么要压缩信息？
4. LLM 为什么不会自动知道 Python 里的 state？
5. 去重为什么也属于 memory？
```

最重要的一句话：

```text
State 是 Agent 对任务过程的结构化理解；messages 是把这些信息交给 LLM 的通信记录。
```

## 9. 和前两部分连起来看

完整学习路线可以这样记：

```text
第一部分：Agent Loop
让一次 LLM 调用变成多步任务执行。

第二部分：Tool Calling
让 LLM 用正式协议表达工具调用。

第三部分：State and Memory
让 Agent 整理工具结果、压缩上下文、避免重复动作。
```

最后回到最初那句话：

```text
Agent = LLM + tools + loop + state
```

第一部分看清楚 loop。
第二部分看清楚 tools 如何接入 LLM。
第三部分看清楚 state 为什么不只是 messages，而是 Agent 自己维护的工作记忆。
