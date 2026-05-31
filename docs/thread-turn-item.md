# 第四部分：Thread / Turn / Item

前三部分已经让 Agent 具备了三个能力：

```text
第一部分：会跑一个最小 Agent Loop
第二部分：会使用正式 tool calling 协议
第三部分：会维护单次运行里的 state / memory
```

第四部分开始，重点变成：

```text
一次程序运行结束后，Agent 怎么接着上一轮继续聊？
一次用户请求里发生了哪些步骤，怎么保存？
如果中途失败，怎么避免把坏的 messages 发回 LLM？
```

一句话总结：

```text
前三部分解决“Agent 怎么在一次运行里工作”。
第四部分解决“Agent 怎么把运行过程持久化，并在下一次 resume 时恢复上下文”。
```

## 1. 三个概念先分清

当前实现里，新增了三个层级：

| 概念 | 含义 | 当前代码里的体现 |
| --- | --- | --- |
| `thread` | 一整段可恢复的会话 | `threads/<thread_id>.jsonl` |
| `turn` | 用户发起的一次请求，以及 Agent 对这次请求的执行过程 | `turn_id = new_id("turn")` |
| `item` | turn 里发生的一条事件记录 | `append_item(...)` 写入 jsonl |

可以这样理解：

```text
thread = 一个聊天会话文件
turn   = 用户问一次，Agent 回答一次的执行过程
item   = 这个过程里每一步发生了什么
```

例如一次完整执行可能长这样：

```text
thread_start
turn_started
user_message
assistant_message
tool_result
assistant_message
final_answer
turn_finished
```

`thread` 是容器，`turn` 是一次任务，`item` 是可追溯的事件。

## 2. 和前三部分的核心对比

前三部分里，主要状态在内存里的 `messages` 和 `state`：

```python
messages.append(assistant_message)
messages.append(tool_message)
state = update_state_after_tool(...)
```

程序一结束，这些内存对象就没了。

第四部分新增了一条持久化路径：

```python
append_item(
    thread_id,
    turn_id,
    "assistant_message",
    {"message": assistant_message},
)
```

也就是说，消息现在会同时走两条路：

```text
1. append 到内存 messages
   给当前这次 agent loop 继续用。

2. append 到 thread jsonl 文件
   给未来 resume 时重建历史。
```

所以第四部分的本质变化是：

```text
messages 从“临时上下文”变成了“可以由事件日志重建的上下文”。
```

## 3. thread.py：append-only 事件日志

`thread.py` 是第四部分最核心的新增模块。

### 3.1 创建 thread

```python
def create_thread():
    thread_id = new_id("th")
    append_item(
        thread_id=thread_id,
        turn_id=None,
        item_type="thread_start",
        data={},
    )
    return thread_id
```

创建 thread 时，不是只返回一个 id，而是先写入一条：

```text
type = "thread_start"
```

这说明这个 jsonl 文件不是普通 messages 数组，而是一个事件流。

### 3.2 写入 item

```python
def append_item(thread_id, turn_id, item_type, data):
    item = {
        "item_id": new_id("it"),
        "thread_id": thread_id,
        "turn_id": turn_id,
        "type": item_type,
        "data": data,
        "created_at": now(),
    }
```

这里的设计重点是：所有东西都统一保存成 `item`。

好处是将来可以保存不同类型的事件：

```text
user_message
assistant_message
tool_result
final_answer
turn_finished
turn_stopped
```

它们不一定都是 LLM messages，但都属于 Agent 执行过程。

## 4. agent.py：一次 turn 如何被记录

`run_agent(...)` 现在多了 `thread_id` 参数：

```python
def run_agent(user_input, call_llm, max_step=8, thread_id=None):
    if thread_id == None:
        thread_id = create_thread()
    turn_id = new_id("turn")
```

这里分两种情况：

```text
run:
没有 thread_id -> 创建新 thread

resume:
传入已有 thread_id -> 继续同一个 thread
```

一次 turn 开始时，会先记录：

```python
append_item(thread_id, turn_id, "turn_started", {"user_input": user_input})
append_item(thread_id, turn_id, "user_message", {"message": {...}})
```

LLM 返回 assistant message 后，会记录：

```python
append_item(
    thread_id,
    turn_id,
    "assistant_message",
    {"message": assistant_message},
)
```

Python 工具执行完后，会记录：

```python
append_item(
    thread_id,
    turn_id,
    "tool_result",
    {"message": tool_message},
)
```

最终回答时，会记录：

```python
append_item(thread_id, turn_id, "final_answer", {"answer": final_answer})
append_item(thread_id, turn_id, "turn_finished", {"state": state})
```

所以现在一个 turn 不只是“用户一句，助手一句”，而是包含完整执行轨迹：

```text
用户输入
LLM 是否调用工具
调用了什么工具
工具结果是什么
最终答案是什么
结束时 state 长什么样
```

## 5. resume：如何从 thread 恢复 messages

`main.py` 里新增了两个命令：

```text
python main.py run "your message"
python main.py resume <thread_id> "your message"
```

`resume` 最关键的是：

```python
history_message = load_thread_messages(thread_id)

messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
] + history_message + [
    {"role": "user", "content": user_input},
]
```

这里的含义是：

```text
1. 先从 thread jsonl 里读历史 item
2. 只挑出能重新发给 LLM 的 message
3. 拼上新的 user input
4. 再调用 LLM
```

注意：不是所有 item 都会变成 messages。

会被恢复的是：

```python
{"user_message", "assistant_message", "tool_result"}
```

不会直接恢复的是：

```text
thread_start
turn_started
final_answer
turn_finished
turn_stopped
```

因为这些是审计/记录信息，不是 LLM API 需要的对话协议消息。

## 6. 为什么必须清理 incomplete tool call tail

正式 tool calling 有一个很硬的协议要求：

```text
assistant message 只要带 tool_calls，
后面必须紧跟对应 tool_call_id 的 tool messages。
```

合法结构：

```text
assistant tool_calls: call_1
tool tool_call_id: call_1
```

多个 tool calls 时：

```text
assistant tool_calls: call_1, call_2
tool tool_call_id: call_1
tool tool_call_id: call_2
```

不合法结构：

```text
assistant tool_calls: call_1
user: 新问题
```

这会触发类似错误：

```text
An assistant message with 'tool_calls' must be followed by tool messages
```

所以 `load_thread_messages(...)` 不能直接把所有历史 message 原样返回，而要先经过：

```python
return drop_incomplete_tool_call_tail(messages)
```

这个函数的作用是：

```text
只保留协议完整的 messages。
如果尾部出现 assistant tool_calls 但缺少 tool_result，就丢掉这段尾巴。
```

## 7. drop_incomplete_tool_call_tail 的核心逻辑

核心代码结构是：

```python
if message.get("role") == "assistant" and message.get("tool_calls"):
    expected_ids = [tc["id"] for tc in message["tool_calls"]]
    group = [message]
    j = i + 1

    for tool_call_id in expected_ids:
        if j >= len(messages):
            return clean

        tool_message = messages[j]
        if (
            tool_message.get("role") != "tool"
            or tool_message.get("tool_call_id") != tool_call_id
        ):
            return clean

        group.append(tool_message)
        j += 1

    clean.extend(group)
    i = j
    continue
```

它做了三件事：

```text
1. 看到 assistant tool_calls，就收集 expected_ids。
2. 检查后面的 tool message 是否一一对应。
3. 只有整组完整，才 clean.extend(group)。
```

这里的 `group` 是一组协议完整的消息：

```text
assistant tool_calls
tool result
tool result
...
```

`clean.extend(group)` 表示把这一组消息展开加入 `clean`，保持 messages 是一维列表。

## 8. 这部分最容易踩的坑

### 8.1 少了 continue 会重复添加 assistant message

这次你遇到的 root cause 就在这里。

如果代码写成：

```python
clean.extend(group)
i = j

if message.get("role") == "tool":
    ...

clean.append(message)
```

那么完整 group 加进去之后，代码还会继续执行到：

```python
clean.append(message)
```

此时 `message` 仍然是那个 assistant tool_calls message。

结果内存里的 messages 会变成：

```text
assistant tool_calls: call_1
tool result: call_1
assistant tool_calls: call_1   # 重复出现，后面没有紧跟 tool
```

这不是 jsonl 文件里多写了一行，而是恢复历史时在内存里重复追加了。

所以这里必须：

```python
clean.extend(group)
i = j
continue
```

含义是：

```text
这一组已经处理完了，直接进入下一轮 while。
不要再让当前 assistant message 走到普通 clean.append(message)。
```

### 8.2 `j >= len(messages)` 不能写成 `j > len(messages)`

如果后面已经没有消息了：

```python
j == len(messages)
```

这时访问：

```python
messages[j]
```

会越界。

所以边界条件应该是：

```python
if j >= len(messages):
    return clean
```

不是：

```python
if j > len(messages):
```

### 8.3 孤立的 tool message 要跳过

代码里还有：

```python
if message.get("role") == "tool":
    i += 1
    continue
```

意思是：如果一个 `tool` message 没有被前面的 assistant tool_calls 配对上，它不能单独发给 LLM。

因为 tool message 的意义依赖于：

```text
前面某条 assistant tool_calls 里的 tool_call_id
```

没有对应 assistant，它就是孤立的协议碎片。

## 9. JSONL 文件里怎么看 thread / turn / item

实际文件类似：

```text
threads/th_2f55f594201f.jsonl
```

里面每一行都是一个 item：

```json
{
  "item_id": "it_...",
  "thread_id": "th_...",
  "turn_id": "turn_...",
  "type": "assistant_message",
  "data": {
    "message": {
      "role": "assistant",
      "tool_calls": [...]
    }
  },
  "created_at": "..."
}
```

对于 tool calling，重点看相邻行：

```text
assistant_message:
  data.message.role = assistant
  data.message.tool_calls[0].id = call_1

tool_result:
  data.message.role = tool
  data.message.tool_call_id = call_1
```

这两行是一组。

如果看到：

```text
assistant_message with tool_calls
后面没有 tool_result
```

这个 thread 尾部就不能直接恢复给 LLM，必须丢掉不完整尾巴。

## 10. 这一部分应该记住什么

最重要的不是 API 名字，而是这几个边界：

```text
thread = 长期会话容器
turn   = 一次用户请求的执行过程
item   = 执行过程中 append-only 的事件
```

```text
messages = 给 LLM API 的协议上下文
items    = 给程序恢复、审计、调试用的事件日志
```

```text
assistant tool_calls + tool_result 必须作为一组恢复。
不能让半截 tool call 混进下一次 LLM 请求。
```

一句话总结：

```text
第四部分的核心，是把 Agent 从“单次运行的 while loop”推进到“可恢复的事件流”。
```
