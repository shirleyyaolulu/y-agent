# 第七部分：Policy and Sandbox

前面第六部分已经把工具系统拆成了：

```text
tool_registry.py = 工具登记
tool_runtime.py  = 工具执行
agent.py         = 主循环编排
```

第七部分开始，重点变成：

```text
不是所有工具调用都应该直接执行。
```

因为工具不再只是普通函数，它可能会：

```text
读数据
写文件
访问网络
执行 shell
修改长期记忆
```

所以在真实 Agent 里，LLM 生成 tool call 以后，Python 不应该马上执行 handler。

中间应该多一层：

```text
policy / sandbox / approval
```

一句话总结：

```text
Policy 决定能不能执行。
Sandbox 定义默认允许哪些能力。
Approval 处理需要用户确认的高风险操作。
Tool Runtime 在真正执行 handler 之前执行这些检查。
```

## 1. 主流 Agent 的基本框架

主流 Agent 的工具执行链路通常是：

```text
LLM returns tool_call
-> parse tool name and args
-> find tool spec
-> validate args
-> check policy / permissions
-> maybe ask user approval
-> execute tool in sandbox or constrained runtime
-> return tool result
-> update state / trace
```

对应到当前项目：

```text
LLM returns tool_call
-> tool_runtime.py 解析 tool_call
-> tool_registry.py 查 ToolSpec
-> validate_args 校验参数
-> policy.py 做 allow / ask / deny
-> approval_callback 询问用户
-> tool_spec.handler(args) 执行真实工具
-> update_state_after_tool 更新 state
```

所以你的主框架是对的。

当前结构已经符合主流 Agent 的核心分层：

| 层 | 当前文件 | 作用 |
|---|---|---|
| Tool Definition | `tool_registry.py` | 定义工具名、参数、handler、capability |
| Policy Decision | `policy.py` | 根据工具能力和策略返回 allow / ask / deny |
| Runtime Gate | `tool_runtime.py` | 在执行 handler 前拦截不安全调用 |
| Human Approval | `agent.py` | 通过 `ask_user_approval` 让用户确认 |
| State Update | `state.py` | 记录成功结果或失败原因 |

## 2. Policy 和 Sandbox 的区别

这两个词容易混在一起。

在主流 Agent 里，可以这样理解：

```text
Policy = 决策规则
Sandbox = 执行边界
```

Policy 回答的是：

```text
这个工具调用应该 allow、deny，还是 ask？
```

Sandbox 回答的是：

```text
这个运行环境默认允许哪些能力？
```

例如：

```python
SandboxPolicy(
    allow_read=True,
    allow_write=False,
    allow_network=False,
    allow_shell=False,
)
```

这表示当前环境默认只允许读，不允许写文件、访问网络、执行 shell。

而 `ApprovalPolicy` 表示遇到不允许的能力时怎么办：

```python
ApprovalPolicy(mode="on_request")
```

表示：

```text
默认不允许，但可以问用户要不要批准。
```

所以它们是两层：

```text
SandboxPolicy = 默认权限边界
ApprovalPolicy = 超出边界时是否允许申请审批
```

## 3. 当前实现里的 Policy 数据结构

当前 `policy.py` 里有三个核心对象。

第一个是 sandbox：

```python
@dataclass(frozen=True)
class SandboxPolicy:
    allow_read: bool = True
    allow_write: bool = False
    allow_network: bool = False
    allow_shell: bool = False
```

它描述当前运行环境允许哪些能力。

第二个是 approval：

```python
@dataclass(frozen=True)
class ApprovalPolicy:
    mode: str = "on_request"
```

当前支持三种模式：

| mode | 含义 |
|---|---|
| `never` | 不询问用户；sandbox 不允许就直接 deny |
| `on_request` | sandbox 不允许时询问用户 |
| `untrusted` | 高风险能力即使 sandbox 允许，也要询问用户 |

第三个是决策结果：

```python
@dataclass(frozen=True)
class PolicyDecision:
    action: str
    reason: str = ""
```

`action` 只应该有三种：

```text
allow
ask
deny
```

这就是一个典型 policy engine 的最小形态。

## 4. capability 应该放在哪里

当前你把 capability 放在 `ToolSpec` 上：

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: callable
    capability: str = "read"
```

这是对的。

因为 capability 是工具本身的安全属性，不应该散落在 runtime 里写 if-else。

例如：

```python
ToolSpec(
    name="search_web",
    ...
    handler=search_web,
    capability="network",
)
```

这表示：

```text
search_web 这个工具需要 network 能力。
```

再比如：

```python
ToolSpec(
    name="save_note",
    ...
    handler=save_note,
    capability="write",
)
```

表示：

```text
save_note 这个工具需要 write 能力。
```

这样 runtime 不需要知道每个工具的业务细节。

它只需要做：

```python
decision = check_policy(tool_spec, sandbox_policy, approval_policy)
```

这就是主流 Agent 常见的写法：

```text
工具声明自己的能力需求。
运行时根据能力需求做统一安全检查。
```

## 5. check_policy 的核心逻辑

当前 `check_policy` 做了三步。

第一步：看工具需要什么能力。

```python
capability = tool_spec.capability
```

第二步：看 sandbox 是否允许这个能力。

```python
allowed = {
    "read": sandbox_policy.allow_read,
    "write": sandbox_policy.allow_write,
    "network": sandbox_policy.allow_network,
    "shell": sandbox_policy.allow_shell,
}.get(capability, False)
```

第三步：根据 sandbox 和 approval policy 返回决策。

可以简化成：

```text
如果 sandbox 允许：
    如果 untrusted 且是高风险能力 -> ask
    否则 -> allow

如果 sandbox 不允许：
    如果 approval policy 允许询问 -> ask
    否则 -> deny
```

这个框架是合理的。

它表达了主流 Agent 里很常见的三段式：

```text
allowed by default
requires approval
denied
```

## 6. Runtime 应该在什么时候检查 policy

policy 检查应该发生在：

```text
参数解析之后
参数校验之后
真实 handler 执行之前
```

当前 `tool_runtime.py` 的顺序是：

```text
parse args
-> validate args
-> duplicate check
-> check policy
-> maybe approval
-> handler(args)
```

这个顺序是对的。

为什么不是最开始就 check policy？

因为 policy 需要知道：

```text
工具名是否存在
参数是否是合法 JSON
参数是否符合 schema
```

如果参数本身已经非法，就不需要进入安全审批。

为什么必须在 handler 前 check policy？

因为 handler 才是真正有副作用的地方。

例如：

```python
result = tool_spec.handler(args)
```

一旦执行到这里，文件可能已经写了，网络可能已经访问了，长期记忆可能已经保存了。

所以 policy 必须挡在 handler 前面。

## 7. Approval 的位置

当前 approval 是这样接入的：

```python
approved = approval_callback(tool_name, args, decision.reason)
```

在 `agent.py` 里，对应：

```python
approval_callback=ask_user_approval
```

这也是对的。

因为 runtime 不应该自己决定怎么和用户交互。

runtime 只应该说：

```text
这个 tool call 需要 approval。
```

至于 approval 是：

```text
命令行 input
网页弹窗
Slack 按钮
API 审批
```

这是 agent 外层应用的问题。

当前项目用 CLI：

```python
answer = input("Approve this tool call? [y/N]: ").strip().lower()
```

对学习项目来说已经够了。

## 8. 和主流 Agent 的区别

你的主框架没有错，但和真正生产级 Agent 相比，有几个简化点。

### 8.1 当前 sandbox 不是 OS 级真实沙箱

当前 `SandboxPolicy` 是 Python 代码里的权限门禁：

```text
在 handler 执行前决定能不能执行。
```

它不是：

```text
Docker sandbox
seccomp
Firecracker microVM
macOS sandbox-exec
文件系统只读挂载
网络隔离
```

所以更准确地说，当前实现是：

```text
policy-level sandbox
```

不是：

```text
runtime isolation sandbox
```

这对学习主框架没有问题。

但如果以后做生产级 Agent，要记住：

```text
Policy 负责决定。
真正的 Sandbox 负责强制执行。
```

也就是说，生产级系统通常会有两层：

```text
policy gate: 代码层面先判断 allow / ask / deny
isolation sandbox: 即使代码判断错了，底层环境也限制文件、网络、进程能力
```

### 8.2 capability 现在是单一字符串

当前一个工具只有一个 capability：

```python
capability="network"
```

生产系统里，一个工具可能需要多个能力：

```text
read + network
write + network
shell + write
```

所以以后可以扩展成：

```python
capabilities: set[str]
```

或者：

```python
capabilities: list[str]
```

但当前阶段用一个字符串是可以的，因为工具都很简单。

### 8.3 当前权限粒度比较粗

现在是：

```text
read / write / network / shell
```

生产系统往往会更细：

```text
read which path?
write which path?
network to which domain?
shell command with which prefix?
can access secrets?
can mutate database?
```

例如：

```text
允许 write notes/
不允许 write ~/.ssh/

允许 network api.github.com
不允许 network unknown domains
```

你的当前实现是最小版本，主框架没问题。

### 8.4 当前 approval 是同步 CLI

当前 approval 会阻塞在：

```python
input("Approve this tool call? [y/N]: ")
```

生产系统可能是异步的：

```text
暂停 agent
发起审批任务
等待用户在 UI 里点 approve / deny
恢复执行
```

但抽象仍然是一样的：

```text
policy returns ask
agent asks human
human decision controls runtime
```

## 9. 当前实现的整体调用链

现在可以把一次工具调用画成这样：

```text
agent.py
  for tool_call in message.tool_calls
        |
        v
tool_runtime.execute_tool_call(...)
        |
        v
parse JSON arguments
        |
        v
TOOL_REGISTRY.get(tool_name)
        |
        v
validate_args(args, schema)
        |
        v
check_policy(tool_spec, sandbox_policy, approval_policy)
        |
        +--> allow -> handler(args)
        |
        +--> deny  -> tool_error(policy_denied)
        |
        +--> ask   -> approval_callback(...)
                       |
                       +--> approved -> handler(args)
                       |
                       +--> denied   -> tool_error(approval_denied)
        |
        v
update_state_after_tool(...)
        |
        v
return args, result, state
```

这个图就是第七部分最重要的框架。

## 10. 几个 policy preset 的含义

当前有三个预设。

### read_only_policy

```python
SandboxPolicy(
    allow_read=True,
    allow_write=False,
    allow_network=False,
    allow_shell=False,
)
ApprovalPolicy(mode="never")
```

含义：

```text
只允许读。
不允许写、网络、shell。
也不问用户，超出权限直接拒绝。
```

适合：

```text
最保守的测试模式
只想看 Agent 会不会乱调用危险工具
```

### interactive_policy

```python
SandboxPolicy(
    allow_read=True,
    allow_write=False,
    allow_network=False,
    allow_shell=False,
)
ApprovalPolicy(mode="on_request")
```

含义：

```text
默认只允许读。
遇到写、网络、shell 时问用户。
```

适合：

```text
本地学习和调试
```

这也是当前 runtime 的默认策略。

### workspace_policy

```python
SandboxPolicy(
    allow_read=True,
    allow_write=True,
    allow_network=False,
    allow_shell=False,
)
ApprovalPolicy(mode="on_request")
```

含义：

```text
允许读写。
网络和 shell 仍然需要审批。
```

适合：

```text
允许 Agent 在工作区写 note 或记忆，但不希望它随便联网或执行 shell。
```

注意：当前代码还没有限制“只能写 workspace 哪些路径”。

所以它只是粗粒度 write permission。

## 11. 自检清单

学完这一部分，你应该能回答：

1. `SandboxPolicy` 和 `ApprovalPolicy` 分别解决什么问题？
2. 为什么 capability 要放在 `ToolSpec` 上？
3. 为什么 policy check 必须在 handler 执行之前？
4. `allow`、`ask`、`deny` 分别表示什么？
5. 为什么当前实现不是 OS 级真实 sandbox？
6. 主流 Agent 为什么通常需要 human approval？
7. 当前实现和生产级 Agent 相比，主要简化了哪些地方？

参考答案：

1. `SandboxPolicy` 定义默认允许哪些能力；`ApprovalPolicy` 定义超出默认能力时是否可以询问用户。
2. capability 是工具本身的安全属性，放在 registry 里可以让 runtime 做统一检查。
3. handler 是真正产生副作用的位置，必须在它执行前完成权限判断。
4. `allow` 直接执行，`ask` 需要用户确认，`deny` 直接拒绝执行。
5. 当前 sandbox 是 Python 层面的门禁，没有 Docker、VM、文件系统挂载、网络隔离等强制边界。
6. 因为 LLM 可能误判或被提示注入诱导，写文件、联网、shell 等操作需要人类确认。
7. 当前 capability 单一、权限粒度粗、approval 是同步 CLI、没有底层隔离沙箱。

## 12. 一句话背诵版

```text
第七部分是在给工具执行加安全边界：
ToolSpec 声明能力，
Policy 判断 allow / ask / deny，
Runtime 在 handler 前执行检查，
Approval 让人类介入高风险操作。
```

