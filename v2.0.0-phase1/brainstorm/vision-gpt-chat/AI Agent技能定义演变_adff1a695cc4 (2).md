<!-- gpt-chat-meta:start -->
> [!info] GPT Chat 时间信息
> - 时间顺序：02 / 10（按 JSON `create_time` 升序）
> - 标题：AI Agent技能定义演变
> - 创建时间：2026-06-04 07:39:08 CST
> - 更新时间：2026-06-04 07:44:09 CST
> - Conversation ID：`6a20bb12-dc64-83ea-97e6-adff1a695cc4`
> - 来源：同名 JSON 顶层时间字段；JSON 已在本次整理后删除。
<!-- gpt-chat-meta:end -->

# User
AI Agent的skill指的是什么？有没有相对早期的定义以及可复现的代码仓库使用？

# Assistant
“Skill（技能）”在 AI Agent 领域其实是个被反复重新定义过的词，不同论文、框架和社区说的根本不是一回事。

如果从发展脉络看，大概经历了三个阶段：

---

# 第一阶段：强化学习里的 Skill（2016-2021）

最早的 Skill 概念其实不是 Agent，而是 RL。

这里 Skill≈Option≈Macro Action。

来自经典的：

- Reinforcement Learning
- Options Framework

一个 skill 是：

```text
打开门
走到目标点
拿起物体
```

而不是：

```text
向左移动一步
转头5°
```

即：

```text
primitive action
↓
skill
↓
task
```

典型工作：

- Option-Critic
- DIAYN
- VALOR
- DADS

这些工作研究：

> Agent能不能自己发现skill？

例如：

```text
skill_1 = 探索房间
skill_2 = 沿墙移动
skill_3 = 穿过门
```

甚至没人告诉它这些技能是什么。

---

# 第二阶段：Tool Use时代（2022-2023）

随着GPT出现。

Skill开始变味。

在这个时期：

```text
Skill ≈ Tool
```

例如：

```python
search()
calculator()
weather()
```

都被叫做skill。

典型项目：

### AutoGPT

[AutoGPT](https://github.com/Significant-Gravitas/AutoGPT?utm_source=chatgpt.com)

里面实际上：

```text
skill:
    google search

skill:
    file write

skill:
    browse website
```

---

### BabyAGI

[BabyAGI](https://github.com/yoheinakajima/babyagi?utm_source=chatgpt.com)

开始提出：

```text
Task
↓
Skill
↓
Execution
```

但依然很粗糙。

Skill就是函数调用。

---

# 第三阶段：Agent Skill Library（2023-2024）

真正把 Skill 重新定义的是一些 Agent Learning 工作。

代表：

### Voyager

[Voyager Project](https://github.com/MineDojo/Voyager?utm_source=chatgpt.com)

这是Minecraft Agent。

它把 Skill 定义成：

```text
可复用程序
```

例如：

```python
def mine_iron():
    ...
```

Agent完成任务后：

```text
挖铁
```

被存进Skill Library。

下次需要铁：

```text
retrieve skill
```

直接调用。

这是第一次把：

```text
经验
→
代码
→
技能
```

连接起来。

---

Voyager架构：

```text
LLM
    ↓
Task
    ↓
Code Generation
    ↓
Execution
    ↓
Skill Extraction
    ↓
Skill Library
```

这已经很接近现代Agent。

---

# 第四阶段：Embodied Agent Skill（2024-现在）

机器人领域进一步抽象。

Skill不再是代码。

而是：

```text
State -> State
```

变换器。

例如：

```text
桌上有杯子
↓
pick_up_cup
↓
手里有杯子
```

一个skill定义：

```text
precondition

effect

controller
```

类似：

```text
PDDL Action
```

或者：

```text
STRIPS Operator
```

这时候skill变成：

```text
可组合能力模块
```

---

# 现在Agent社区最常见的Skill定义

如果你看：

- LangGraph
- OpenAI Agents SDK
- CrewAI
- MetaGPT
- OpenHands

大家嘴上说Skill时通常指：

```text
一个可调用能力
```

形式可能是：

```python
class Skill:
    name
    description
    input_schema
    output_schema
    executor
```

例如：

```python
SearchSkill

CodingSkill

SQLSkill

BrowserSkill
```

本质上：

```text
Skill
=
Tool
+
Prompt
+
Execution Logic
```

---

# 你提到的“微调System Prompt”的Skill

这个其实特别有意思。

因为它对应的是最近Agent研究里的一个新方向：

```text
Skill ≠ Tool
Skill = Prompt Fragment
```

例如：

```text
如何写Verilog

如何调试FPGA

如何Review代码
```

被存成：

```text
Prompt Template
```

需要时插回Context。

类似：

```text
Memory Retrieval
+
Prompt Composition
```

而不是调用函数。

---

这实际上和 Voyager 很像：

Voyager：

```text
Skill = Code
```

你设想的是：

```text
Skill = Prompt
```

进一步抽象甚至可以写成：

```text
Skill
=
(Context Transformer)
```

输入：

```text
当前任务
```

输出：

```text
更好的System Prompt
```

所以：

```text
Task
    ↓
Skill Retrieval
    ↓
Prompt Augmentation
    ↓
LLM
```

这已经很接近很多人在做的：

- Prompt-based Skill Learning
- Agent Procedure Learning
- Dynamic System Prompting

只是还没有形成统一术语。

---

# 如果你想找“最早且能跑起来”的Skill系统

我建议按这个顺序读：

1. [Voyager GitHub](https://github.com/MineDojo/Voyager?utm_source=chatgpt.com)
   - Skill Library经典实现
   - Agent学会后保存技能

2. [BabyAGI GitHub](https://github.com/yoheinakajima/babyagi?utm_source=chatgpt.com)
   - 最早的Task→Skill风格

3. [LangGraph Documentation](https://langchain-ai.github.io/langgraph/?utm_source=chatgpt.com)
   - 现代Agent workflow

4. [OpenHands GitHub](https://github.com/All-Hands-AI/OpenHands?utm_source=chatgpt.com)
   - 实际工程Agent

5. [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/?utm_source=chatgpt.com)
   - 当代Tool/Skill抽象

结合你前面提到的想法——“把任务切成臊子粒度，然后做类似MoE的skill检索”——我觉得最接近的不是传统Tool Calling，而是：

```text
Skill
=
一个小粒度Prompt程序
```

即：

```text
skill:
    HDL代码审查

skill:
    Verilog时序分析

skill:
    FPGA资源估算

skill:
    CDC检查
```

运行时：

```text
Task
    ↓
Retriever
    ↓
Top-K Skills
    ↓
拼接System Prompt
    ↓
LLM
```

这比把 Skill 做成 Python Tool 更轻，也更容易自动优化和蒸馏。而且从你之前说的“端口是节点、逻辑是边”的 graph 视角来看，Skill 甚至可以被看成图上的一个局部子图变换规则，而不是一个函数。那样的话，它会更接近“可检索的推理模式库”而不是传统工具库。

# User
我现在是又有点想用LG写一个，又想自己搓，因为这样相对轻量一点。

# Assistant
其实这两个方向对应的是两种完全不同的目标。

如果你的目标是：

> 我想验证“Skill = Prompt Fragment / Context Transformer”这个想法是否成立

那我反而建议先自己搓。

因为你会很快发现，LangGraph 这种框架自带的很多东西：

```text
State
Node
Edge
Checkpoint
Persistence
Human-in-the-loop
Tool Runtime
```

在你的实验初期根本不是核心问题。

你的核心问题其实只有三个：

```text
Skill如何表示

Skill如何检索

Skill如何组合
```

甚至最小系统可以简单到：

```python
class Skill:
    name: str
    desc: str
    prompt: str
```

然后：

```python
skills = retrieve(task)

system_prompt = """
You are an assistant...
""" + "\n".join(skill.prompt for skill in skills)
```

结束。

可能连200行代码都不到。

---

我觉得你现在这个方向有个特别有意思的地方：

你实际上不像大部分 Agent 项目。

大部分 Agent：

```text
Task
↓
Planner
↓
Tool Call
↓
Result
```

而你更像：

```text
Task
↓
Skill Retriever
↓
Prompt Composer
↓
LLM
```

Agent本体几乎没有Tool。

Skill才是重点。

---

实际上这有点像：

### RAG for Behavior

普通RAG：

```text
Query
↓
Retrieve Knowledge
↓
LLM
```

你的系统：

```text
Task
↓
Retrieve Skills
↓
LLM
```

检索的不是知识。

而是：

```text
解决问题的方法
```

---

所以我甚至怀疑你第一版根本不需要 LangGraph。

直接：

```text
Task
↓
Embedding
↓
Vector Search
↓
Top-K Skills
↓
Prompt Assembly
↓
LLM
```

就够了。

---

而且有个工程上经常被低估的问题：

LangGraph一旦上来，你会开始思考：

```text
Node怎么设计

State怎么设计

Graph怎么切

消息怎么传

Checkpoint怎么存
```

然后三天过去了。

Skill系统还没开始写。

这属于典型的：

```text
Infrastructure before Validation
```

先修高速公路，再确认有没有车要开。

---

我甚至觉得你现在可以把 Skill 存成 Markdown：

```markdown
# HDL_CDC_CHECK

## Description

Check clock domain crossing issues.

## Trigger

cdc
clock crossing
async

## Prompt

When reviewing Verilog:

1. Check ...
2. Check ...
3. Check ...
```

目录：

```text
skills/
    cdc.md
    timing.md
    lint.md
    synthesis.md
```

然后：

```python
retrieve()
```

直接 BM25 或 embedding。

---

等你发现：

```text
100 skills
↓
开始有依赖关系

开始有版本

开始有冲突

开始有组合逻辑
```

这时候再引入 LangGraph。

你会很自然得到：

```text
Skill Node
↓
Skill Graph
↓
Execution Graph
```

而不是为了用 LangGraph 去找问题。

---

更进一步说，从你前面聊的想法来看，我甚至怀疑最终形态不会是 LangGraph 那种 DAG。

因为你一直在强调：

```text
小粒度
MOE
Graph
```

这更像：

```text
Task
↓
Skill Retrieval
↓
Skill Routing
↓
Skill Composition
↓
Prompt
```

其中 Skill 之间的关系可能是：

```text
A -> B

A -> C

B + C -> D
```

本身就是一个动态图。

这反而更接近神经网络里的：

```text
Mixture of Experts
```

或者编译器里的：

```text
Pass Pipeline
```

而不是传统 Agent Workflow。

所以如果是我做这个实验，我会：

```text
Phase 1
--------
纯Python
Skill = Markdown
Skill Retrieval

Phase 2
--------
Embedding
Skill Ranking

Phase 3
--------
Skill Dependency Graph

Phase 4
--------
自动生成Skill
自动评估Skill
```

前三阶段加起来可能都不到1000行代码。

等真的证明这套东西有效，再考虑把 LangGraph 当运行时接进来。现在就上框架，大概率是在优化一个还没被验证存在的问题。

# User
我给你先看看我们的描述文档，这套东西其实已经有点像coding agent了但是是HDL特化的

# Assistant
可以，直接发过来。

我建议最好发下面几种之一：

```text
README

设计文档

架构图（Mermaid也行）

Skill定义文档

Prompt模板

Workflow描述
```

我重点会看几个东西：

### 1. Skill到底是什么

因为这是整个系统最关键的地方。

比如我会看你们的 Skill 更接近：

```text
Tool
```

还是

```text
Prompt
```

还是

```text
Procedure
```

例如：

```yaml
skill:
  name: write_testbench
  trigger:
    - testbench
  prompt: ...
```

这种是 Prompt Skill。

---

而：

```yaml
skill:
  name: run_verilator
  command: verilator ...
```

这种实际上是 Tool。

---

或者：

```yaml
skill:
  precondition:
    - rtl_ready

  steps:
    - generate_tb
    - run_sim
    - analyze_wave
```

这种已经是 Procedure Skill。

---

### 2. Skill粒度

这个是决定系统上限的。

我会看你们是在：

```text
Generate RTL
```

这种大粒度。

还是：

```text
Infer FSM
Generate FSM Skeleton
Check State Encoding
Generate Transition Logic
```

这种小粒度。

从你前面说的「切成臊子」来看，我猜你们已经偏后者了。

如果真是这样，那它会比较像：

```text
HDL Expert MOE
```

而不是传统 Coding Agent。

---

### 3. Graph到底是什么

你之前提到过一句让我很在意：

> 端口是节点，逻辑是边

这其实不是普通Agent的Workflow Graph。

更像：

```text
Circuit Graph
```

或者：

```text
IR Graph
```

如果Skill是在Graph上工作的：

```text
Graph
 ↓
Skill A
 ↓
Graph
 ↓
Skill B
 ↓
Graph
```

那它其实已经开始接近EDA里的：

```text
Pass
```

概念了。

我会特别关注这部分。

---

### 4. Skill是静态的还是会成长

这是Voyager路线和普通Agent路线的分水岭。

比如：

```text
Skill Library
```

是否会：

```text
新增Skill

修改Skill

淘汰Skill

合并Skill
```

如果会的话。

那其实已经进入：

```text
Agent Learning
```

范畴了。

而不是单纯Workflow。

---

### 5. 为什么不用现成Coding Agent

这个问题其实很重要。

因为如果我看完文档发现：

```text
OpenHands
+
Verilator
+
Yosys
```

也能做。

那说明你们做的是工程封装。

---

但如果发现：

```text
HDL表示
↓
Graph
↓
Skill Routing
↓
RTL Generation
↓
Verification Loop
```

里面有独特的表示层。

那就是新东西了。

---

发过来以后我会尽量从：

```text
Agent Architecture

Skill System

EDA视角

可扩展性

是否值得自己搓而不是LangGraph
```

几个角度一起看。

我怀疑你们这个东西未必属于现在社区理解的 Agent，更有可能是在往“HDL领域专用推理运行时（Reasoning Runtime）”那个方向长。这个差别其实挺大的。

# User
# ICU-MUJICA v2 skill version
### ICU-MUJICA (Integrated Circuit Unified - Multi-skill Unified Joint IC Automatic)
---
## v2 版本说明
- 少女乐队堂堂开启续集！
- 放弃 v1 版本的多 docker 和多 agent 设计
- 采用单个 LLM 配合定义明确的 skill 定义和结构清晰、模块化的工作流设计实现前端设计、仿真和后端参与的全流程自动化
---
## v2 开发主线
- 明确采用 Harness + Skill 的 SOTA
- 分析和运行过程相互独立且采用多轮对话
---
## v2 版本预期达成目标
- 截至 2026/6/3 的预期目标，先梦这么多吧！
- 实现 Zero-Shot 全栈开发，解放前端，后端能跑
- 支持自定义的 RAG 知识库，方便引用已有测试数据 & 支持自主维护数据处理与写入
- 可自我迭代的 skill 设置，方便针对模型调整以获得最佳性能
---
## v2.0.0 文件目录架构（计划构成）
```
ICU-MUJICA
|- src                - 源码存放
|  |- common          - 共享类型（skill 统一化协议模型、pydantic 检查类型）
|  |- skill           - 智能体 skill 目录
|  |- workflow        - 智能体原子化工作流目录
|- workspace          - 智能体 active 态下工作空间
|- output             - 文件输出目录
|  |- frontend        - 前端输出（架构图、RTL等）
|  |- backend         - 后端输出（报告、网表等）
|- docker_compose.yml
|- requirements.txt
```
---
## 技术栈选择
| 维度 | 选型 | 作用 |
| :--- | :--- | :--- |


嗯对，这版东西基本等于重新开始搓，所以我也没有头绪

# Assistant
看完这段以后，我最大的感受其实不是“没头绪”，而是：

**你们现在缺的不是代码，而是抽象层。**

因为这里已经能看出几个很明确的方向。

---

## 我看到的东西

v1：

```text
Agent A
Agent B
Agent C
Docker A
Docker B
Docker C
```

属于 2023-2024 年很流行的：

```text
Multi-Agent Everything
```

路线。

---

v2：

```text
Single LLM
+
Skill
+
Workflow
```

开始往：

```text
Compiler
```

路线走了。

这个转向其实很有意思。

因为 HDL 开发天然不像写 Python。

普通 Coding Agent：

```text
需求
↓
生成代码
↓
运行
↓
修
```

就结束了。

---

但 HDL：

```text
Spec
↓
Architecture
↓
RTL
↓
TB
↓
Simulation
↓
Lint
↓
Synthesis
↓
Timing
↓
Backend
```

本身就是流水线。

所以 HDL Agent 更像：

```text
Compiler Pipeline
```

而不是：

```text
Chat Agent
```

---

## 我最喜欢的一句话

这里：

```text
分析和运行过程相互独立且采用多轮对话
```

其实非常关键。

因为这说明你已经意识到：

```text
Reasoning
≠
Execution
```

这是很多 Agent 项目踩坑的地方。

---

如果是我。

我甚至会明确拆成：

```python
AnalysisPhase

ExecutionPhase
```

---

Analysis：

```text
读需求

分析模块

确定接口

确定时序

确定验证策略
```

输出：

```json
{
  "module": "...",
  "ports": [...],
  "architecture": "...",
  "verification_plan": "..."
}
```

---

Execution：

```text
生成RTL

生成TB

跑仿真

修BUG
```

---

这样你得到：

```text
Spec
↓
Plan
↓
Implementation
```

而不是：

```text
Spec
↓
RTL
```

---

## 我觉得最大的风险

是 skill 和 workflow 的边界。

你目前目录：

```text
skill/
workflow/
```

但还没定义两者区别。

---

如果不定义。

最后一定会出现：

```text
generate_rtl.py

generate_tb.py

run_sim.py
```

全部跑到 skill 里面。

workflow 变空壳。

---

我建议一开始就规定：

### Skill

只能干一件事

输入输出固定

例如：

```python
InferPortsSkill

GenerateFSMSkill

AnalyzeWaveformSkill

ExtractTimingViolationSkill
```

---

### Workflow

负责组合 skill

例如：

```text
RTL_FLOW

Architecture
↓
Port Inference
↓
RTL Generation
↓
Lint
```

---

即：

```text
Skill = Operator

Workflow = DAG
```

---

## 我觉得你们最值得投入的地方

不是 Skill。

而是：

```text
Skill Protocol
```

---

例如统一格式：

```python
class SkillResult(BaseModel):
    success: bool

    summary: str

    artifacts: list[str]

    next_actions: list[str]

    confidence: float
```

---

每个 skill：

```python
class Skill:
    name
    description

    input_schema
    output_schema

    execute()
```

---

这样未来：

```text
GenerateRTLSkill

GenerateTBSkill

RunSimulationSkill
```

都能插进去。

---

## 一个我觉得很像 HDL 的设计

其实我甚至不喜欢：

```text
workflow/
```

这个名字。

---

因为你们做的是 IC。

更像：

```text
passes/
```

---

EDA 人会立刻懂：

```text
Pass 1
Architecture

Pass 2
RTL

Pass 3
Verification

Pass 4
Synthesis
```

---

类似：

```text
LLVM Pass

Yosys Pass
```

---

于是系统变成：

```text
Task
↓
Pass Manager
↓
Skill Router
↓
Artifacts
```

---

这个抽象和 HDL 非常契合。

---

## 如果是我今天开始搓 v2

第一周我甚至不会碰 LangGraph。

直接：

```text
src/

common/
    skill.py
    artifact.py

skills/
    infer_ports.py
    generate_rtl.py
    generate_tb.py

passes/
    frontend_flow.py
```

---

先把：

```text
需求
↓
RTL
↓
TB
↓
iverilog
```

跑通。

---

等到出现：

```text
20+
skills

10+
workflow

复杂依赖
```

再考虑：

```text
LangGraph

NetworkX

DAG Runtime
```

---

从你这份文档透露出来的信息看，我觉得 ICU-MUJICA v2 最终很可能不会长成 OpenHands 那种 Coding Agent。

它更像：

```text
HDL Compiler
+
LLM Passes
+
Skill Library
```

如果沿着这个方向走，很多设计决策会突然变得清晰：

- Skill ≈ Pass Operator
- Workflow ≈ Pass Pipeline
- Artifact ≈ IR
- Workspace ≈ Build Directory
- RAG ≈ Design Database

而且这套抽象和 FPGA/EDA 的思维方式天然一致，不需要硬往 LangGraph 那套 Agent Workflow 上靠。
