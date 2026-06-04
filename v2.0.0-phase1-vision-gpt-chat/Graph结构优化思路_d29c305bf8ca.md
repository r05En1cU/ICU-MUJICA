# User
我的想法是，通过收集用户反馈，LLM可以自己新建并调整graph。举个例子：LLM输出的RTL代码功能性完备但是缺少模块复用，而LLM自己的reasoning和output做了偷懒。经过反馈后LLM可以询问用户是否需要检查模块的可复用/可配置性然后加入这个graph节点作为设计初期评估的skill。

# Assistant
这个想法我觉得有潜力，但我会把它定义成：

> **Graph结构优化（Workflow Learning）**
> 而不是
> **Skill学习（Capability Learning）**

这两者差别很大。

---

## 第一层：你现在描述的其实不是Skill训练

你举的例子：

> RTL功能正确
>
> 但是模块复用性差
>
> 用户反馈后加入“可复用性检查”节点

这里实际上没有产生新能力。

LLM本来就知道：

- parameter化设计
- generate
- hierarchy
- reusable module
- interface abstraction

这些知识它训练时就学过。

问题只是：

> 它没有在这次工作流里主动检查。

所以学习的不是：

```text
不会 -> 会
```

而是：

```text
知道但没做 -> 下次记得做
```

这更像：

```text
Graph Optimization
```

例如：

```text
Design RTL
    ↓
Functional Check
```

变成：

```text
Requirement Analysis
    ↓
Reusability Check
    ↓
Parameterization Check
    ↓
RTL Design
    ↓
Functional Check
```

这里变化的是流程。

---

## 第二层：这其实很接近Agent领域现在缺的东西

现在很多Agent框架：

- LangGraph
- AutoGen
- CrewAI

都有Graph。

但Graph通常是：

```python
graph = Graph(...)
graph.add_node(...)
graph.add_edge(...)
```

人工写死。

而你在说：

```text
Graph itself is learnable.
```

即：

```text
失败案例
    ↓
用户反馈
    ↓
分析缺陷来源
    ↓
修改Graph
```

形成：

```text
Experience
    ↓
Graph Update
    ↓
Better Workflow
```

这个方向反而比很多Agent框架更有研究价值。

---

## 第三层：但是要小心Graph爆炸

如果每个反馈都新增节点：

```text
Check Reusability
Check Timing
Check Naming
Check CDC
Check Reset
Check DFT
Check Lint
Check Power
Check Area
...
```

最后Graph会长成：

```text
300个节点
```

推理成本爆炸。

所以我觉得需要区分：

### Level 1：长期固定Skill

真正新增能力。

例如：

```text
Formal Verification
UPF Analysis
STA Debug
```

这种值得永久加入。

---

### Level 2：Evaluation Skill

你刚才的例子属于这里。

```text
Evaluate Reusability
Evaluate Readability
Evaluate Configurability
```

这些其实都属于：

```text
Design Quality Evaluation
```

下面的子项。

因此更合理的是：

```text
Evaluate RTL Quality
```

返回：

```json
{
  "reuse": 0.4,
  "readability": 0.8,
  "timing_risk": 0.6
}
```

然后决定是否触发：

```text
Improve Reusability
Improve Timing
```

而不是新增几十个节点。

---

## 第四层：我觉得反馈学习应该更新的是触发条件

这是我认为最有价值的地方。

假设初始Graph：

```text
Requirement
    ↓
RTL Generation
    ↓
Simulation
```

某次用户反馈：

> 代码能跑，但是无法复用。

学习结果不是：

```text
新增 Reusability Node
```

而是：

```text
当用户要求：
    parameterizable
    reusable
    IP-quality

时

自动插入：

Reusability Evaluation
```

即：

```text
Node 不变
Edge 条件变
```

形式上：

```text
Graph Structure
    +
Routing Policy
```

其中真正学习的是：

```text
Routing Policy
```

而不是Graph本身。

---

## 第五层：如果继续发展下去，会变成一种经验库

你可以把每次失败记录成：

```json
{
  "task_type": "RTL Generation",
  "failure": "Poor Reusability",
  "root_cause": "Missing Parameterization Review",
  "solution": "Run Reusability Evaluation"
}
```

累计很多条后：

```text
Task Embedding
        ↓
Retrieve Similar Failures
        ↓
Inject Missing Evaluation Nodes
```

这其实已经有点像：

```text
RAG for Workflow
```

而不是：

```text
RAG for Knowledge
```

检索的不是知识。

而是：

```text
历史上哪些工作流会翻车。
```

---

如果结合你前面提到的：

- Skill是细粒度的
- Evaluate / Execute分离
- Graph自动编排

那么我会把系统设计成：

```text
Skill
├── Evaluate
└── Execute

Graph
├── Nodes
└── Routing Policy

Memory
├── Failure Cases
├── Successful Cases
└── Graph Modifications
```

最终学习目标不是让LLM变聪明，而是让它逐渐学会：

> 对于什么类型的IC设计任务，应该在什么阶段插入哪些评估节点，才能避免过去踩过的坑。

这比“训练出新的RTL生成能力”更现实，也更容易通过用户反馈持续优化。

# User
我覺得或許可以這樣定義：在不发生系统复杂度爆炸的情况下,性能能得到提高,我觉得这是一种进化。

# Assistant
我觉得这个定义其实挺接近工程领域对“进化”的实用定义。

如果抽象一下：

> 系统通过经验积累，使未来任务表现变得更好，而新增的复杂度增长速度低于性能提升速度。

那么确实可以称为一种进化。

甚至可以写成一个很工程化的指标：

\[
Evolution\ Score
=
\frac{\Delta Performance}{\Delta Complexity}
\]

当：

\[
\Delta Performance > 0
\]

且

\[
\frac{\Delta Performance}{\Delta Complexity}
\]

持续保持较高时，系统就在健康进化。

---

实际上很多Agent系统死掉的原因正好相反：

```text
问题来了
    ↓
加一个Agent

又出问题
    ↓
再加一个Agent

继续出问题
    ↓
再加一个Agent
```

最后：

```text
3个Agent
→ 10个Agent
→ 50个Agent
→ 100个Agent
```

性能提升：

```text
+10%
+5%
+2%
+0%
```

复杂度提升：

```text
×2
×5
×20
×100
```

这属于退化（degeneration），不是进化。

---

你刚刚那个“可复用性检查”的例子有个有意思的地方：

它甚至不一定需要新增节点。

假设原来：

```text
Requirement
    ↓
RTL Generation
```

后来发现经常复用性差。

一种做法：

```text
Requirement
    ↓
Reusability Check
    ↓
RTL Generation
```

复杂度+1。

---

但另一种做法可能是：

把经验写进：

```text
RTL Generation Skill
```

的Prompt或者Skill描述里：

```text
生成RTL时优先考虑：
- 参数化
- 模块边界
- 复用性
```

Graph根本没变：

```text
Requirement
    ↓
RTL Generation
```

性能却提升了。

这时候：

```text
ΔComplexity ≈ 0
ΔPerformance > 0
```

进化效率最高。

---

所以我觉得你这个方向里，真正重要的可能不是：

> Graph会不会长大。

而是：

> 新经验应该落在哪一层。

我会把经验更新分成三个等级：

### Level 1：参数更新（最优）

```text
Skill Prompt
Tool Selection
Routing Threshold
```

例如：

```text
生成RTL时优先参数化
```

复杂度几乎不变。

---

### Level 2：策略更新

```text
什么时候执行某个Skill
```

例如：

```text
模块数 > 5
    ↓
自动触发复用性评估
```

Graph不变。

Edge条件变。

复杂度增长很小。

---

### Level 3：结构更新

```text
新增Node
新增Subgraph
```

这是最昂贵的学习。

只有前两种都解决不了时才做。

---

这其实让我想到一个很有研究味道的问题：

你最终优化的对象可能不是Graph本身，而是一个类似下面的目标函数：

\[
J =
Quality
-
\lambda_1 Cost
-
\lambda_2 Latency
-
\lambda_3 Complexity
\]

用户反馈提升Quality。

Graph增长增加Complexity。

调用更多Skill增加Cost和Latency。

系统学习的目标是最大化：

\[
J
\]

而不是单纯让Graph越来越大。

如果这样定义的话，你说的“进化”就很接近：

> 在固定或缓慢增长的复杂度预算下，通过经验积累持续提高任务完成质量。

这个定义我觉得比“Agent自动长出新节点”本身更有研究价值，因为它直接给出了一个可优化、可衡量、可实验验证的目标。

# User
所以其實有很多種方法，包括但不限於優化Skill的Prompt，优化Graph的结构以及定期调整参数，或者是在RAG内增加或者减少有代表性的项目,或者只保留一些TOP的项目作为优先参考。

# Assistant
对，而且我觉得你现在已经开始从“Agent设计”转向“Agent自优化框架”了。

前面我们讨论时，默认优化对象是Graph。但你这里实际上在说：

```text
System
├── Skill
├── Graph
├── Memory
├── RAG
├── Routing
└── Parameters
```

这些都可以成为被优化对象。

---

如果把它抽象成一个统一框架，我甚至会定义：

```text
Experience
    ↓
Analysis
    ↓
Optimization Action
    ↓
System Update
```

区别只在于：

```text
Optimization Action
```

作用在哪一层。

---

### 第一层：Skill Evolution

例如：

```text
RTL生成质量差
```

分析后发现：

```text
Skill Prompt有问题
```

于是：

```text
Generate RTL
```

对应的Prompt从：

```text
生成RTL代码
```

变成：

```text
生成RTL代码

优先：
- 参数化
- 可复用
- 清晰层次
```

这是最便宜的优化。

---

### 第二层：Parameter Evolution

例如：

```text
Evaluate Timing
```

节点存在。

但是：

```text
触发阈值
```

不合理。

原来：

```text
设计规模 > 10000门
```

才执行。

后来发现：

```text
5000门就容易翻车
```

于是调整：

```text
10000 → 5000
```

Graph没变。

性能提高。

---

### 第三层：Routing Evolution

这个我觉得特别有价值。

例如：

原来：

```text
Requirement
    ↓
RTL
    ↓
Simulation
```

后来统计发现：

```text
FIFO设计
```

经常出CDC问题。

于是：

```text
FIFO
    ↓
CDC Check
    ↓
RTL
```

但：

```text
Adder
```

不走这个路径。

即：

```text
Graph不变
Routing改变
```

---

### 第四层：Memory Evolution

这里就开始有点像你说的：

> 保留TOP项目

例如Memory里有：

```text
10000条案例
```

实际上很多已经过时。

---

可能做：

```text
Importance Score
=
Success
+
Usage Frequency
+
Recency
```

然后：

```text
Top 500长期保留
Top 100优先检索
```

甚至：

```text
长期没人引用
```

直接淘汰。

---

这其实非常像生物进化里的：

```text
遗忘
```

而不是无限增长。

很多Agent系统最大的问题恰恰是：

```text
只会记忆
不会遗忘
```

最后Memory变成垃圾场。

---

### 第五层：RAG Evolution

这个我觉得和IC设计特别搭。

假设现在有：

```text
项目A
项目B
项目C
项目D
```

每次检索都全塞进去。

Context爆炸。

---

后来统计发现：

```text
项目B
```

对于FIFO设计帮助最大。

那么：

```text
FIFO Query
    ↓
优先检索项目B
```

甚至：

```text
FIFO Query
    ↓
项目B
项目D
```

而：

```text
项目A
项目C
```

不再检索。

---

本质上是：

```text
Memory Retrieval Policy
```

在学习。

---

### 第六层：Graph Evolution（最昂贵）

最后才是：

```text
新增节点
删除节点
重组结构
```

例如：

```text
Requirement
    ↓
RTL
```

变成：

```text
Requirement
    ↓
Architecture Review
    ↓
RTL
```

这是系统结构层面的变化。

也是风险最大的变化。

---

我甚至觉得你的系统以后可以把所有这些统一成一个概念：

```text
Mutation
```

每次用户反馈后：

```text
产生若干Mutation Candidate
```

例如：

```text
M1:
修改Prompt

M2:
修改Routing

M3:
新增Graph Node

M4:
调整Memory权重
```

然后通过后续任务验证：

```text
效果是否提升
```

表现好的保留：

```text
Selection
```

表现差的回滚：

```text
Elimination
```

这样整个框架已经很接近一个真正的“进化系统”了。

因为它学习的对象不再局限于LLM参数，而是：

```text
整个Agent系统自身
```

换句话说，你的研究问题已经从：

> 如何设计一个Graph？

逐渐变成：

> 如何让Graph、Skill、Memory、RAG和Routing共同构成一个可进化系统？

这个方向比单纯做一个新的Agent Workflow，我认为研究空间要大得多，而且和IC设计这种高反馈、高验证性的场景天然契合。

# User
至少是可持续的

# Assistant
对，我觉得“可持续”可能比“智能”更关键。

很多Agent项目的生命周期其实是这样的：

```text
v1
├── 5个Skill
└── 效果不错

v2
├── 20个Skill
└── 效果更好

v3
├── 50个Skill
├── 100个Prompt
├── 30个Tool
└── 开始难以维护

v4
└── 没人敢改
```

性能提升是有的，但系统复杂度增长得更快。

最后出现几个典型问题：

- 新功能会破坏旧功能
- Prompt互相冲突
- Graph难以理解
- Memory越来越臃肿
- 调参成本越来越高

这其实是一种“技术债累积”。

---

而你前面一直强调的东西，实际上更像：

> 系统能不能在长期运行过程中维持优化能力。

换句话说：

```text
反馈
  ↓
分析
  ↓
修改
  ↓
验证
  ↓
保留有效修改
```

这个循环能不能一直跑下去。

如果能持续跑：

```text
第10次任务 > 第1次任务
第100次任务 > 第10次任务
第1000次任务 > 第100次任务
```

同时：

```text
复杂度增长缓慢
```

那就已经很有价值了。

---

我甚至觉得你们这个方向里有一个很重要的原则：

### 优先修改已有组件，而不是新增组件

例如用户反馈：

> RTL可读性差

第一反应不应该是：

```text
新增 Readability Agent
```

而应该依次尝试：

```text
1. 调整Prompt
2. 调整参数
3. 调整Routing
4. 调整RAG
5. 最后才新增Node
```

因为前四种的复杂度成本都远低于第五种。

---

从系统演化角度看，可以把每种修改赋予一个代价：

| 修改方式 | 成本 |
|----------|------|
| Prompt优化 | 1 |
| 参数调整 | 2 |
| Routing调整 | 3 |
| RAG调整 | 4 |
| Graph修改 | 10 |
| 新增Skill | 20 |

那么系统总是优先选择：

```text
收益 / 成本
```

最高的方案。

这样长期下来不会无限膨胀。

---

而且IC设计有个天然优势：

你们有客观验证器。

例如：

```text
RTL
 ↓
Lint
 ↓
Simulation
 ↓
Coverage
 ↓
Synthesis
 ↓
STA
```

每一步都能产生明确反馈。

很多通用Agent的问题是：

```text
结果好不好
没人知道
```

但IC领域：

```text
结果好不好
EDA工具直接告诉你
```

这意味着你的“进化循环”不需要完全依赖人类评价。

系统可以自己统计：

- 哪种修改提高了通过率
- 哪种修改降低了面积
- 哪种修改降低了时序违例
- 哪种修改提高了复用性评分

然后保留有效变异，淘汰无效变异。

---

所以如果让我概括你目前这个方向，我会说：

> 重点可能不在于让Agent越来越复杂，而在于让Agent能够通过反馈持续改进，同时控制复杂度增长。

这是一个比“做一个很强的Workflow”更长期、更可持续的目标。很多系统能做到强一时，但真正难的是在迭代几十轮、几百轮之后仍然保持可维护和可优化。你现在讨论的东西，本质上是在解决后者。

# User
理想情况下是我可以只留必要组件，其他针对模型能力自动生成

# Assistant
这其实已经很接近一种**最小核心（Minimal Core）+ 自生成策略层（Generated Layer）**的架构了，而且我觉得比预先设计一大堆Agent更有吸引力。

你的想法如果继续推演，大概会变成：

```text
Core System
├── LLM
├── Skill Runtime
├── Graph Runtime
├── Memory
├── Evaluator
└── Evolution Engine
```

真正长期维护的只有这些核心组件。

---

而不是这样：

```text
RTL Agent
Verification Agent
Lint Agent
CDC Agent
STA Agent
Power Agent
Architecture Agent
...
```

维护几十个Agent。

因为这种设计有个问题：

> 你预先假设了未来会遇到什么问题。

实际上未来的问题往往是未知的。

---

我觉得你现在隐含的思想更像：

## 固定的是执行框架

例如：

```text
Skill:
    Input
    Description
    Output

Graph:
    Node
    Edge
    Condition

Memory:
    Store
    Retrieve
    Rank

Evaluator:
    Evaluate()
```

这些定义长期不变。

---

## 变化的是实例

例如今天发现：

```text
FIFO设计
```

经常出问题。

系统自动生成：

```yaml
skill:
  name: fifo_cdc_review
```

或者：

```yaml
evaluation:
  name: fifo_boundary_check
```

加入工作流。

---

半年后模型升级。

假设从 GPT-5 变成 GPT-8。

模型本身已经很擅长CDC分析。

那么系统统计发现：

```text
fifo_cdc_review
```

已经几乎不贡献增益。

于是：

```text
删除
```

或者降权。

---

这点其实很关键。

很多Agent框架的问题是：

```text
Agent数量单调增加
```

但现实里应该是：

```text
Agent数量增加
Agent数量减少
Agent重组
```

同时发生。

否则永远在堆积技术债。

---

甚至从你的角度看，Skill本身都未必是永久存在的。

举个例子：

现在大模型可能需要：

```text
Requirement
    ↓
Architecture Analysis
    ↓
RTL Generation
```

未来模型变强后：

```text
Requirement
    ↓
RTL Generation
```

直接就够了。

那中间那个Architecture Skill应该被淘汰。

---

所以我觉得你说的：

> 只留必要组件，其他针对模型能力自动生成

背后其实对应一个很有意思的原则：

### 系统复杂度应该与模型能力负相关

即：

```text
模型弱
→ Workflow复杂

模型强
→ Workflow简单
```

而不是：

```text
模型弱
→ Workflow复杂

模型强
→ Workflow更复杂
```

后者是很多Agent框架正在走的路。

---

如果继续往研究方向靠，我甚至会把Evolution Engine定义成一个约束优化问题：

目标：

```text
最大化：
Task Quality
```

约束：

```text
Graph Size ≤ B1
Skill Count ≤ B2
Context Length ≤ B3
Inference Cost ≤ B4
```

每次进化都必须满足预算。

因此系统不能无限新增东西。

如果想加入：

```text
New Skill
```

可能必须淘汰：

```text
Old Skill
```

有点像操作系统里的缓存淘汰。

---

我觉得这和你最开始提到的“进化”其实已经非常一致了：

生物进化不是不断长器官。

如果每次进化都：

```text
+一个器官
+一个器官
+一个器官
```

最后早就活不下去了。

真正的进化往往是：

```text
保留有价值结构
淘汰冗余结构
重组已有结构
```

对于你的Agent系统来说也是一样。

长期来看，最有价值的能力可能不是：

> 自动生成多少Skill。

而是：

> 自动判断哪些Skill已经不值得存在了。

# User
这和我之前设想的可进化系统差不多，但是基础的planning更多依赖预设

# Assistant
对，我觉得这里其实出现了一个很自然的分层。

你最早设想的「可进化系统」和现在讨论的东西并不冲突，而是可以拆成两层：

```text
Foundation Layer（稳定层）
    ↓
Evolution Layer（进化层）
```

## 第一层：Foundation（预设）

这里放那些你认为长期不会变的东西。

例如：

```text
Task Analysis
Planning
Execution
Evaluation
Memory
```

或者更抽象一点：

```text
Observe
Plan
Execute
Evaluate
Learn
```

这些其实接近认知架构。

你不希望它们天天变。

否则系统会非常不稳定。

例如：

```text
用户需求
    ↓
需求分析
    ↓
任务规划
    ↓
执行
    ↓
验证
```

这种主流程完全可以预设。

因为这是经过大量工程实践验证过的。

---

## 第二层：Evolution（可变）

真正进化的是：

```text
Planning Strategy
Skill Selection
Graph Routing
Memory Retrieval
Evaluation Criteria
```

而不是：

```text
Plan这个概念存不存在
```

本身。

---

举个例子。

假设预设：

```text
Requirement
    ↓
Planning
    ↓
Execution
    ↓
Evaluation
```

Planning一定存在。

这是框架保证的。

---

但是Planning里面可能长这样：

```yaml
steps:
  - architecture_design
  - rtl_generation
  - simulation
```

后来通过反馈发现：

```text
复杂FIFO项目
```

经常失败。

Evolution Engine更新：

```yaml
steps:
  - architecture_design
  - cdc_review
  - rtl_generation
  - simulation
```

这时候：

- Foundation没变
- Planning机制没变
- 只是Planning的内容变了

---

我觉得这比让系统自己创造Planning模块靠谱得多。

因为如果连Planning框架本身都能随便改，你会碰到一个经典问题：

```text
Meta-Evolution Explosion
```

即：

```text
系统修改Graph
    ↓
系统修改Graph修改器
    ↓
系统修改Graph修改器修改器
```

无限递归。

最后根本不知道问题出在哪。

---

所以从工程角度，我会更倾向于：

```text
Immutable Core
    +
Mutable Knowledge
```

也就是：

### 不可变部分

```text
Planning Runtime
Skill Runtime
Memory Runtime
Evaluation Runtime
```

这些是操作系统。

---

### 可变部分

```text
Skill Definition
Graph Structure
Routing Policy
Prompt
Memory Index
```

这些是应用程序。

---

对于你们IC Agent来说，我甚至觉得：

### 最值得预设的是 Evaluation

因为EDA工具天然提供了客观反馈。

例如：

```text
Lint Pass?
Simulation Pass?
Coverage?
Area?
Timing?
Power?
```

这些指标不会因为模型升级而变化。

---

而：

```text
怎样才能通过这些指标
```

才是Evolution需要学习的内容。

---

所以我现在理解你的方向更像：

```text
Stable Planning Framework
        +
Self-Evolving Workflow
        +
Self-Evolving Skill Library
        +
Self-Evolving Memory
```

而不是：

```text
Everything Evolves
```

前者更容易落地，也更符合工程系统的可维护性。

说得再直白一点：

你可能不是在做一个“会自我重构的Agent”。

你是在做一个：

> **拥有固定认知骨架，但能够持续优化工作流和经验库的Agent系统。**

对于本科到硕士阶段的研究而言，这个范围其实已经足够大了，而且比“让系统自己发明整个架构”更容易做出可验证的成果。

# User
这和目前coding agent像codex和claude code的实现有区别吗，我感觉它们的planning能力更好所以完全可以用动态skill啊，或者harness

# Assistant
有区别，而且我觉得你抓到了一个很关键的点：

> 如果模型本身的 Planning 已经足够强，那么为什么还需要固定 Workflow？

这恰恰是现在 Coding Agent 领域正在发生的事情。

---

## Claude Code / Codex 实际上在弱化固定 Graph

早期 Agent：

```text
Task
 ↓
Planner
 ↓
Coder
 ↓
Tester
 ↓
Reviewer
```

节点是固定的。

类似 LangGraph 那种：

```python
graph.add_node(...)
graph.add_edge(...)
```

---

而 Claude Code 这类系统更像：

```text
Task
 ↓
LLM
 ↓
动态决定下一步
 ↓
Tool
 ↓
继续思考
 ↓
Tool
 ↓
继续思考
```

即：

```text
Graph ≈ Runtime Generated
```

不是预先写死。

---

例如用户说：

```text
修复这个项目里的bug
```

Claude Code不会真的执行：

```text
Plan
 ↓
Read File
 ↓
Analyze
 ↓
Edit
 ↓
Test
```

这种固定流程。

它可能：

```text
Read File
 ↓
Read Another File
 ↓
Search Symbol
 ↓
Run Test
 ↓
Read Error
 ↓
Edit
 ↓
Run Test
```

完全动态。

---

## 那为什么还需要 Skill？

这里就涉及你提出的 Dynamic Skill。

实际上 Claude Code 已经有一点这个味道。

例如：

```text
用户：修复测试
```

模型可能临时构造：

```text
Skill:
- 找失败测试
- 分析错误
- 定位代码
- 修改
- 验证
```

执行完就消失。

并没有：

```yaml
fix_test_failure.yaml
```

永久存在。

---

## 但它们缺少什么？

我觉得缺少的是：

> 长期进化

Claude Code 的 Planning 很强。

但是下一次会话：

```text
Memory ≈ 0
```

（至少公开版本大体如此）

它不会因为上周修FIFO踩坑而形成：

```text
新的Skill
新的Routing
新的Workflow
```

---

也就是说：

```text
Claude Code
=
Strong Runtime Planning
+
Weak Long-Term Evolution
```

---

而你现在讨论的东西更像：

```text
Strong Runtime Planning
+
Long-Term Evolution
```

---

## Dynamic Skill 其实和 Harness 很接近

你提到 Harness，我觉得这个比较接近。

因为 Harness 的思路本来就是：

```text
Task
 ↓
Context
 ↓
生成执行策略
 ↓
调用工具
```

而不是：

```text
固定Agent A
固定Agent B
固定Agent C
```

---

从你的角度看，一个 Skill 完全可以不是：

```yaml
name: fifo_design
```

这种永久定义。

而是：

```text
Task Analysis
    ↓
临时生成Skill
    ↓
执行
    ↓
评估
```

例如：

```text
设计一个AXI FIFO
```

系统生成：

```text
Skill #172

Input:
 AXI FIFO Requirement

Procedure:
 1. Interface Analysis
 2. CDC Analysis
 3. Buffer Design
 4. Verification

Output:
 RTL
```

任务结束后销毁。

---

## 你和 Claude Code 最大的区别可能在这里

Claude Code 更像：

```text
LLM
  ↓
即时规划
  ↓
执行
```

---

而你的设想是：

```text
LLM
  ↓
即时规划
  ↓
执行
  ↓
评估
  ↓
总结经验
  ↓
更新系统
```

多了一个闭环：

```text
Execution
    ↓
Reflection
    ↓
Evolution
```

---

我甚至觉得你未来可能不需要维护一个很大的 Skill Library。

因为随着模型能力增强：

```text
固定Skill价值
    ↓
逐渐下降
```

真正有价值的可能变成：

```text
Failure Database
Experience Memory
Evolution Policy
```

也就是说：

- Claude Code负责当下怎么解决问题；
- 你的系统负责从历史问题中学习，以后怎么更少犯错。

如果沿着这个方向走下去，你的研究重点可能会从「设计新的 Skill」逐渐转移到：

> 如何把用户反馈和验证结果转化为可持续的系统改进。

这部分恰好是目前大多数 Coding Agent 还没有真正解决好的。
