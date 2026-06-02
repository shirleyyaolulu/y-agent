# 第九部分：Workspace Tools

前面几部分已经讲过：

```text
tool_registry.py = 工具登记
tool_runtime.py  = 工具执行前的参数校验、权限检查、调用 handler
policy.py        = 判断工具能力是否允许
state.py         = 记录工具执行后的观察结果
```

第九部分开始，Agent 不再只是搜索网页、读 URL、保存 note。

它开始具备更像真实 coding agent 的能力：

```text
读工作区文件
编辑工作区文件
执行工作区命令
```

一句话总结：

```text
Workspace tools 把 LLM 的意图变成对本地项目的真实操作。
```

但这也是最容易出风险的一部分。

因为工具一旦能读写文件、执行 shell，Agent 就不只是“聊天”，而是在动你的 repo。

## 1. 这部分代码在哪里

当前 workspace tools 的核心文件是：

```text
workspace_tools.py
```

里面有三个主要工具：

| 工具 | 函数 | 能力 |
|---|---|---|
| `read_file` | `read_file(args)` | 读取工作区 UTF-8 文本文件 |
| `edit_file` | `edit_file(args)` | 精确替换文件中的一段文本 |
| `run_command` | `run_command(args)` | 在工作区执行 shell 命令 |

它们不是孤立存在的。

完整链路是：

```text
LLM returns tool_call
-> tool_runtime.py 解析 tool_call.function.arguments
-> tool_registry.py 找到对应 ToolSpec
-> validate_args 校验参数
-> policy.py 检查 read / write / shell 权限
-> workspace_tools.py 执行真实操作
-> state.py 记录 observation
-> tool result 回传给 LLM
```

所以 `workspace_tools.py` 是真实动作层。

它负责：

```text
真的读文件
真的写文件
真的执行命令
```

而不是决定：

```text
工具是否存在
参数是否合法
这次调用是否需要审批
下一步还要不要继续调用 LLM
```

这些分别属于 registry、runtime、policy 和 agent loop。

## 2. WORKSPACE_ROOT 是边界

文件顶部有这一句：

```python
WORKSPACE_ROOT = Path.cwd().resolve()
```

这表示：

```text
当前启动 python main.py 的目录，就是 Agent 的工作区根目录。
```

例如你在这里运行：

```bash
python main.py run "读取 README.md"
```

如果当前目录是：

```text
/Users/yaolulu/workspace/y-agent
```

那么 `WORKSPACE_ROOT` 就是这个目录。

后面所有文件路径都会基于它解析。

核心函数是：

```python
def resolve_workspace_path(path):
    resolved = (WORKSPACE_ROOT / path).resolve()

    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise ValueError(f"Path {path} is outside of the workspace")
    
    return resolved
```

这段代码的重点是：

```text
把用户/模型传来的相对路径解析成绝对路径。
然后确认这个绝对路径仍然在 WORKSPACE_ROOT 里面。
```

比如：

```text
README.md
```

会变成：

```text
/Users/yaolulu/workspace/y-agent/README.md
```

这是允许的。

但如果模型试图读：

```text
../../Documents/Resume/resume.html
```

`resolve()` 之后可能跑到工作区外面。

这时：

```python
resolved.relative_to(WORKSPACE_ROOT)
```

会失败，于是抛出：

```text
Path ... is outside of the workspace
```

这里的难点不是 `Path` 本身，而是理解：

```text
不能只检查字符串里有没有 ".."。
必须 resolve 成真实绝对路径以后，再判断它是否属于 workspace。
```

因为路径可以有很多绕法：

```text
../
./
符号链接
嵌套路径
```

用 `resolve()` + `relative_to()` 是更稳的边界检查。

## 3. read_file：分页读取文件

`read_file` 的参数是：

```python
path = args["path"]
offset = args.get("offset", 0)
limit = args.get("limit", DEFAULT_FILE_LISTING_LIMIT)
```

这里可以看到：

```text
path 是必填参数。
offset 和 limit 是可选参数。
```

所以 `path` 用：

```python
args["path"]
```

因为没有 `path` 就不应该继续执行。

而 `offset` / `limit` 用：

```python
args.get(...)
```

因为它们可以不传，不传就用默认值。

### offset 和 limit 怎么工作

当前代码：

```python
content = file_path.read_text(encoding="utf-8")
chunk = content[offset:offset+limit]
```

这说明它是按：

```text
字符位置
```

切片，不是按行数。

例如文件有 20000 个字符。

第一次读：

```json
{
  "path": "agent.py",
  "offset": 0,
  "limit": 8000
}
```

返回：

```text
第 0 到第 7999 个字符
```

如果返回里：

```json
"has_more": true
```

说明后面还有内容。

第二次可以继续读：

```json
{
  "path": "agent.py",
  "offset": 8000,
  "limit": 8000
}
```

这就是一个简单的分页机制。

### 为什么要分页

主要是为了防止：

```text
大文件一次性进入 tool result
大文件一次性进入 LLM 上下文
模型被大量无关内容干扰
终端输出过长
```

所以 `DEFAULT_FILE_LISTING_LIMIT = 8000` 的意义是：

```text
默认最多返回 8000 个字符给模型。
```

但要注意一个边界：

```python
content = file_path.read_text(encoding="utf-8")
```

它仍然会先把整个文件读进 Python 内存，再切片返回。

所以它防的是：

```text
返回给模型的内容太大
```

不是严格防：

```text
Python 进程读取超大文件导致内存压力
```

如果以后要支持真正的大文件，可以改成基于文件流的读取。

### read_file 的返回值

成功时返回：

```python
{
    "path": path,
    "offset": offset,
    "limit": limit,
    "total_chars": len(content),
    "content": chunk,
    "has_more": offset + limit < len(content),
}
```

这里最重要的是：

| 字段 | 作用 |
|---|---|
| `content` | 这次实际读到的内容片段 |
| `total_chars` | 文件总字符数 |
| `has_more` | 是否还有后续内容 |
| `offset` / `limit` | 告诉模型这次读的是哪一段 |

这些字段会帮助 LLM 决定：

```text
内容够了，直接回答
还是继续用更大的 offset 读取下一段
```

## 4. edit_file：精确替换，不是自由写文件

`edit_file` 的参数是：

```python
path = args["path"]
old = args["old"]
new = args["new"]
```

它不是让模型直接传入整个新文件内容。

它的设计是：

```text
找到文件里一段唯一的 old 文本。
把它替换成 new。
```

核心逻辑：

```python
content = file_path.read_text(encoding="utf-8")

count = content.count(old)
if count == 0:
    return tool_error(f"Text to replace not found in file: {old}", "text_not_found")

if count > 1:
    return tool_error("old text is not unique", "edit_text_not_unique")

updated = content.replace(old, new, 1)
file_path.write_text(updated, encoding="utf-8")
```

这里有两个关键保护：

```text
old 找不到，不编辑。
old 出现多次，不编辑。
```

为什么？

因为如果 `old` 出现多次，模型可能以为自己在改 A 处，实际 Python 改了第一处。

这种 bug 很隐蔽。

所以当前实现要求：

```text
old 必须唯一。
```

这比直接全局替换更保守。

### edit_file 的难点

难点不是 `replace()`。

难点是：

```text
让模型提供足够精确的 old 文本。
```

如果 old 太短：

```text
yAgent
```

它可能在文件里出现多次。

更稳的做法是让模型提供更长上下文：

```text
This is about yAgent.
```

再替换成：

```text
This is about yAgent Learning.
```

这样更容易保证唯一。

### 一个真实踩坑点

handler 里必须取具体字段：

```python
new = args["new"]
```

不能写成：

```python
new = args
```

否则 `new` 就是整个 dict：

```python
{"path": "...", "old": "...", "new": "..."}
```

然后执行：

```python
content.replace(old, new, 1)
```

会报错：

```text
replace() argument 2 must be str, not dict
```

这个错误很适合说明一件事：

```text
tool_runtime 只校验 args 的结构。
handler 仍然要正确读取 args 里的具体字段。
```

schema 正确，不代表 handler 就一定写对。

## 5. run_command：执行命令，但不是 shell 字符串

`run_command` 的参数是：

```python
command = args["command"]
timeout = args.get("timeout", DEFAULT_COMMAND_TIMEOUT)
```

它会限制 timeout：

```python
if timeout < 1 or timeout > DEFAULT_COMMAND_TIMEOUT:
    return tool_error(...)
```

默认最大：

```python
DEFAULT_COMMAND_TIMEOUT = 20
```

也就是最多等 20 秒。

核心执行逻辑：

```python
argv = shlex.split(command)

result = subprocess.run(
    argv,
    cwd=WORKSPACE_ROOT,
    text=True,
    capture_output=True,
    timeout=timeout,
    shell=False,
)
```

这里有几个重点。

### 第一，cwd 固定在 workspace

```python
cwd=WORKSPACE_ROOT
```

这表示命令默认在工作区里执行。

比如：

```json
{"command": "python main.py run 23*345"}
```

会在：

```text
/Users/yaolulu/workspace/y-agent
```

里执行。

### 第二，shell=False

```python
shell=False
```

这表示 Python 不会把整个字符串交给 shell 解释。

而是先：

```python
argv = shlex.split(command)
```

例如：

```text
python main.py run "读取 README.md"
```

会变成类似：

```python
["python", "main.py", "run", "读取 README.md"]
```

这样做的好处是：

```text
减少 shell 注入风险。
```

但也带来限制。

这些 shell 特性不会像普通终端那样自然工作：

```text
管道 |
重定向 >
环境变量展开 $HOME
通配符 *
&& / ||
```

因为它没有真正通过 shell 解析。

所以：

```text
run_command 是执行一个 argv 命令，不是完整 shell 会话。
```

### 第三，输出会截断

返回时：

```python
"stdout": truncate_text(result.stdout, MAX_COMMAND_OUTPUT_CHARS),
"stderr": truncate_text(result.stderr, MAX_COMMAND_OUTPUT_CHARS),
```

其中：

```python
MAX_COMMAND_OUTPUT_CHARS = 6000
```

意思是：

```text
命令输出最多返回 6000 个字符。
```

这和 `read_file` 的分页类似，都是为了防止：

```text
工具结果太大，撑爆上下文。
```

区别是：

```text
read_file 可以用 offset 继续读。
run_command 输出被截断后，目前没有 offset 机制。
```

如果命令输出很长，Agent 只能换更精确的命令重新跑。

例如：

```text
rg -n "pattern" file.py
```

比：

```text
cat very_large_file.py
```

更适合 Agent。

## 6. 这三个工具怎么登记给模型

`tool_registry.py` 里把这三个函数登记成 `ToolSpec`。

`read_file`：

```python
ToolSpec(
    name="read_file",
    description="Read a UTF-8 text file from the current workspace. Use offset and limit for large files.",
    parameters={...},
    handler=read_file,
    capability="read",
)
```

`edit_file`：

```python
ToolSpec(
    name="edit_file",
    description="Edit a UTF-8 text file in the current workspace by replacing old text with new text.",
    parameters={...},
    handler=edit_file,
    capability="write",
)
```

`run_command`：

```python
ToolSpec(
    name="run_command",
    description="Run a shell command in the current workspace.",
    parameters={...},
    handler=run_command,
    capability="shell",
)
```

这里重点是 `capability`：

| 工具 | capability | policy 怎么看 |
|---|---|---|
| `read_file` | `read` | 通常默认允许 |
| `edit_file` | `write` | 默认可能要审批 |
| `run_command` | `shell` | 风险更高，默认可能要审批 |

这和第七部分的 Policy and Sandbox 接上了。

工具自己不决定是否允许执行。

它只声明：

```text
我属于哪种能力。
```

然后 `policy.py` 根据当前策略决定：

```text
allow / ask / deny
```

## 7. state.py 记录观察，不保存全文

工具执行后，`state.py` 会更新 observations。

`read_file` 只保存预览：

```python
"content_preview": data.get("content", "")[:500]
```

`run_command` 也只保存 stdout/stderr 预览：

```python
"stdout_preview": data.get("stdout", "")[:500]
"stderr_preview": data.get("stderr", "")[:500]
```

这说明 state 不是完整日志。

它更像：

```text
给下一轮模型看的结构化工作记忆。
```

好处是：

```text
不会把超长文件和超长命令输出一直塞进上下文。
```

代价是：

```text
如果后续真的需要完整内容，模型要重新调用工具。
```

这里会遇到一个当前实现里的边界：

```text
同一轮 run_agent 内，seen_tool_calls 会阻止完全相同参数的重复工具调用。
```

所以如果模型第一次：

```json
{"path": "README.md"}
```

读过文件，后面再想用完全相同参数验证，就会被认为是重复调用。

解决方式可以是：

```text
读文件时带上不同 offset / limit
或者调整 duplicate 检测逻辑，让 read_file 在 edit_file 之后允许再次读取
或者由 edit_file 返回更新后的内容预览
```

这个点很重要，因为 coding agent 经常需要：

```text
编辑以后再验证。
```

如果验证被重复调用拦住，Agent 就只能根据 edit_file 的成功结果推断，而不能真实确认。

## 8. 三个工具的安全边界

当前 workspace tools 有一些已经做好的边界。

### 已经做好的

路径边界：

```text
resolve_workspace_path 会阻止访问 workspace 外部路径。
```

文件类型边界：

```text
read_file / edit_file 只处理 UTF-8 文本文件。
目录、二进制文件会报错。
```

读取大小边界：

```text
read_file 用 limit 控制返回内容大小。
```

编辑精确性边界：

```text
edit_file 要求 old 文本唯一。
```

命令时间边界：

```text
run_command 的 timeout 最多 20 秒。
```

命令输出边界：

```text
stdout / stderr 会被截断到 6000 字符。
```

shell 注入边界：

```text
run_command 使用 shell=False。
```

### 还没有完全解决的

第一，`read_file` 仍然会先把整个文件读进内存。

```text
limit 限制的是返回给模型的内容，不是 Python 实际读取的内容。
```

第二，`edit_file` 是整文件读写。

```text
大文件编辑时会一次性读入并重写整个文件。
```

第三，`run_command` 虽然 `cwd` 在 workspace，但命令本身仍然可能访问外部路径。

例如：

```text
python script.py /some/outside/path
```

如果底层命令自己访问外部文件，当前 Python 层不一定能拦住。

第四，当前 sandbox 是 Python 层的 policy gate，不是 OS 级隔离。

也就是说：

```text
policy 可以在执行 handler 前阻止某些工具。
但一旦允许 run_command，命令运行后的系统级行为不由这个 Python sandbox 完全控制。
```

这个要和第七部分连起来理解。

## 9. 重点难点总结

### 重点一：workspace tool 是真实副作用层

`workspace_tools.py` 不是 schema，也不是 policy。

它是：

```text
真正读写文件、执行命令的地方。
```

所以它的错误会直接影响真实项目文件。

### 重点二：路径必须 resolve 后再判断

不要只看原始字符串。

应该像当前代码这样：

```text
WORKSPACE_ROOT / path
-> resolve()
-> relative_to(WORKSPACE_ROOT)
```

这样才能防住一部分路径逃逸问题。

### 重点三：read_file 的 limit 是上下文保护

`offset` / `limit` 主要是为了控制：

```text
返回给 LLM 的内容大小。
```

它不是完整的大文件流式读取方案。

### 重点四：edit_file 必须要求 old 唯一

否则模型很容易误改。

当前实现的：

```text
count == 0 报错
count > 1 报错
count == 1 才替换
```

是一个很适合入门 coding agent 的保守策略。

### 重点五：run_command 不是完整 shell

虽然参数叫 `command`，但实际是：

```text
shlex.split(command) -> subprocess.run(argv, shell=False)
```

所以它更像：

```text
执行一个命令 argv
```

不是：

```text
打开一个 shell 解释整段脚本
```

### 重点六：工具能力要和 policy 接上

`read_file` / `edit_file` / `run_command` 分别声明：

```text
read / write / shell
```

这样 runtime 才能统一做权限检查。

如果没有 capability，policy 就不知道：

```text
这个工具到底算低风险读取，还是高风险执行命令。
```

### 重点七：编辑后验证现在还有改进空间

当前 `seen_tool_calls` 会阻止同一轮完全相同参数的重复调用。

这能防止模型无脑循环：

```text
read_file -> read_file -> read_file
```

但也可能挡住正常验证：

```text
read_file -> edit_file -> read_file
```

这是 workspace tools 进入 coding agent 阶段后很自然会暴露的问题。

## 10. 可以怎么改进

如果继续往主流 coding agent 靠，可以考虑这些方向：

1. `read_file` 改成按行读取，返回 `start_line` / `end_line`，更适合代码定位。
2. `edit_file` 返回替换后的局部预览，帮助模型确认结果。
3. duplicate 检测加入“工具调用是否有副作用之后”的上下文，允许编辑后重新读取同一文件。
4. `run_command` 支持显式 argv 参数，减少 `shlex.split` 带来的歧义。
5. 对 `run_command` 增加 allowlist 或 denylist，比如默认只允许 `python`、`pytest`、`rg` 等低风险命令。
6. 对大文件读取增加真正的流式读取，避免整文件进内存。
7. 对写操作增加 diff 预览，让用户审批时能看到具体修改。

## 11. 自检清单

学完这一部分，你应该能回答：

1. `WORKSPACE_ROOT` 是什么时候决定的？
2. 为什么路径检查要用 `resolve()` 和 `relative_to()`？
3. `read_file` 的 `offset` / `limit` 是按行还是按字符？
4. `read_file` 的 `limit` 防的是文件读入内存太大，还是返回给模型的内容太大？
5. 为什么 `edit_file` 要求 `old` 文本唯一？
6. `run_command` 里的 `shell=False` 有什么影响？
7. `run_command` 为什么仍然属于高风险工具？
8. `ToolSpec.capability` 和 `policy.py` 是怎么接起来的？
9. 为什么编辑后再次 `read_file({"path": "README.md"})` 可能被 duplicate 检测拦住？
10. `workspace_tools.py`、`tool_registry.py`、`tool_runtime.py`、`policy.py`、`state.py` 的边界分别是什么？
