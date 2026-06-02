# 第八部分：Skills

前面第七部分已经把工具执行加上了安全边界：

```text
LLM returns tool_call
-> tool_runtime.py 校验参数和权限
-> policy.py 决定 allow / ask / deny
-> Python handler 真正执行工具
```

第八部分开始，重点不是新增工具，而是新增一种更轻量的能力：

```text
不同任务，给 Agent 加载不同的工作方式。
```

一句话总结：

```text
Skill 是一份按需加载的过程说明。
它不直接执行代码，也不是长期记忆，而是在本轮对话开始时被选中，然后作为 system message 注入给主 LLM。
```

## 1. Skill 解决什么问题

没有 skill 之前，Agent 只有一个通用 system prompt：

```text
You are a helpful research agent.
Use tools when you need external information...
```

这个 prompt 适合做通用任务，但不同任务需要不同的回答策略。

例如：

```text
解释概念：
  先给一句话定义，再讲为什么存在，再给例子。

比较方案：
  先列出选项，再按几个维度比较，最后给建议。

实现指导：
  先明确目标，再拆步骤，再提醒边界。
```

如果把所有策略都塞进一个 system prompt，会有两个问题：

```text
1. prompt 越来越长，普通任务也要背上所有规则
2. 不同策略可能互相干扰，比如“解释概念”和“比较方案”的输出结构不同
```

所以 skill 的设计是：

```text
平时不加载。
只有当用户请求明显匹配某个 skill 时，才把那份 skill 内容放进上下文。
```

## 2. Skill 和 Tool / Memory 的区别

这三个东西很容易混在一起。

| 机制 | 作用 | 是否执行代码 | 是否跨运行保存 | 进入 LLM 的方式 |
|---|---|---|---|---|
| Tool | 让 Agent 做外部动作 | 是 | 否 | 通过 OpenAI tools schema |
| Long-term Memory | 保存用户明确要求记住的信息 | 写文件时执行工具 | 是 | 转成 system message |
| Skill | 改变本轮任务的工作方式 | 否 | skill 文件本身长期存在 | 转成 system message |

最关键的边界是：

```text
Tool 是 action。
Memory 是 remembered fact。
Skill 是 instruction。
```

所以 skill 不应该负责“搜索网页”“写文件”“计算结果”。

skill 负责的是告诉模型：

```text
这类任务应该怎样思考、怎样组织回答、怎样避免常见误区。
```

## 3. 当前 Skill 文件长什么样

当前 skill 放在 `skills/<skill-name>/SKILL.md`：

```text
skills/
  explain-concept/
    SKILL.md
  compare-options/
    SKILL.md
  implemetation-guide/
    SKILL.md
```

一个完整的 `SKILL.md` 分两部分：

```markdown
---
name: explain-concept
description: Use when the user asks what something is...
---

# Explain Concept

When explaining a concept:

1. Start with a short plain-language definition.
2. Explain why the concept exists.
3. Show how it fits into the current project or topic.
```

上面的 `--- ... ---` 是 frontmatter。

它的作用是给 router 看：

| 字段 | 作用 |
|---|---|
| `name` | skill 的稳定名字 |
| `description` | 告诉 router 什么时候该选它 |

下面的正文才是给主 LLM 看的具体过程说明。

## 4. 第一步：只发现 metadata

`skill_loader.py` 里先定义了两个数据结构：

```python
@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    path: Path

@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    content: str
```

这里故意分成 `SkillMeta` 和 `Skill`。

原因是：

```text
router 只需要知道有哪些 skill，以及它们分别适合什么任务。
router 不需要提前读取每个 skill 的完整正文。
```

所以 discovery 阶段只做轻量扫描：

```python
def discover_skill_metadata(skills_dir=SKILLS_DIR):
    if not skills_dir.exists():
        return []
    
    metas = []
    for path in sorted(skills_dir.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        meta, _ = parse_frontmatter(text)

        metas.append(SkillMeta(
            name=meta.get("name", path.parent.name),
            description=meta.get("description", ""),
            path=str(path),
        ))
    return metas
```

这个函数只返回：

```text
name
description
path
```

也就是说，它是在建立一份 skill 目录，而不是加载 skill 内容。

这里还有一个兜底设计：

```python
name=meta.get("name", path.parent.name)
```

如果 `SKILL.md` 没有写 `name`，就用文件夹名当 skill name。

## 5. Frontmatter 是怎么解析的

`parse_frontmatter(...)` 负责把 `SKILL.md` 拆成 metadata 和正文：

```python
parts = text.split("---", 2)
raw_meta = parts[1].strip()
body = parts[2].strip()
```

这里 `split("---", 2)` 的意思是：

```text
最多按 --- 切两次。
```

所以这种文本：

```text
---
name: explain-concept
description: Use when...
---

# Explain Concept
...
```

会被拆成：

```text
parts[0] = 开头空内容
parts[1] = name / description 这些 metadata
parts[2] = skill 正文
```

然后逐行解析 metadata：

```python
key, value = line.split(":", 1)
meta[key.strip()] = value.strip().strip('"').strip("'")
```

这行代码做了三件事：

```text
1. 只按第一个冒号切开，避免 description 里有冒号时被切坏
2. 去掉 key / value 两边空格
3. 去掉 value 首尾可能包着的单双引号
```

当前 parser 很轻量，只适合简单 frontmatter。

它不是完整 YAML parser，所以复杂嵌套结构不适合放在这里。

## 6. 第二步：router 选择一个 skill

`skill_router.py` 的入口是：

```python
select_skill_name(user_input, skill_metas, skill_router_llm)
```

它先把所有 skill metadata 整理成：

```python
available_skills = [
    {
        "name": meta.name,
        "description": meta.description,
    }
    for meta in skill_metas
]
```

然后单独调用一个 router LLM：

```python
message = skill_router_llm(messages)
```

这里要注意：

```text
router LLM 不回答用户问题。
router LLM 只判断要不要加载一个 skill。
```

所以它的 system prompt 写得很窄：

```text
Do not answer the user's request.
Return JSON only.
Choose at most one skill.
Only choose a name from available_skills.
Use null if no skill clearly applies.
```

最后 router 只返回两类结果：

```json
{"skill": null, "reason": "..."}
```

或者：

```json
{"skill": "explain-concept", "reason": "..."}
```

这一步的重点是：

```text
skill 选择本身也是一次 LLM 判断，但它被限制成一个很小的分类任务。
```

## 7. 第三步：只加载被选中的 skill

`agent.py` 里对应的流程是：

```python
skill_metas = discover_skill_metadata()
selected_skill_name, skill_reason = select_skill_name(
    user_input=user_input, 
    skill_metas=skill_metas, 
    skill_router_llm=skill_router_llm,
)
meta_by_name = {meta.name: meta for meta in skill_metas}
if selected_skill_name in meta_by_name:
    active_skill = load_skills(meta_by_name[selected_skill_name])
```

这段代码体现了完整顺序：

```text
1. discover_skill_metadata()
   扫描所有 skill 的 name / description

2. select_skill_name(...)
   让 router 选择一个 skill name 或 null

3. load_skills(...)
   只读取被选中的那个 SKILL.md 正文
```

这比“一开始加载所有 skill 正文”更干净：

```text
router 阶段轻量。
主模型阶段只看到真正相关的 skill。
```

## 8. 第四步：把 skill 注入主模型上下文

skill 被选中以后，不会直接改变 Python 的执行逻辑。

真正让它生效的是 `context_manager.py`：

```python
def make_skill_message(skill):
    return {
        "role": "system",
        "content": (
            "Active skill / process instructions:\n"
            f"## {skill.name}\n"
            f"Description: {skill.description}\n"
            f"Source: {skill.path}\n\n"
            f"{skill.content}"
        ),
    }
```

然后在构造 model messages 时：

```python
context_messages = [system_message]

if skill is not None:
    context_messages.append(make_skill_message(skill))

context_messages.extend([
    make_state_message(state),
    make_memory_message(memories),
])
```

最终发给主 LLM 的结构变成：

```text
system prompt
+ active skill system message
+ current state system message
+ long-term memories system message
+ recent protocol-safe messages
```

这里 skill 的位置很重要。

它放在主 system prompt 后面、state / memory 前面，意思是：

```text
先告诉模型通用身份和工具原则。
再告诉模型本轮任务应该采用哪种工作方式。
再补充当前状态和长期记忆。
最后给最近对话历史。
```

## 9. Skill selection 也被写入 thread

`agent.py` 还会把选择结果写进 thread item：

```python
append_item(
    thread_id,
    turn_id,
    "skill_selection",
    {
        "selected": selected_skill_name,
        "reason": skill_reason,
        "skill": (
            {
                "name": active_skill.name,
                "description": active_skill.description,
                "path": active_skill.path,
            }
        ) if active_skill else None,
    },
)
```

这一步不是给模型看的，而是给调试和回放看的。

当回答风格不符合预期时，可以查看 thread 记录：

```text
这一轮到底选了哪个 skill？
为什么选它？
有没有本来应该选 skill，但 router 返回了 null？
```

你当前的测试记录里已经能看到这种 item：

```json
{
  "type": "skill_selection",
  "data": {
    "selected": null,
    "reason": "The user is asking for the current time..."
  }
}
```

这说明即使没有选中 skill，系统也会留下原因。

## 10. 当前实现的主链路

把所有文件串起来，完整路径是：

```text
main.py
  -> run_agent(..., skill_router_llm=call_llm_plain)

agent.py
  -> discover_skill_metadata()
  -> select_skill_name(...)
  -> load_skills(...)
  -> append_item(type="skill_selection")

context_manager.py
  -> build_model_messages(..., skill=active_skill)
  -> make_skill_message(active_skill)

llm.py
  -> call_llm(model_message)
```

更直观地看：

```text
User input
-> Skill discovery
-> Skill router LLM
-> selected skill name or null
-> load selected SKILL.md
-> inject as system message
-> Main LLM answers or calls tools
```

这里有两个 LLM 调用：

| 调用 | 使用位置 | 目的 | 输出 |
|---|---|---|---|
| Router LLM | `skill_router.py` | 选择 skill | JSON |
| Main LLM | `agent.py` 主循环 | 回答用户 / 调用工具 | assistant message |

这个分工很重要：

```text
router LLM 负责分类。
main LLM 负责执行任务。
```

## 11. 当前实现里最值得记住的点

第一，skill 是 prompt-level 能力，不是 tool-level 能力。

```text
它改变模型怎么回答，不负责执行动作。
```

第二，skill 是按需加载的。

```text
先只扫描 metadata，选中以后才加载正文。
```

第三，router 的输入应该小而清楚。

```text
给 router 的是 user_input + available_skills。
不要把完整对话历史、state、memory 都塞给 router。
```

第四，description 很关键。

```text
router 是根据 name 和 description 选择 skill 的。
如果 description 为空，这个 skill 基本很难被稳定选中。
```

所以当前 `skills/implemetation-guide/SKILL.md` 如果要投入使用，最好补上 frontmatter：

```markdown
---
name: implementation-guide
description: Use when the user asks how to implement a feature, build a module, or break an engineering task into concrete steps.
---
```

第五，skill selection 需要留痕。

```text
thread 里记录 selected / reason / skill path，可以帮助你判断 router 有没有选错。
```

## 12. 和前面几部分的关系

到第八部分为止，Agent 的层次可以这样理解：

```text
第一部分 Agent Loop
  让程序能一轮轮调用 LLM

第二部分 Tool Calling
  让 LLM 能请求 Python 执行工具

第三部分 State
  让一次任务里的中间结果有地方放

第四部分 Long-term Memory
  让用户明确要求记住的信息跨运行保存

第五部分 Context Manager
  决定每次 LLM 调用到底带哪些上下文

第六部分 Tool Registry / Runtime
  把工具定义和工具执行从 agent.py 拆出去

第七部分 Policy / Sandbox
  在真正执行工具前加权限和审批边界

第八部分 Skills
  根据用户请求按需加载任务过程说明
```

所以 skill 的位置不是替代前面的任何一层。

它是在 context manager 这一层增加一份新的 system context：

```text
system prompt
+ selected skill
+ state
+ memory
+ recent messages
```

最终得到的是一个更接近真实 Codex / ChatGPT 工作方式的结构：

```text
不是所有规则都常驻。
而是根据当前任务，动态选择需要加载的 instructions。
```
