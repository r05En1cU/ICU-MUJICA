# ICU-MUJICA 决策文档

## 0. 已冻结的决策

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