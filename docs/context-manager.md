# 第五部分：Context Manager

前四部分已经解决了这些问题：

```text
第一部分：Agent loop 怎么跑起来
第二部分：正式 tool calling 协议怎么接
第三部分：state / memory 怎么整理任务过程
第四部分：thread / turn / item 怎么持久化执行记录
```

第五部分开始，重点变成：

```text
历史越来越长以后，下一次到底该给 LLM 哪些 messages？
怎么避免把 system / memory / state / 历史消息混在一起？
怎么截断上下文时不破坏 tool calling 协议？
```

一句话总结：

```text
Context Manager 的作用，是把完整历史整理成“本轮 LLM 调用真正需要的上下文”。
```

## 1. 为什么需要 Context Manager

如果没有 context manager，最简单的做法是：

```python
message = call_llm(messages)
```

也就是把完整 `messages` 全部发给模型。

但随着 Agent 运行时间变长，会出现几个问题：

```text
1. messages 越来越长，token 成本越来越高
2. 很旧的工具结果可能不再重要
3. LLM 容易被大量历史细节干扰
4. 随便截断 messages 可能破坏 tool calling 协议
```

所以现在 `agent.py` 不再直接把完整 `messages` 发给 LLM，而是：

```python
model_message = build_model_messages(messages, state, long_term_memories)
message = call_llm(model_message)
```

这里的 `build_model_messages(...)` 就是 context manager 的入口。

## 2. Context Manager 负责什么

当前 `context_manager.py` 主要做三件事：

```text
1. 构造系统级上下文
   system prompt + long-term memories + current state + optional summary

2. 从历史 messages 里选择最近一部分
   不是按单条 message 截取，而是按 protocol chunk 截取

3. 返回最终 model messages
   让 LLM API 收到一维 messages list
```

对应代码是：

```python
def build_model_messages(
    messages,
    state,
    memories,
    compacted_summary=None,
    max_recent_chunks=DEFAULT_MAX_RECENT_CHUNKS,
):
    system_message = messages[0]

    context_messages = [
        system_message,
        make_memory_message(memories),
        make_state_message(state),
    ]

    summary_message = make_summary_message(compacted_summary)
    if summary_message:
        context_messages.append(summary_message)

    recent_messages = select_recent_messages(messages, max_recent_chunks)

    return context_messages + recent_messages
```

所以最终发给 LLM 的结构是：

```text
system prompt
+ long-term memories system message
+ current state system message
+ optional compacted summary system message
+ recent protocol-safe messages
```

## 3. 和第三部分 State / Memory 的关系

第三部分里，我们已经有了：

```python
state = create_initial_state(user_input)
state = update_state_after_tool(state, tool_name, args, result)
```

但 Python 里的 `state` 本身不会自动被 LLM 看到。

所以 context manager 要把它转成 system message：

```python
def make_state_message(state):
    return {
        "role": "system",
        "content": f"Current explicit agent state:\n{state_to_context(state)}"
    }
```

长期记忆也是一样：

```python
def make_memory_message(memories):
    return {
        "role": "system",
        "content": f"Long-term memories:\n{format_memories_for_context(memories)}"
    }
```

这里的分工是：

```text
state.py / memory.py
负责保存和格式化信息。

context_manager.py
负责决定这些信息以什么消息形式进入 LLM 上下文。
```

## 4. 为什么不是直接取最近 N 条 messages

最容易误解的是这里：

```python
chunks = build_protocol_chunks(history_message)
selected_chunks = chunks[-max_recent_chunks:]
```

为什么不直接写：

```python
messages[-6:]
```

原因是正式 tool calling 协议里，有些消息不能被拆开。

合法的一组是：

```text
assistant message with tool_calls
tool message with tool_call_id
```

如果直接按单条 message 截断，可能截出这种坏结构：

```text
tool message with tool_call_id
user message
```

或者：

```text
assistant message with tool_calls
user message
```

这两种都不适合直接发给 LLM。

所以当前实现先把 messages 分成 protocol chunks。

## 5. 什么是 protocol chunk

`build_protocol_chunks(...)` 返回的是二维 list：

```python
[
    [user_message],
    [assistant_tool_call_message, tool_result_message],
    [assistant_final_message],
]
```

普通消息自己是一个 chunk：

```python
[message]
```

assistant tool call 和它后面的 tool result 会组成一个 chunk：

```python
[
    {"role": "assistant", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "...", "content": "..."},
]
```

如果 assistant 一次调用多个工具，那么这个 chunk 会更长：

```python
[
    assistant_tool_call_message,
    tool_result_1,
    tool_result_2,
]
```

这样做的好处是：

```text
选择上下文时，可以按 chunk 选择。
一旦选择了 assistant tool_calls，就一定把对应 tool_result 一起带上。
```

## 6. message_protocal.py 的作用

你把协议判断抽到了 `message_protocal.py`：

```python
def is_tool_message(message):
    return message.get("role") == "tool"

def is_assistant_tool_call(message):
    return message.get("role") == "assistant" and has_tool_call(message)
```

还有一个更关键的函数：

```python
def read_tool_call_group(messages, start_index):
    ...
    return group, next_index
```

它负责从某个 assistant tool call 开始，读取一整组完整协议消息：

```text
assistant tool_calls
+ tool result 1
+ tool result 2
+ ...
```

如果后面的 tool message 不完整，就返回：

```python
None, start_index + 1
```

这说明：

```text
这个 assistant tool call 组不能安全使用。
调用方应该跳过或丢弃它。
```

把这部分抽出来的好处是：`thread.py` 和 `context_manager.py` 可以复用同一套协议判断。

## 7. selected_messages 为什么还要再生成一次

`chunks` 本身确实是 list，但它是二维 list：

```python
chunks = [
    [message1],
    [assistant_tool_call_message, tool_message],
    [message4],
]
```

选最近 chunk 后：

```python
selected_chunks = chunks[-max_recent_chunks:]
```

得到的仍然是二维结构。

但 OpenAI / DeepSeek 的 `messages` 参数需要一维 list：

```python
[
    {"role": "user", "content": "..."},
    {"role": "assistant", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "...", "content": "..."},
]
```

所以需要：

```python
selected_messages = []
for chunk in selected_chunks:
    selected_messages.extend(chunk)
return selected_messages
```

这一步的作用是把二维 chunk list 摊平成一维 messages list。

一句话：

```text
chunks 是为了“安全选择”。
selected_messages 是为了“符合 LLM API 输入格式”。
```

## 8. 为什么要跳过 system message

`select_recent_messages(...)` 里有：

```python
history_message = messages[1:]
chunks = build_protocol_chunks(history_message)
```

这里的 `messages[1:]` 是为了跳过第一条 system prompt。

因为 system prompt 会在 `build_model_messages(...)` 里单独放回去：

```python
system_message = messages[0]
context_messages = [
    system_message,
    make_memory_message(memories),
    make_state_message(state),
]
```

如果不跳过 system message，后面再拼接时可能出现重复 system prompt。

所以这里的设计是：

```text
system / memory / state 由 context manager 明确构造。
历史对话只从 messages[1:] 里选择。
```

## 9. optional summary 是为以后压缩上下文留的口

当前 `build_model_messages(...)` 支持：

```python
compacted_summary=None
```

如果传入 summary，会生成：

```python
{
    "role": "system",
    "content": "Compacted previous context:\n" + summary
}
```

这说明未来可以把更早的历史压缩成摘要，而不是完全丢掉。

最终上下文可以变成：

```text
system prompt
+ long-term memories
+ current state
+ compacted previous context
+ recent messages
```

这是一个常见的上下文管理策略：

```text
旧历史 -> summary
近期历史 -> 原始 messages
当前任务状态 -> structured state
长期偏好/事实 -> long-term memory
```

## 10. 这部分最容易踩的坑

### 10.1 按 message 截断会破坏 tool calling 协议

不要直接：

```python
recent_messages = messages[-6:]
```

因为这可能把：

```text
assistant tool_calls
tool result
```

拆开。

正确思路是：

```text
先 build_protocol_chunks
再按 chunk 截断
最后 flatten 成 messages
```

### 10.2 `chunks` 和 `selected_messages` 不是同一种结构

```text
chunks            = 二维 list，用来表达“哪些 messages 必须绑在一起”
selected_messages = 一维 list，用来真正发给 LLM
```

如果直接返回 `selected_chunks`，LLM API 会拿到嵌套 list，格式不对。

### 10.3 复用协议逻辑时，要避免重复追加

`build_protocol_chunks(...)` 处理 assistant tool call group 时，核心意图是：

```text
读到完整 group -> chunks.append(group) -> i 跳到 group 后面
```

这类逻辑和第四部分的 `drop_incomplete_tool_call_tail(...)` 很像。

难点是：处理完一组之后，要确保不会再把同一个 assistant message 当普通消息追加一次。

所以阅读这类代码时，要重点检查：

```text
i 是否已经跳到 next_index
当前循环是否还会继续落到 chunks.append([message])
```

这就是 context manager 里最容易出现重复 message 的地方。

## 11. 和前几部分连起来看

现在整个 Agent 的上下文路径可以这样理解：

```text
thread.py
从 jsonl 恢复历史 messages

agent.py
把 system + history + new user input 组成完整 messages

context_manager.py
把完整 messages 压缩/筛选成 model_message

llm.py
把 model_message 发给 LLM
```

也就是：

```text
thread 负责恢复历史。
agent 负责维护运行时消息。
context manager 负责选择本轮 LLM 需要看的上下文。
llm 负责真正调用模型。
```

这里要注意两个名字：

```text
messages      = Agent 内部维护的完整运行时历史
model_message = 本轮实际发送给 LLM 的精简上下文
```

## 12. 这一部分应该记住什么

最重要的是这三个边界：

```text
完整历史不等于模型上下文。
```

```text
截断上下文不能破坏 assistant tool_calls + tool_result 的协议组。
```

```text
Context Manager 不是保存记忆的地方，而是决定“这次给模型看什么”的地方。
```

一句话总结：

```text
第五部分的核心，是把 Agent 从“把所有 messages 都塞给 LLM”推进到“有选择、有结构、协议安全地构造上下文”。
```

