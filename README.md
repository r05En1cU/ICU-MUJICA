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
- 分析和运行过程相互独立且采用多轮对话模式运行
- （考虑）skill 的每轮运行均遵循 evaluate + execute 模式
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
|  |  |- graph        - 智能体 skill 图结构
|  |  |- evaluate     - 评估器 skill
|  |  |- execute      - 执行器 skill
|  |- workflow        - 智能体原子化工作流目录
|- workspace          - 智能体 active 态下工作空间
|- output             - 文件输出目录
|  |- frontend        - 前端输出（架构图、RTL等）
|  |- backend         - 后端输出（报告、网表等）
|- docker_compose.yml
|- requirements.txt
|- .env               - 环境变量
```
---
## 技术栈选择
| 维度 | 选型 | 作用 |
| :--- | :--- | :--- |
---
## 文献和仓库参考
[1] SkillGraph: Skill-Augmented Reinforcement Learning for Agents via Evolving Skill Graphs - arXiv:2605.12039 [cs.CL]
[2] 