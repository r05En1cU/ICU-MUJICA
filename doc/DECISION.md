# ICU-MUJICA Develop Decision

> 功能：记录开发关键决策等必要信息。
> 记录格式：编号 | 结论 | 理由 | 推翻条件。

## 2026-06-11

### 今日目标

> 1.运行 CVDP 最小测试样例（至少 1 个）（未完成）
> 2.修复原 ICU-MUJICA v1.0 的潜在问题

| 编号 | 结论 | 理由 | 推翻条件 | 状态 |
| --- | --- | --- | --- | --- |
| 01 | 需要建立从 ICU-MUJICA docker 到 cvdp docker 的文件链接，给可编辑权限 | cvdp_benchmark 的 agentic 测试通过 Docker agent 运行，并且 agent 采用外部挂载目录作为工作空间 | 暂无/测试标准更新 | 暂缓 |
| 02 | 可以使用智能体进行单次运行 | README.md 明确写出运行配置字段为 -p work_agent | 暂无/智能体标准更新（低概率） | 暂缓 |
| 03 | CVDP 论文 提供了明确的测试 metrics，对本 Agent 需跑 Agentic Problems 并统计 Pass@1 Rate | 见 arXiv:2506.14074 | 暂无/测试标准更新 | metric 决策保留 |
| 04 | CVDP 子集限定 nocommercial 标签任务(iverilog/Verilator+cocotb,镜像自带) | 商业仿真器不可得 | 拿到商业 license 时 | 生效 |
| 05 | benchmark 输入只读,agent 输出限定 .env 指定工作区 | 防基准污染 | 暂无 | 生效 |

## 2026-06-13

### 今日目标

> 1.继续 06-11 的运行 CVDP 最小测试样例（至少 1 个）
> 2.完成统一测试样例的同模型对比（统一为 DeepSeek V4 Flash）

| 编号 | 结论 | 理由 | 推翻条件 | 状态 |
| --- | --- | --- | --- | --- |
| 06 | 针对单个 LLM 语义下的性能对比，应使用 FastAPI 将 Agent 包装成统一 OpenAI v1/completion 格式供统一对比 | Agent 模式接入下传 `prompt` 参数时含有多余工具调用信息，和 LLM 测试语义不统一 | v2 composite skill 跑通 / model 封装下性能瓶颈（期间可尝试运行单个 Agentic 示例并保留实验结果） | 生效 |