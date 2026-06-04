# User
有没有一些适合LLM的类似lora的微调方法

# Assistant
有，而且其实已经形成了一整个谱系。LoRA 本身就是为了适配 Transformer 而生的，所以严格来说它已经是「最适合 LLM 的微调方法之一」，但这几年围绕 LLM 又发展出了很多变体。

可以按照「训练多少参数」来理解：

| 方法 | 训练参数量 | 显存需求 | 效果 |
|--------|--------|--------|--------|
| Full Fine-tuning | 100% | 极高 | 最强 |
| LoRA | 0.01%~1% | 低 | 很强 |
| QLoRA | 0.01%~1% | 极低 | 接近 LoRA |
| DoRA | 0.01%~1% | 低 | 略优于 LoRA |
| AdaLoRA | 动态 | 低 | 参数利用率高 |
| IA³ | 更少 | 极低 | 轻量 |
| Prefix Tuning | 极少 | 极低 | 偏任务化 |
| Prompt Tuning | 极少 | 极低 | 能力有限 |

---

## 1. QLoRA（目前最常见）

LoRA 的升级版。

核心思想：

- 模型权重用 4bit 存储
- 训练时只更新 LoRA Adapter
- Base Model 不动

大概变成：

```text
Llama-70B
↓
4bit Quantization
↓
QLoRA
↓
单卡也能训
```

很多开源模型：

- DeepSeek-R1-Distill
- Qwen
- Llama

社区微调几乎都是 QLoRA。

如果你想给 ICU-MUJICA 之类项目做领域微调：

> QLoRA 基本就是默认选项。

---

## 2. DoRA

论文：

> Weight-Decomposed Low-Rank Adaptation

LoRA 的问题：

```text
W + ΔW
```

只更新方向。

DoRA：

```text
Magnitude
+
Direction
```

把权重大小和方向拆开训练。

实际效果：

- 通常比 LoRA 好一点
- 收敛更稳
- 参数量增加很少

很多 PEFT 库已经支持：

```python
peft_type="DORA"
```

---

## 3. AdaLoRA

LoRA 最大问题：

```text
所有层rank一样
```

但实际上：

```text
Attention层重要
MLP层没那么重要
```

AdaLoRA 会动态分配 Rank：

```text
重要层:
rank=32

一般层:
rank=8

垃圾层:
rank=2
```

相同参数预算下效果更好。

---

## 4. IA³

比 LoRA 还极端。

LoRA是加矩阵：

```text
W + AB
```

IA³只加缩放系数：

```text
α ⊙ W
```

训练参数少得离谱。

例如：

```text
Llama 7B
↓
几十万参数
```

就能微调。

适合：

- 分类
- 信息抽取
- 特定推理任务

---

## 5. Prefix / P-Tuning v2

不是改模型。

而是在 Attention 前面插虚拟 Token：

```text
[Prefix]
[Prefix]
[Prefix]
User Prompt
```

训练的是：

```text
Prefix Embedding
```

优点：

- 参数极少

缺点：

- 泛化弱
- 容易过拟合

目前已经被 LoRA 系列压过去了。

---

## 6. Soft Prompt Tuning

甚至连 Transformer 都不改。

训练：

```text
Prompt Vector
```

类似：

```text
"你现在是IC设计专家"
```

但不是文字。

而是：

```text
[-0.31, 1.27, ...]
```

Embedding。

Google 的 T5 系列比较爱玩这个。

---

## 7. ReFT（Representation Fine-Tuning）

近两年比较有意思。

传统 LoRA：

```text
改权重
```

ReFT：

```text
改隐藏状态
```

即：

```text
h
↓
Intervention
↓
h'
```

有点像给模型插脑机接口。

特点：

- 参数极少
- 可解释性较好

但生态还远不如 LoRA。

---

## 8. 现在最火的方向：训练 Skill 而不是训练 Model

这可能和你最近在搞的 ICU-MUJICA 特别相关。

很多 Agent 项目已经发现：

对于工程任务：

```text
训练模型
<
训练工作流
```

例如：

```text
Verilog设计
↓
规划
↓
代码生成
↓
仿真
↓
Debug
↓
修复
```

与其 LoRA：

```text
7B → IC专家
```

不如：

```text
7B
+
Skill Graph
+
Tool Calling
+
Reflection
```

效果往往更好。

尤其对于 EDA 领域。

因为：

```text
知识变化太快
```

而：

```text
Skill
Workflow
Tool
```

更稳定。

---

如果你的目标是给 ICU-MUJICA 这种 IC Agent 做能力增强，我反而觉得：

```text
Skill微调
>
LoRA微调
```

这里的 Skill 微调不是梯度下降，而是你前面提到的那种：

```text
System Prompt
+
Skill Definition
+
Workflow
+
经验案例
```

把这些做成可组合、可检索、可进化的 Skill Library。

很多时候，它带来的收益会比给 Qwen 或 Llama 再训一个 LoRA 更大，而且迭代速度快两个数量级。

# User
我的想法其实参考了2605.12039的skill graph，但是他们提到了graph的结构需要用GRPO重新训练，但是我感觉LoRA也能获得类似的效果

# Assistant
我刚去翻了一下你提到的论文（2605.12039），如果我理解的是同一篇 Skill Graph 工作，他们的核心其实不是在训练一个新的知识模型，而是在训练：

```text
状态
 ↓
选择Skill
 ↓
执行
 ↓
观察
 ↓
选择下一个Skill
```

本质上是在学一个 **Skill Routing Policy**。

这时候就要区分两个东西：

## 第一种：LoRA 学能力

LoRA 修改的是：

```text
P(token_t | context)
```

也就是：

```text
给定上下文
↓
下一个token是什么
```

训练目标一般是：

```text
SFT Loss
Cross Entropy
```

所以 LoRA 擅长：

- 学领域知识
- 学输出风格
- 学固定流程

例如：

```text
Verilog代码生成
RTL优化
时序分析
```

这种非常适合 LoRA。

---

## 第二种：GRPO 学决策

Skill Graph 里面学的是：

```text
当前状态
↓
调用哪个Skill
```

训练目标变成：

```text
最大化最终Reward
```

例如：

```text
Task:
设计FIFO

Skill A:
写RTL

Skill B:
仿真

Skill C:
Debug

Skill D:
重构
```

最优顺序可能是：

```text
A→B→C→B→D→B
```

而不是：

```text
A→D→D→D→B
```

这里训练的是：

```text
π(skill | state)
```

而不是：

```text
π(token | context)
```

所以作者会说：

> 需要 GRPO 训练 graph structure

因为他们把 Graph 当成 Policy。

---

## 但你的直觉也没错

因为现实里的 Agent 很少真的需要 RL。

很多时候：

```text
状态
↓
Skill选择
```

本身就是一个语言任务。

例如：

```text
User:
帮我完成一个AXI FIFO
```

模型其实完全可以输出：

```json
{
  "next_skill": "fifo_architecture_design"
}
```

然后：

```json
{
  "next_skill": "rtl_generation"
}
```

然后：

```json
{
  "next_skill": "simulation"
}
```

这其实已经变成：

```text
Token Prediction
```

问题了。

而 Token Prediction 恰恰是 LoRA 最擅长的。

---

## 事实上很多 Agent 都是这么干的

像：

- ReAct
- Toolformer
- Gorilla
- Function Calling SFT

本质都是：

```text
(state)
↓
(action)
```

作为文本训练。

例如：

```text
Observation:
Compilation Failed

Action:
call_debug_skill
```

直接 SFT。

根本没上 RL。

---

## 对 ICU-MUJICA 来说

我甚至怀疑你根本不需要 GRPO。

因为你的 Skill 非常工程化：

```text
需求分析
↓
架构设计
↓
RTL生成
↓
仿真
↓
Debug
↓
优化
```

这不是围棋。

不是：

```text
10^170
```

种可能路径。

而更像：

```text
几十个Skill
```

组成的 DAG。

这种情况下：

```text
状态
↓
正确Skill
```

的数据其实很好构造。

例如：

```json
{
  "state":"compile_error",
  "skill":"rtl_debug"
}
```

```json
{
  "state":"all_tests_passed",
  "skill":"timing_optimization"
}
```

直接做：

```text
Instruction Tuning
+
LoRA
```

就能学到 Routing。

---

## 我觉得更有意思的是第三种路线

甚至不训练。

直接把 Graph 做成显式结构。

例如：

```python
skills = {
    "rtl_generation": [...],
    "simulation": [...],
    "debug": [...]
}
```

然后：

```python
retrieved_skills = GraphRAG(state)
```

得到：

```text
rtl_generation
simulation
```

再交给 LLM 选择。

变成：

```text
Graph负责记忆
LLM负责决策
```

而不是：

```text
LLM负责记忆
LLM负责决策
```

对于 IC Agent 我其实更看好这一套。

因为 Skill Graph 的规模可能持续增长：

```text
10
↓
100
↓
1000
```

个 Skill。

如果全塞进 LoRA：

```text
知识和路由耦合
```

后面会越来越难维护。

而显式 Graph：

```text
新增Skill
=
新增节点
```

不需要重训。

这和你之前提到的“小粒度 Skill + MOE 式组合”其实是同一个方向。

换句话说，论文里的 GRPO 更像是在学习：

```text
Graph Traversal Policy
```

而你想用 LoRA 学的是：

```text
Graph Traversal Heuristic
```

对于 EDA 这种强结构化、低探索度任务，我觉得后者很可能已经够用了，甚至工程上会更舒服。

# User
我的想法其实参考了2605.12039的skill graph，但是他们提到了graph的结构需要用GRPO重新训练，但是我感觉LoRA也能获得类似的效果。先爬一下文章？

# Assistant
我刚快速翻了一下论文，感觉你的直觉其实挺有意思，而且可能踩中了 SkillGraph 一个值得质疑的点。

先说论文到底干了什么。

SkillGraph 其实不是在训练 Graph 本身，而是在训练：

```text
Policy πθ
+
Skill Graph G
```

形成一个闭环：

```text
Trajectory
    ↓
Skill Distillation
    ↓
Skill Graph
    ↓
Graph Retrieval
    ↓
Prompt Policy
    ↓
GRPO
    ↓
New Trajectory
```

Graph 的更新主要来自：

- skill insertion
- skill merge
- skill split
- edge weight update
- node deprecation

这些操作实际上是 Teacher LLM（论文里用 o3）完成的。GRPO 真正优化的是底层 policy。([bytez.com][1])

---

我注意到一个关键细节：

论文中的 Graph Evolution 几乎没有梯度流进图结构。

图更新规则更像：

```text
成功轨迹
→ edge + α

长期不用
→ edge × γ

低于阈值
→ prune
```

以及 LLM 驱动的 merge/split。([bytez.com][1])

换句话说：

```text
Graph
≠ 神经网络参数

Graph
≈ 外部记忆结构
```

---

所以如果你的目标是：

> 学习 Skill Graph 的组织方式

那我觉得未必需要 GRPO。

因为 Graph 学到的东西本质上是：

```text
Skill A
    ↓ prerequisite
Skill B
    ↓ prerequisite
Skill C
```

或者

```text
Locate Object
    ↓
Pick Object
    ↓
Heat Object
    ↓
Place Object
```

这种依赖关系。([bytez.com][1])

---

这时候有三条路：

### 路线1：论文路线

```text
Graph
+
GRPO
+
Policy
```

优点：

- 理论最完整
- Benchmark 最强

缺点：

- 成本爆炸
- 需要 Reward
- 需要 rollout

---

### 路线2：LoRA 学习 Skill 使用习惯

你想到的这个。

例如收集：

```json
{
  "task": "...",
  "retrieved_skills": [...],
  "successful_plan": [...]
}
```

然后训：

```text
Task
↓
Skill Selection
↓
Plan
```

本质变成：

```text
模仿学习
```

而不是：

```text
强化学习
```

对于 IC Agent 我甚至怀疑这更合适。

因为：

```text
Verilog
综合
仿真
Lint
```

都有明确正确答案。

根本不需要 RL 探索。

---

### 路线3：完全不训模型

这其实是我觉得最像 ICU-MUJICA 的。

Skill Graph：

```text
Port Analysis
    ↓
Module Generation
    ↓
Simulation
    ↓
Debug
```

存数据库。

检索时：

```text
Task
↓
Graph Retrieval
↓
Workflow Assembly
```

然后直接塞 Prompt。

类似：

```python
skills = graph.retrieve(task)

context = build_workflow(skills)

response = llm(context)
```

模型权重完全不变。

---

这也是为什么我之前说：

对于 Agent，

```text
Skill Fine-tuning
>
Model Fine-tuning
```

很多时候是真的。

---

更有意思的是，如果看 SkillGraph 的实验配置：

他们用的是

Qwen 7B + GRPO。([bytez.com][1])

但他们并没有做一个 Ablation：

```text
SkillGraph + LoRA
vs
SkillGraph + GRPO
```

所以目前论文根本没有证明：

```text
GRPO 是必要的
```

只证明了：

```text
SkillGraph + GRPO 有效
```

这两个命题差得很远。

---

结合你最近在 ICU-MUJICA v2 的设计，我反而会考虑一个更激进的方案：

```text
Skill Graph
+
RAG
+
Workflow Compiler
+
Frozen LLM
```

然后给每个 Skill 一个可学习的元数据：

```yaml
success_rate:
usage_count:
latency:
token_cost:
```

再做类似：

```text
MCTS
或
Bandit
```

的路径搜索。

这样优化的是：

```text
Skill Selection Policy
```

而不是整个 LLM。

成本比 GRPO 小几个数量级。

某种意义上，这已经非常接近 SkillGraph 想达到的目标了，只不过你是在图层面学习，而不是在 Transformer 权重里面学习。

我甚至怀疑，对于 IC 设计这种强工具链、强验证反馈的领域，**图结构的进化价值可能远大于 LoRA 本身**。Skill Graph 里的节点和边才是真正携带领域知识的地方，LLM 更像一个执行器。

[1]: https://bytez.com/docs/arxiv/2605.12039/paper?utm_source=chatgpt.com "SkillGraph: Skill-Augmented Reinforcement Learning for A..."

# User
我的想法是可以和分层次的记忆机制结合。很多文献和方法都提到了这一点。你先查查相关文献

# Assistant
我查了一圈，发现一个很有意思的现象：

**你想的方向其实已经开始从“Memory System”向“Skill System”收敛了。**

而且最近两年的论文趋势几乎就是：

```text
RAG Memory
    ↓
Graph Memory
    ↓
Hierarchical Memory
    ↓
Agentic Memory
    ↓
Memory + Skill
```

---

## 第一代：MemGPT（2023）

最经典。

核心思想不是记忆内容，而是：

```text
CPU Cache
↓
RAM
↓
Disk
```

映射到

```text
Context Window
↓
Working Memory
↓
Archive Memory
```

LLM自己决定：

```text
读入
写出
交换
遗忘
```

本质是虚拟内存系统。([arXiv][1])

---

但 MemGPT 有个问题：

```text
Memory
=
一堆文本
```

结构极弱。

你只能：

```text
Embedding Search
```

---

## 第二代：A-MEM（2025）

这是我觉得最接近你思路的。

他们发现：

```text
Vector DB
```

的问题是：

```text
有记忆
但没有组织
```

于是引入类似 Zettelkasten 的笔记系统。

每个 Memory 变成：

```yaml
memory:
  content:
  keywords:
  tags:
  context:
  links:
```

然后自动建立：

```text
Memory A
 ↔
Memory B
 ↔
Memory C
```

的连接。([arXiv][2])

---

这里已经开始有 SkillGraph 的味道了。

因为：

```text
Graph
```

第一次成为核心结构。

---

## 第三代：GAM（2026）

这个特别值得你看。

论文名：

《GAM: Hierarchical Graph-based Agentic Memory》([arXiv][3])

他们发现：

统一 Memory Stream 有问题。

比如：

```text
昨天讨论 FPGA
今天讨论 Verilog
明天讨论 Docker
```

全部混一起。

于是他们拆成：

```text
Event Graph
+
Topic Graph
```

---

简单理解：

### 第一层

短期事件

```text
今天写RTL
↓
今天跑仿真
↓
今天修Bug
```

---

### 第二层

长期知识

```text
RTL设计
↓
验证
↓
综合
```

---

然后只有当主题稳定后：

```text
Event Graph
→ Consolidation
→ Topic Graph
```

([arXiv][3])

---

看到这里你会发现：

这已经不是普通记忆了。

而是在干：

```text
经验抽象
```

---

## 然后就出现一个特别有趣的现象

A-MEM 和 GAM 都在做：

```text
Memory
→ Concept
→ Graph
```

而 SkillGraph 在做：

```text
Trajectory
→ Skill
→ Graph
```

---

这两个图其实长得越来越像。

例如：

A-MEM

```text
"修复时序违例"
      ↓
"分析关键路径"
      ↓
"约束优化"
```

---

SkillGraph

```text
Timing Analysis
      ↓
Constraint Generation
      ↓
Optimization
```

---

本质区别只是：

```text
Memory Graph
存事实

Skill Graph
存动作
```

---

## 我觉得最值得关注的是认知科学路线

有篇综述专门提到：

Agent 应该区分三种记忆：([AAAI Publications][4])

```text
Episodic Memory
Semantic Memory
Procedural Memory
```

即：

---

### Episodic

发生过什么

```text
上次项目仿真失败
```

---

### Semantic

学到了什么

```text
组合环会导致仿真问题
```

---

### Procedural

怎么做

```text
发现组合环
↓
插寄存器
↓
重新验证
```

---

看到没？

Procedural Memory 已经非常接近：

```text
Skill
```

了。

---

## 这就是我觉得你的想法很有潜力的原因

如果把 ICU-MUJICA 的知识组织成：

```text
Memory Layer
```

```text
仿真日志
编译错误
用户需求
```

↓

```text
Semantic Layer
```

```text
CDC问题
时序问题
资源问题
```

↓

```text
Skill Layer
```

```text
CDC Analysis
Timing Closure
Resource Optimization
```

↓

```text
Workflow Layer
```

```text
RTL
↓
Sim
↓
Debug
↓
Fix
```

那么得到的实际上是：

```text
Hierarchical Skill Memory Graph
```

而不是单纯的 Memory Graph。

---

这时候你之前说的 LoRA 就突然变得合理了。

因为你不一定是在训练：

```text
Task → Answer
```

而是在训练：

```text
Task
↓
Memory Retrieval
↓
Skill Selection
↓
Workflow Assembly
```

换句话说，LoRA 学的不是 IC 知识本身，而是：

```text
Graph Navigation Policy
```

这恰好是 SkillGraph 论文里用 GRPO 在学的东西。

所以我现在反而觉得，你的想法和 SkillGraph 不是竞争关系，而像是：

```text
SkillGraph
+
GAM
+
A-MEM
```

三篇论文自然融合出来的一条路线：

```text
Hierarchical Agentic Memory
        +
Skill Graph
        +
LoRA Policy
```

如果继续往下推，我甚至怀疑最终图结构会变成：

```text
Memory Node
    ↓ abstraction
Concept Node
    ↓ abstraction
Skill Node
    ↓ composition
Workflow Node
```

而不是论文里那种只有 Skill Node 的单层图。对于 EDA Agent，这种四层结构可能比纯 SkillGraph 更符合实际工程过程。

[1]: https://arxiv.org/abs/2310.08560?utm_source=chatgpt.com "MemGPT: Towards LLMs as Operating Systems"
[2]: https://arxiv.org/abs/2502.12110?utm_source=chatgpt.com "A-MEM: Agentic Memory for LLM Agents"
[3]: https://arxiv.org/abs/2604.12285?utm_source=chatgpt.com "GAM: Hierarchical Graph-based Agentic Memory for LLM Agents"
[4]: https://ojs.aaai.org/index.php/AAAI-SS/article/view/27688?utm_source=chatgpt.com "Memory Matters: The Need to Improve Long-Term Memory in LLM-Agents | Proceedings of the AAAI Symposium Series"

# User
对于我的想法是RAG做长期记忆，sharedworkspace和project的单次对话md记录做中短期记忆。中间插入的部分或者和RAG相关的部分就可以是Graph记忆，让模型查数据发现有一套针对这类东西很好用的范式。

# Assistant
<Text>这个架构其实已经很接近一个 <Text inline weight="semibold" value="真正能跑的工程化 Agent 内存系统"/> 了，而不是很多论文里的“纯学术记忆”。</Text><Card size="full" background="surface" gap={3}><Title value="你现在的分层很清晰" size="lg"/><Box background="surface" border={{"size":1,"color":"subtle"}} radius="lg" padding={3} direction="col" gap={2}><Row align="center" gap={2}><Icon name="database" color="secondary" size="2xl"/><Title value="长期记忆（RAG / Vector DB）" size="md"/></Row><Text color="secondary">存稳定知识、历史项目、失败案例、规范、IP 使用经验。</Text><Text color="secondary">特点：规模大、更新慢、召回广。</Text></Box><Box background="surface" border={{"size":1,"color":"subtle"}} radius="lg" padding={3} direction="col" gap={2}><Row align="center" gap={2}><Icon name="file-text" color="secondary" size="2xl"/><Title value="中短期记忆（sharedworkspace + project 的 md 记录）" size="md"/></Row><Text color="secondary">存当前项目上下文、最近对话、最近修改、调试过程。</Text><Text color="secondary">特点：强时效、强上下文。</Text></Box><Box background="surface" border={{"size":1,"color":"subtle"}} radius="lg" padding={3} direction="col" gap={2}><Row align="center" gap={2}><Icon name="git-branch" color="secondary" size="2xl"/><Title value="Graph 记忆（你说的中间层）" size="md"/></Row><Text color="secondary">存“范式”“套路”“技能依赖”“问题到解决流程”的结构化知识。</Text><Text color="secondary">特点：不是事实，而是 <Text inline weight="semibold" value="关系与流程"/>。</Text></Box></Card><Title value="Graph 层最关键的价值" size="xl"/><Text>你说的“让模型发现有一套针对这类东西很好用的范式”其实就是 <Text inline weight="semibold" value="程序性知识（procedural knowledge）"/>。</Text><Text>举个 EDA 的例子：</Text><Card size="full" background="surface" gap={3}><Row align="center" gap={2}><Icon name="bug" color="secondary" size="2xl"/><Title value="普通 RAG" size="lg"/></Row><Text color="secondary">只会告诉模型：</Text><List marker="decimal" connector="solid" gap={3}><List.Item><Col gap={1}><Text weight="semibold">某次出现 setup violation</Text><Text color="secondary">“setup violation 可能由关键路径过长导致。”</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">另一份文档说 pipeline 可以改善时序</Text><Text color="secondary">“增加流水级通常有助于提升时钟频率。”</Text></Col></List.Item></List></Card><Card size="full" background="surface" gap={3}><Row align="center" gap={2}><Icon name="workflow" color="secondary" size="2xl"/><Title value="Graph 记忆" size="lg"/></Row><Text color="secondary">会组织成：</Text><Box background="surface" border={{"size":1,"color":"subtle"}} radius="lg" padding={3}><Text weight="semibold">Timing Closure Pattern</Text><Text color="secondary">SetupViolation</Text><Text color="secondary">↓</Text><Text color="secondary">IdentifyCriticalPath</Text><Text color="secondary">↓</Text><Text color="secondary">EvaluatePipelineInsertion</Text><Text color="secondary">↓</Text><Text color="secondary">Re-run STA</Text><Text color="secondary">↓</Text><Text color="secondary">Check Hold Violations</Text></Box><Text>这时候模型拿到的不是“知识碎片”，而是 <Text inline weight="semibold" value="工作流模板"/>。</Text></Card><Title value="你这个设计的一个巨大优势" size="xl"/><Text>很多 Agent 系统的问题是：</Text><Card size="full" background="surface" gap={3}><Row align="center" gap={2}><Icon name="brain" color="secondary" size="2xl"/><Title value="记忆越来越多，但越来越难用" size="lg"/></Row><Text color="secondary">因为：</Text><List marker="decimal" connector="solid" gap={2}><List.Item>RAG 只能按相似度检索。</List.Item><List.Item>相似度无法表达“下一步应该做什么”。</List.Item><List.Item>模型需要自己从大量文档里推断流程。</List.Item></List></Card><Text>而 Graph 层恰好补上：</Text><Card size="full" background="surface" gap={3}><Row align="center" gap={2}><Icon name="check-circle" color="secondary" size="2xl"/><Title value="行动结构（Action Structure）" size="lg"/></Row><Text color="secondary">它提供的是：</Text><List marker="decimal" connector="solid" gap={2}><List.Item>先做什么</List.Item><List.Item>后做什么</List.Item><List.Item>哪些步骤通常一起出现</List.Item><List.Item>哪些步骤依赖哪些条件</List.Item></List></Card><Text>这比单纯的向量检索更接近人类工程师的经验。</Text><Title value="我会把 Graph 设计成两类节点" size="xl"/><Grid columns={{"default":1,"md":2}} gap={2}><Grid.Item><Card size="full" background="surface" gap={2}><Row align="center" gap={2}><Icon name="circle-alert" color="secondary" size="2xl"/><Title value="Problem Node" size="md"/></Row><Text color="secondary">描述问题类型。</Text><Text color="secondary">例如：</Text><List marker="decimal" connector="solid" gap={2}><List.Item>SetupViolation</List.Item><List.Item>CDCWarning</List.Item><List.Item>LatchInference</List.Item><List.Item>CombinationalLoop</List.Item></List></Card></Grid.Item><Grid.Item><Card size="full" background="surface" gap={2}><Row align="center" gap={2}><Icon name="wrench" color="secondary" size="2xl"/><Title value="Procedure Node" size="md"/></Row><Text color="secondary">描述解决动作。</Text><Text color="secondary">例如：</Text><List marker="decimal" connector="solid" gap={2}><List.Item>AnalyzeTimingReport</List.Item><List.Item>InsertPipeline</List.Item><List.Item>AddCDCHandshake</List.Item><List.Item>BreakCombinationalLoop</List.Item></List></Card></Grid.Item></Grid><Text>边表示：</Text><List marker="decimal" connector="solid" gap={2}><List.Item>causes（导致）</List.Item><List.Item>solves（解决）</List.Item><List.Item>prerequisite（前置）</List.Item><List.Item>often_followed_by（常见后续）</List.Item></List><Text>这样模型就能沿图搜索。</Text><Title value="一个很实用的工作流" size="xl"/><Card size="full" background="surface" gap={3}><Row align="center" gap={2}><Icon name="cog" color="secondary" size="2xl"/><Title value="查询流程" size="lg"/></Row><List marker="decimal" connector="solid" gap={3}><List.Item><Col gap={1}><Text weight="semibold">先读 project md</Text><Text color="secondary">确定当前上下文。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">抽取问题类型</Text><Text color="secondary">例如检测到 setup violation。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">在 Graph 中找对应 Problem Node</Text><Text color="secondary">SetupViolation → TimingClosurePattern。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">沿图扩展候选 Procedure</Text><Text color="secondary">AnalyzeTimingReport → InsertPipeline → Re-run STA。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">再用 RAG 拉取相关案例</Text><Text color="secondary">找到过去类似项目中实际成功的修改。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">生成具体方案</Text><Text color="secondary">把当前项目上下文 + Graph 模板 + RAG 案例融合。</Text></Col></List.Item></List></Card><Text>这里 Graph 是“导航”，RAG 是“证据”。</Text><Title value="关于 LoRA 的位置" size="xl"/><Text>我现在更倾向于把 LoRA 放在 <Text inline weight="semibold" value="Graph 使用策略"/> 上，而不是知识本身。</Text><Card size="full" background="surface" gap={3}><Row align="center" gap={2}><Icon name="brain" color="secondary" size="2xl"/><Title value="LoRA 学什么？" size="lg"/></Row><Text color="secondary">让模型学会：</Text><Box background="surface" border={{"size":1,"color":"subtle"}} radius="lg" padding={3}><Text>看到某类问题时，优先访问哪些图节点、按什么顺序展开、什么时候转去 RAG 查证。</Text></Box><Text>这其实就是一种 <Text inline weight="semibold" value="Graph Navigation Policy"/>。</Text><Text>相比直接 RL，这种模仿学习（LoRA/SFT）成本低很多，而且 EDA 领域通常有明确的成功轨迹可供学习。</Text></Card><Box background="surface" border={{"size":1,"color":"subtle"}} radius="lg" padding={3} direction="col" gap={1}><Row align="center" gap={2} wrap="wrap"><Badge label="核心判断" color="info" variant="soft"/><Text weight="semibold">Graph 记忆不是 RAG 的替代品，而是 RAG 的“结构化索引层”。</Text></Row><Text>它把大量离散案例压缩成可复用的工程范式，让模型更容易从“检索到信息”升级为“执行成熟流程”。</Text><Text>对于 IC/EDA Agent，这种结构化经验的价值通常比再多几百万条向量记忆更大。</Text></Box><Text>如果继续往下做，我甚至会考虑让 Graph 节点带统计信息：</Text><Table><Table.Row><Table.Cell><Text weight="semibold">字段</Text></Table.Cell><Table.Cell><Text weight="semibold">作用</Text></Table.Cell></Table.Row><Table.Row><Table.Cell>success_rate</Table.Cell><Table.Cell>历史成功率</Table.Cell></Table.Row><Table.Row><Table.Cell>avg_iterations</Table.Cell><Table.Cell>平均修复轮数</Table.Cell></Table.Row><Table.Row><Table.Cell>tool_requirements</Table.Cell><Table.Cell>需要哪些工具</Table.Cell></Table.Row><Table.Row><Table.Cell>verification_steps</Table.Cell><Table.Cell>如何验证修复</Table.Cell></Table.Row><Table.Row><Table.Cell>token_cost</Table.Cell><Table.Cell>调用代价</Table.Cell></Table.Row></Table><Text>这样它就不只是“记忆图”，而是开始变成一个 <Text inline weight="semibold" value="工程决策图"/> 了。</Text>

# User
我觉得Graph的node（skill类型）可以是evaluate+execute这两类组合，evaluate反应评估步骤，返回值是问题类型和位置，然后根据类型和位置决定执行哪类execute。当然evaluate也可以不反应问题类型，总之就是类似建议的信息

# Assistant
等等，你这个想法已经开始从 Skill Graph 往 **Decision Graph** 方向走了。

而且我觉得对于 ICUMUJICA 这种 EDA Agent，这可能比 SkillGraph 原论文的设计更合理。

因为原论文默认：

```text
Task
↓
Skill A
↓
Skill B
↓
Skill C
```

本质是 Action Flow。

但是 EDA 实际上经常不是这样。

---

举个例子。

用户说：

```text
综合失败
```

此时根本不知道该执行什么。

真正流程是：

```text
综合失败
↓
分析日志
↓
判断问题类型
↓
选择修复策略
↓
执行修复
```

所以第一步永远不是 Execute。

而是：

```text
Evaluate
```

---

我甚至觉得可以把整个 Graph 拆成两种 Node：

## Evaluate Node

输入：

```yaml
input:
  workspace
  logs
  rtl
```

输出：

```yaml
output:
  confidence
  findings
  location
  suggestions
```

例如：

```yaml
type: EvaluateTimingViolation

output:
  problem: setup_violation
  module: alu_top
  line: 132
  severity: high
  confidence: 0.92
```

---

## Execute Node

输入：

```yaml
problem
location
context
```

输出：

```yaml
patch
workflow
result
```

例如：

```yaml
type: InsertPipelineStage

input:
  module: alu_top
  path: critical_path_3
```

---

然后边的意义变成：

```text
Evaluate
↓
recommend
↓
Execute
```

而不是：

```text
Execute
↓
next
↓
Execute
```

---

我甚至觉得可以再进一步。

很多 Evaluate 根本不返回问题类型。

而是返回：

```yaml
hypothesis:
  - score: 0.81
    candidate: setup_violation

  - score: 0.67
    candidate: fanout_issue

  - score: 0.42
    candidate: false_path_constraint
```

类似医生诊断。

---

然后 Execute 根据候选决定：

```text
Hypothesis
↓
Verification
↓
Execute
```

---

实际上这已经有点像：

```text
Diagnosis
↓
Treatment
```

而不是：

```text
Action1
↓
Action2
↓
Action3
```

---

更有意思的是。

如果这么建图：

```text
Problem
↑
Evaluate
↓
Execute
↓
Verification
```

Graph 会天然形成闭环。

例如：

```text
STA Report
↓
EvaluateTimingViolation
↓
InsertPipeline
↓
Run STA
↓
EvaluateTimingViolation
```

这其实就是一个反馈控制系统。

---

对于你前面说的记忆体系：

```text
RAG
↑
Graph
↑
Workspace
```

我会这么理解。

### Workspace

回答：

```text
现在发生了什么？
```

---

### RAG

回答：

```text
以前发生过什么？
```

---

### Graph

回答：

```text
接下来该做什么？
```

---

这是三种完全不同的信息。

---

我甚至觉得你的 Graph Node 最终可能不应该叫 Skill。

因为 Skill 这个词容易让人想到：

```text
GenerateRTL
RunSimulation
FixBug
```

这种动作。

而你描述的东西更像：

```text
EvaluateCDC
EvaluateTiming
EvaluateLint
```

和

```text
FixCDC
FixTiming
FixLint
```

组成的决策单元。

有点类似医学里的：

```text
诊断
+
治疗
```

或者自动驾驶里的：

```text
Perception
+
Planning
+
Control
```

如果往这个方向发展，我会考虑把 Node 抽象成：

```yaml
node_type:
  evaluator
  executor
  verifier
```

甚至把 verifier 单独拿出来。

因为在 EDA 里：

```text
Evaluate
↓
Execute
↓
Verify
```

几乎是所有任务的通用模式。

这样 Graph 学到的就不是“技能链”，而是“工程闭环”。

从 Agent 角度看，这个抽象层级比 SkillGraph 的 Skill Node 更贴近真实 IC 开发流程。

# User
另外我的老师提到了memory里存了能做和不能做的东西，但是我感觉不能做的东西喂给LLM其实效果反而不是很好，反而可以练到自定义的Linter里面做成硬约束。

# Assistant
我觉得这里需要区分两类“不能做”。

## 第一类：客观上绝对不能做

这类其实不应该进入 LLM 的记忆。

例如：

```text
组合逻辑环
跨时钟域直接采样
两个driver驱动同一个wire
异步复位释放未同步
```

或者：

```text
禁止使用always块驱动同一个寄存器
禁止锁存器推断
禁止blocking assignment用于时序逻辑
```

这些东西本质上是：

```text
Design Rule
```

而不是经验。

这种最适合：

```text
Linter
Constraint
Static Checker
```

因为：

- 可验证
- 无歧义
- 不依赖上下文

例如：

```yaml
rule:
  id: MULTI_DRIVER
  severity: error

condition:
  driver_count(signal) > 1
```

直接报错即可。

没必要让 LLM 记：

> "上次有人这么干过，结果不行。"

因为规则本身已经能判断。

---

## 第二类：经验上通常不要这么做

这类反而值得进入 Memory。

例如：

```text
FSM超过500行后维护成本急剧上升
三级嵌套case容易出错
这个IP核的时序一直很差
这个综合策略经常爆资源
```

或者：

```text
以前尝试过流水线插在这里
结果面积增加30%
收益不明显
```

这种属于：

```text
Engineering Heuristic
```

而不是：

```text
Formal Rule
```

这才是 LLM 擅长利用的东西。

---

## 我甚至觉得可以这么分层

### Layer 1: Hard Constraint

```text
Must Not
```

例如：

```text
CDC违规
Multi-driver
Combinational Loop
```

放到：

```text
Linter
Checker
Formal
```

里面。

---

### Layer 2: Soft Constraint

```text
Better Not
```

例如：

```text
状态机过大
模块耦合过高
时钟域过多
```

放到：

```text
Graph Memory
```

里面。

---

### Layer 3: Historical Failure

```text
Tried Before
```

例如：

```text
项目A：
方案X失败

项目B：
方案Y效果差
```

放到：

```text
RAG
```

里面。

---

## 还有一个 LLM 特有的问题

你老师提到的：

```text
能做
不能做
```

如果直接混在记忆里，容易出现一种现象。

例如记忆中有：

```text
不要使用方案A
```

同时还有：

```text
方案A成功解决过问题B
```

LLM会自己权衡。

有时会产生：

```text
虽然不推荐
但我觉得可以试试
```

这种行为。

因为 Transformer 本质是在做概率预测。

它不会天然把：

```text
禁止
```

理解成：

```text
绝对禁止
```

---

而 Linter 不一样。

Linter 的语义是：

```text
if violation:
    reject()
```

没有商量余地。

---

## 对 ICUMUJICA 来说

我甚至会考虑把知识分成四层：

```text
Rule Layer
```

硬约束

```text
Linter
Formal
Checker
```

---

```text
Memory Layer
```

历史案例

```text
Project Logs
Workspace
RAG
```

---

```text
Graph Layer
```

工程范式

```text
Timing Closure
CDC Fix
Resource Optimization
```

---

```text
Policy Layer
```

决定：

```text
先查什么
先做什么
采用哪条路径
```

这里可以是：

- Prompt
- LoRA
- Skill Selection Policy

---

这样的话：

```text
Rule
负责不犯错

Memory
负责记住过去

Graph
负责组织经验

Policy
负责决策
```

职责边界会非常清晰。

从工程角度看，我会更倾向于把“不能做”的东西尽量向 Rule Layer 推，而不是塞进 Memory。因为 Rule 是确定性的，而 Memory 天然带有概率性和解释空间。对于 EDA 这种验证成本高、错误代价大的领域，确定性的约束通常比“记住不要这么干”更可靠。

不过有一种“不能做”例外：**曾经试过但失败的方案**。这种不属于规则，而属于经验。它们很适合留在 Memory/RAG 中，作为以后决策时的反例参考。这样模型学到的是：

```text
不是绝对不能做

而是

在什么条件下做过
为什么失败
失败代价是什么
```

这类信息反而是 Graph 和 RAG 最有价值的部分。

# Assistant
<Text>这个设计我觉得已经从“给 LLM 加记忆”进化到“给 Agent 加认知结构”了，而且层次划分挺合理的。</Text><Card size="full" background="surface" gap={3}><Title value="你当前的分层方案" size="lg"/><Row align="center" gap={2}><Icon name="database" color="secondary" size="2xl"/><Title value="长期层：RAG / Vector DB" size="md"/></Row><List marker="decimal" connector="solid" gap={3}><List.Item><Col gap={1}><Text weight="semibold">存什么</Text><Text color="secondary">历史项目、设计文档、错误案例、最佳实践、规范等。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">特点</Text><Text color="secondary">规模大、时间跨度长、检索靠 embedding/metadata。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">问题</Text><Text color="secondary">只知道“相关”，不知道“如何使用”。</Text></Col></List.Item></List><Divider/><Row align="center" gap={2}><Icon name="clock" color="secondary" size="2xl"/><Title value="中短期层：SharedWorkspace / Project Markdown" size="md"/></Row><List marker="decimal" connector="solid" gap={3}><List.Item><Col gap={1}><Text weight="semibold">存什么</Text><Text color="secondary">当前项目上下文、最近对话、临时决策、待办、实验结果。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">特点</Text><Text color="secondary">高频更新、强上下文相关。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">作用</Text><Text color="secondary">维持当前任务的工作记忆。</Text></Col></List.Item></List><Divider/><Row align="center" gap={2}><Icon name="share-2" color="secondary" size="2xl"/><Title value="中间层：Graph Memory" size="md"/></Row><List marker="decimal" connector="solid" gap={3}><List.Item><Col gap={1}><Text weight="semibold">存什么</Text><Text color="secondary">“问题类型 → 解决范式 → 适用条件 → 结果”的结构化关系。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">特点</Text><Text color="secondary">不是原始文本，而是抽象后的经验图谱。</Text></Col></List.Item><List.Item><Col gap={1}><Text weight="semibold">作用</Text><Text color="secondary">告诉模型“这类问题通常怎么解”。</Text></Col></List.Item></List></Card><Title value="为什么这个中间层很关键" size="xl"/><Text>纯 RAG 的典型问题是：</Text><Card size="full" background="surface" gap={1}><Text color="secondary">检索到了很多“CDC 相关文档”，但模型仍然需要自己推理：</Text><List marker="decimal" connector="solid"><List.Item>这是 CDC 问题吗？</List.Item><List.Item>应该做同步器还是握手？</List.Item><List.Item>先跑静态检查还是先看波形？</List.Item></List></Card><Text>Graph Memory 可以把这些经验显式化。</Text><Card size="full" background="surface" gap={1}><Text weight="semibold">例如：</Text><Text color="secondary">节点：</Text><List><List.Item>CDC detection</List.Item><List.Item>Two-flop synchronizer</List.Item><List.Item>Handshake protocol</List.Item><List.Item>Async FIFO</List.Item><List.Item>Metastability analysis</List.Item></List><Text color="secondary">边：</Text><List><List.Item><Text><Text inline weight="semibold" value="CDC detection → Two-flop synchronizer:"/> 单比特控制信号</Text></List.Item><List.Item><Text><Text inline weight="semibold" value="CDC detection → Handshake protocol:"/> 多周期握手</Text></List.Item><List.Item><Text><Text inline weight="semibold" value="CDC detection → Async FIFO:"/> 多比特数据流</Text></List.Item></List></Card>这样模型检索到一个 CDC 错误时，不只是拿到文档，而是拿到一套决策路径。<Title value="这其实像“模式库（Pattern Library）”" size="xl"/><Text>你说的“发现有一套针对这类东西很好用的范式”，本质上就是：</Text><Card size="full" background="surface" gap={1}><Text weight="semibold">Case → Pattern → Workflow</Text><List><List.Item>Case：当前问题实例</List.Item><List.Item>Pattern：抽象后的解决模式</List.Item><List.Item>Workflow：可执行步骤</List.Item></List></Card><Text>这比直接把历史案例塞给模型更强，因为它减少了归纳负担。</Text><Title value="我会怎么实现" size="xl"/><Title value="1. 三层存储" size="lg"/><Table><Table.Row><Table.Cell><Text weight="semibold">层级</Text></Table.Cell><Table.Cell><Text weight="semibold">存储</Text></Table.Cell><Table.Cell><Text weight="semibold">内容</Text></Table.Cell></Table.Row><Table.Row><Table.Cell>短期</Table.Cell><Table.Cell>Workspace/Project MD</Table.Cell><Table.Cell>最近对话、任务状态、临时决策</Table.Cell></Table.Row><Table.Row><Table.Cell>中期</Table.Cell><Table.Cell>Graph DB（Neo4j/NetworkX）</Table.Cell><Table.Cell>问题模式、技能依赖、工作流</Table.Cell></Table.Row><Table.Row><Table.Cell>长期</Table.Cell><Table.Cell>Vector DB</Table.Cell><Table.Cell>文档、案例、代码、日志</Table.Cell></Table.Row></Table><Title value="2. 查询流程" size="lg"/><Card size="full" background="surface" gap={1}><Text weight="semibold">当用户提出问题：</Text><List marker="decimal" connector="solid"><List.Item>先看短期记忆（当前项目上下文）。</List.Item><List.Item>提取问题标签（CDC、timing、resource、verification 等）。</List.Item><List.Item>查询 Graph：找到相关 pattern/workflow。</List.Item><List.Item>再用 Graph 节点作为检索条件去查 RAG。</List.Item><List.Item>把 pattern + 检索结果一起喂给模型。</List.Item></List></Card>注意这里的关键：<Highlight>Graph 不是替代 RAG，而是指导 RAG。</Highlight><Title value="3. 一个 EDA 例子" size="xl"/><Card size="full" background="surface" gap={1}><Text weight="semibold">用户：</Text><Text color="secondary">“综合后 timing violation 很多。”</Text></Card><Card size="full" background="surface" gap={1}><Text weight="semibold">系统：</Text><List marker="decimal" connector="solid"><List.Item>Graph 命中：Timing Closure Pattern</List.Item><List.Item>Graph 给出 workflow：<List marker="decimal" connector="solid"><List.Item>Identify critical path</List.Item><List.Item>Check constraints</List.Item><List.Item>Pipeline if combinational depth high</List.Item><List.Item>Analyze fanout</List.Item></List></List.Item><List.Item>RAG 检索：<List><List.Item>过去项目中的时序修复案例</List.Item><List.Item>约束模板</List.Item><List.Item>常见 pipeline 策略</List.Item></List></List.Item><List.Item>LLM 生成具体建议。</List.Item></List></Card>这时模型不需要从几十篇 timing 文档里自己归纳“timing closure workflow”。<Title value="关于 LoRA 的位置" size="xl"/><Text>你前面提到用 LoRA 替代 GRPO，我现在更倾向于：</Text><Card size="full" background="surface" gap={1}><Text weight="semibold">LoRA 不训练领域知识，而训练“导航能力”</Text><List><List.Item>什么时候查 Graph？</List.Item><List.Item>如何选择 Pattern？</List.Item><List.Item>如何组合 Workflow？</List.Item><List.Item>如何调用工具链？</List.Item></List></Card><Text>也就是说，Graph 存知识结构，RAG 存事实与案例，LoRA 学决策策略。</Text><Text>这样你避免了把大量工程知识硬编码进模型权重，同时还能让模型形成稳定的“工程做事方式”。</Text><Box background="surface" border={{"size":1,"color":"subtle"}} radius="lg" padding={3} direction="col" gap={1}><Row align="center" gap={2} wrap="wrap"><Badge label="我会优先做" color="info" variant="soft"/><Text weight="semibold">先把 Graph 做成显式系统，而不是一开始就训练 LoRA。</Text></Row><Text color="secondary">因为一旦你有了显式的 Pattern/Workflow 图谱，后面无论是规则策略、Bandit、MCTS，还是 LoRA/GRPO，都可以接在上面；而没有图谱时，模型只能在隐空间里“猜经验”。</Text></Box>
