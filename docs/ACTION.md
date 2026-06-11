# ICU-MUJICA 行动文档(唯一的"我需要做什么")

> 本文档整合:8 周计划、盲区分析、代码评审、收敛声明、知识管理协议。
> 它本身遵守自己的规则:只准删减和打勾,不准增加新概念。
> 失效条件:14 天验收(§2)完成后,本文档由 EXPERIMENTS.md 的数据接管优先级。

---

## 0. 已冻结的决策(禁止重开,直接抄进 DECISIONS.md)

| # | 决策 | 理由 | 推翻条件 |
|---|---|---|---|
| D1 | 不用 LangGraph,自研轻量 DAG 运行时 | 被优化的图必须是可序列化数据 | 永不(v2) |
| D2 | Mutation 欠定义:任何保持图合法性的变换;Harness 强定义 | 创新空间留给搜索 | 永不 |
| D3 | 不训练/不微调,结构约束搜索空间 | 成本与初衷 | 出现客观验证器无法覆盖的维度且 judge 校准失败 |
| D4 | 拆名:Variant Lineage Graph(工作流变体谱系)≠ Design Lineage Graph(RTL→物理谱系);后者是第二篇论文 | 概念冲突 | 永不(第一篇内) |
| D5 | 拆名:Gate(确定性裁决)≠ Interpreter(LLM 假设构造) | Evaluate 双重身份 | 永不 |
| D6 | "多 judge 去噪" = 分级客观验证器 racing(lint→sim→等价性→PPA)+ 多 seed 统计;LLM judge 只用于无客观验证器的维度且需校准 | 客观 harness 是核心资产 | 永不 |
| D7 | 进化引擎不住在 Harness 核心里(Immutable Core) | 防 meta-evolution 递归 | 永不 |
| D8 | 放弃 v1.5/v2 版本剧场:单主干 + 绞杀者替换,benchmark 先行 | 无基准的重写无法证明价值 | 永不 |
| D9 | Benchmark 转向 CVDP/RealBench 方向(VerilogEval 饱和);任务集切 evolve/held-out | 论文生死线 | CVDP 不可用时回退自建集 |
| D10 | 三容器拆分不带入 v2;models.py 契约、Verify 裁决纪律、llm_safety 带入 | 评审结论 | 永不 |
| D11 | Spire-HDL = 生成路径的受约束输出后端(一种 Skill 实现),**不是**表示基座;基座仍为 slang/Yosys RTLIL(必须能吃任意 Verilog)。pin commit + 接口包装可替换 | Spire 是 eDSL 非 parser;华为 paper code 无维护承诺;防任务集选择偏差 | Spire 增加 Verilog ingest 能力 |
| D12 | 主模型 DeepSeek-V4-Flash(便宜=演化循环友好)。目标指标是相对量:① ΔPass(harness − 裸跑,同集同 seeds);② 等美元成本下 DSV4F+harness vs 大模型裸跑。绝对分数(如 CVDP 50)仅作 stretch,在固定子集+计分方式前无定义 | 绝对分是虚荣指标;等成本对比直接检验"复杂度与模型能力负相关" | 永不 |

研究陈述(一句话,贴在所有新对话开头):
**在结构可拆解的设计制品上,以失败模式引导受限图变异,用分级客观验证器做统计化剪枝,使 agent 工作流结构随任务积累持续进化。**

H0(目的假设,2026-06-10):**当模型把 skill 内化进权重后,终端侧的不可约残留是一个最小可进化壳 = 验证 + 本地失败经验 + 审计/回滚 + 成本仲裁。** 检验方式:① 横截面 = D12 等成本实验;② 纵向 = 同一壳跨模型代际重跑,Δ 不衰减的成分即不可约壳,技能退役曲线本身是论文图表。

---

## 1. 知识管理协议(今天就执行,30 分钟)

1. 仓库只留三份活文档:
   - `DECISIONS.md` — 每条一行:结论 / 理由 / 推翻条件。用 §0 的表初始化。
   - `EXPERIMENTS.md` — 每次跑数:日期 / commit / 配置 / seeds / 数字。现在为空,这是正常的、也是羞耻的。
   - `VISION.md` — 现有 brainstorm1 压缩到 1 页,冻结。
2. `v2.0.0-phase1/brainstorm/` 整个目录移出仓库(本地留档可以,git 里删)。包括 2106 行时间线。
3. 聊天纪律:每次 AI 对话结束 → ≤5 行进 DECISIONS.md → 聊天记录丢弃。新对话开场 = 贴 DECISIONS.md + 研究陈述,不重新讲故事。
4. 文档存在资格:有人或有代码依赖它行动。其余删。

## 2. 14 天验收(唯一优先级,期间禁止新文档/新概念/讨论"更深")

到期检查 git log,以下全部存在则通过:

- [ ] **D1–2:从 0 到 1。** 一个 CVDP(或自选最小)任务,iverilog 跑通,第一条 FailureRecord 落入 JSONL。今晚做。
- [ ] **D3–5:benchmark runner。** 脚本输入 (任务集, seeds, 配置) → 输出结果表(JSON/CSV)。20 个任务:先用 CVDP 子集,不够就用 v1 能跑的生成任务凑,别完美主义。
- [ ] **D5–7:v1 止血四项**(直接在 main 上做,不开版本分支):
  - 全局异常兜底 → 一切失败走 archive_failed + trace(评审 #1)
  - WorkTaskPayload 加 verify_report_path,retry 上下文类型化(评审 #2)
  - **FailureRecord 结构化落盘**:每次非 PASS 追加 `(task_id, iteration, verdict, error_details, intent, top_module)` 到 JSONL(评审建议 3,这是 v2 演化数据的起点)
  - models.py 单测(至少覆盖 SpecReg 一致性校验和 VerifyRpt 互锁)
- [ ] **D8–12:baseline 数字。** 20 任务 × 3 seeds × 两行:**DSV4F 裸跑** 和 v1 现状,pass 率 + token 成本 + 耗时,进 EXPERIMENTS.md。这是你的第一张表;裸跑行决定 D12 中一切相对目标的含义。
- [ ] **D12–14:仓库卫生。** 删 .bak/.noverify/重复 DEVLOG;output/ 与 shared_workspace/ 出 git;compose 的 USER_ID 给默认值;§1 协议落地。
- [ ] **累计 ≥100 条 FailureRecord**(跑 benchmark 自然产生;不够就加 seeds)。

验收通过的奖励:你获得提出"研究什么更深"的资格——答案是表里第一个你解释不了的数字。

## 3. 14 天之后(预告,现在不准做)

按原 8 周计划推进,但起点已变(benchmark 已存在,提前完成了原 W3-4 的一半):

1. **W3-4 → 表示基座**:slang/Yosys 管道,RTL Graph + Link Table,增量 estimate。子图拆解的最小验证实验:同一修复任务,全文件 vs 子图上下文,成功率与 token 对比(这是三条腿里最便宜先立住的)。
2. **W5-6 → 演化闭环**:Addition Graph 插入点标注、6 个 mutation 算子、失败模式分类器(数据已经在 JSONL 里攒着)、分级 racing + ≥3 seeds 选择。
3. **W7-8 → 固化与实验**:win-streak 固化 + applicability condition、held-out 泛化实验、消融(无 Addition Graph 约束 / 无失败引导 / 随机变异)。
4. **写论文前**:对 ADAS / AFlow / GPTSwarm / EvoFlow / SkillOS 做对照表(学什么/改什么/fitness 来源/有无遗忘),补搜当期新工作。差异化三点:客观多级 harness、轨迹归因变异、复杂度预算下的固化与遗忘。

## 4. 自检条款(每周日读一遍)

- 本周 EXPERIMENTS.md 增加了数字吗?没有 = 这周在表演研究。
- 本周新建文档了吗?有 = 删掉,内容压进 DECISIONS.md。
- 有问题被第二次讨论吗?有 = 它该进 DECISIONS.md 了。
- 在想"更高层"或"更底层"吗?回去看 §2 的勾打完没有。
- 自我评估又出现了("我行/我不行")?不回答,看表。
