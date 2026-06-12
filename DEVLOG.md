# 2026-06-11

- 补入本地健壮性测试目录 `tests/`,新增针对 Parser/Execute/Evaluate 异常路由、retry 上下文、FailureRecord 记录与归档清理逻辑的稳健性检查。
- 暂未填 `eval/safety_suite/` 的具体用例,语义与脚本待 v1.5 守卫加固、P0 元数据、Ambiguity/DesignSheet 方向明确后再补。

# 2026-05-29 v1

- 完成项目文档品牌迁移：将项目描述更新为 `IC Unified - Multi-agent Unified Joint IC Automation`，明确 ICU-MUJICA 继承自 AGVS4RTL，曾作为重构分支，现转入独立开发；保留旧 README 备份 `README.md.bak`。
- 增强 LLM 运行时配置：主环境变量与内部请求头迁移为 `ICU_MUJICA_LLM_*` / `X-ICU-MUJICA-LLM-*`，保留 `AGVS4RTL_*` 兼容回退；补充 `reasoning_effort` 透传、网络重试与 CoT/推理文本剥离，避免运行时敏感配置写入任务产物。
- 收紧生成失败语义：Generator 真实 LLM 路径取消 dummy fallback，Architect / Coder 失败会记录修复上下文与错误产物，由 Parser / Verify 明确暴露失败，不再静默产出假 PASS。
- 完成 Verilog-2001 约束收敛：协议、提示词与 Verify 解析均禁止 SystemVerilog `logic` 等新语法，端口类型限定为 `wire` / `reg`，避免生成不可被当前工具链稳定处理的 RTL。
- 强化 `SpecReg` 图结构校验：禁止 `TOP` 作为普通 `nodes` 节点；层次化设计存在节点时必须提供 `edges`；TOP 边端口必须匹配顶层端口方向；每个子节点必须与 TOP 具备可达与反向可达关系，避免接口契约只藏在自然语言 `implementation_hint` 中。
- 引入 graph-driven skeleton elaboration：Generator 根据 `SpecReg.edges` 推导子模块端口契约、内部连线与顶层实例化，顶层 RTL skeleton 由图确定性生成；顶层文件不再交给 LLM 自由猜测端口连接，子模块输出端口默认使用 `output reg` 以兼容过程赋值。
- 增强 Architect 提示词约束：要求层次化/模块化设计必须把子模块接口写入 graph edges，不能仅在说明文本中描述；明确低位宽计算单元组合、模块复用等结构性需求需要体现在节点和边中。
- Parser / Compose 超时配置补齐：Parser 调用 Generator 与 Verify 的默认超时统一提升到 420 秒，并通过 `GEN_SERVICE_TIMEOUT_SECONDS` / `VERIFY_SERVICE_TIMEOUT_SECONDS` 注入 Compose，降低真实 LLM 与 Verify 慢路径误超时概率。
- 新增 Gradio 控制台 `app/gradio_ui.py`：支持 Parser 健康检查、工作流提交、实时轮询进度、Artifact/RTL/SpecReg/VerifyRpt/HardwareGraph 预览、Mermaid 图渲染、LLM runtime 表单，以及已归档任务状态刷新。
- Gradio 控制台新增未完成任务面板：动态扫描 `shared_workspace/TASK_*` 与未归档 `output/TASK_*`，不额外落盘任务索引；支持刷新、检查、加载原始请求到表单、直接重试和删除残留任务目录。
- 完成本轮容器与 GUI 验证：重建并重启 `parser` / `gen` / `verify` 三服务，确认 Parser health 正常；重启 Gradio GUI 至 `127.0.0.1:7860`，通过浏览器验证未完成任务列表、Load For Retry、删除测试任务与 Refresh Latest Output 可用。
- 现场评估混合位宽 PE 生成结果：普通提示词可得到可编译扁平 MAC，但缺少低位单元组合结构；强化提示词后模型开始尝试 2-bit 基础乘法与 shift-add 组合，并推导 17-bit 累加结果，但仍暴露 Verilog function 参数与 graph 未层级化问题。当前系统定位为可用的 RTL 生成工作流框架，复杂架构级设计仍需进一步把结构语义硬化到 Architect / Verify 规则中。