# ICU-MUJICA Agent Definition

ICU-MUJICA（IC Unified - Multi-agent Unified Joint IC Automation）是一个面向 IC/RTL 自动化生成、验证与迭代修复的多 Agent 工作流框架。项目继承自 AGVS4RTL，曾作为其重构分支推进，当前已转入独立开发。

当前阶段的系统目标不是一次性替代人工 RTL 设计，而是提供一个可运行、可观测、可失败归因的生成-验证闭环：能够从自然语言需求生成结构化规约，产出可综合 Verilog-2001 RTL，执行静态/编译级验证，并在失败时保留可供下一轮修复使用的结构化反馈。

---

## 1. 总体架构

系统由三个容器化内部服务和一个宿主机 GUI 构成：

```text
User / Gradio UI
  |
  v
Parser service  (external: 127.0.0.1:8001)
  |
  +--> Execute service   (internal: execute:8000)
  |
  +--> Evaluate service  (internal: evaluate:8000)

Persistent task data:
  output/TASK_ID/{Origin,Result,Archive}
  shared_workspace/TASK_ID/{specs,rtl,sim,graphs,llm}
```

- `parser` 是唯一对宿主机暴露 HTTP 入口的服务，负责请求接收、任务初始化、状态机编排、重试路由和归档。
- `execute` 与 `evaluate` 仅在 Docker 内部网络中开放 API，不直接暴露给外部用户。
- 大对象通过共享文件系统传递，HTTP 层只传输路径、状态摘要和结构化报告。
- Gradio GUI 位于 `app/gradio_ui.py`，用于健康检查、提交任务、观察进度、预览产物、管理未完成任务。

---

## 2. 核心设计原则

### 2.1 阶段产物清晰分工

- Parser 维护 `UserTaskSpec`：用户意图、顶层模块、原始需求与提炼后的需求。
- Execute Architect 维护 `SpecReg`：结构化接口、参数、功能要求、时钟复位、协议、RTL 图结构。
- Execute Coder 维护 RTL：根据 `SpecReg` 生成 Verilog-2001 源码。
- Evaluate 维护 `VerifyRpt`：验证 verdict、错误快照、修复建议与日志路径。

### 2.2 控制面与数据面分离

- 控制面：`WorkflowTraceStep`、`GenNodeOutput`、`VerifyNodeOutput` 等轻量结构。
- 数据面：`UserTaskSpec.json`、`SpecReg_iterN.json`、`*.v`、`VerifyRpt_iterN.json`、日志、图文件、LLM transcript。
- 服务间不通过 HTTP 传递完整 RTL、仿真日志或大块模型响应文本。

### 2.3 失败必须显式暴露

真实 LLM 路径不允许用 dummy RTL 静默兜底。Architect、Coder 或 Evaluate 失败时，应落盘 transcript、修复上下文和结构化错误，并由 Parser 明确归档为失败或进入下一轮 retry。

### 2.4 Verilog-2001 优先

当前工具链按 Verilog-2001 收敛：

- 禁止输出 SystemVerilog `logic` 等新语法。
- 顶层端口类型限定为 `wire` / `reg`。
- Evaluate 静态端口解析不接受 `logic`。
- Coder prompt 必须明确“可综合 Verilog-2001”。

---

## 3. Parser Agent

Parser 是系统的 Orchestrator，负责把用户请求转化为可执行任务，并驱动 Execute / Evaluate 的多轮闭环。

### 3.1 任务初始化

Parser 接收 `WorkflowRunRequest` 后必须：

1. 生成全局唯一 `task_id`。
2. 创建任务目录：
   ```text
   output/TASK_ID/Origin
   output/TASK_ID/Result
   output/TASK_ID/Archive
   shared_workspace/TASK_ID/specs
   shared_workspace/TASK_ID/rtl
   shared_workspace/TASK_ID/sim
   shared_workspace/TASK_ID/graphs
   shared_workspace/TASK_ID/llm
   ```
3. 将原始请求写入 `output/TASK_ID/Origin/request.txt`。
4. 生成并保存 `UserTaskSpec.json`，同时放入 output 与 shared workspace。

### 3.2 语义解析与路由

Parser 可使用 LLM 生成结构化 `ParserLlmAnalysis`，用于辅助：

- intent 分类；
- 需求提炼；
- 顶层模块名识别；
- 目标协议、设计规则和非法条件识别。

如果 LLM 不可用、返回不可校验内容或运行时禁用，则回退到保守关键词路由与原始需求兜底。显式请求字段优先级高于 LLM 推断字段。

### 3.3 工作流状态机

当前主路径为：

```text
parser_initialize
  -> gen_stateless
  -> verify_stateless
  -> archive_success | prepare_retry | archive_failed
```

Parser 根据 `VerifyRpt.verdict` 决策：

- `PASS`：归档到 `output/TASK_ID/Result`。
- `FAIL_SEMANTIC` / `FAIL_COMPILE` / 可恢复仿真失败：若未达到最大轮次，进入 `prepare_retry`。
- `INFRA_ERROR` / 不可恢复错误 / 达到最大轮次：归档到 `output/TASK_ID/Archive`。

### 3.4 超时与运行时配置

- Execute 调用超时由 `EXECUTE_SERVICE_TIMEOUT_SECONDS` 控制，默认 420 秒。
- Evaluate 调用超时由 `EVALUATE_SERVICE_TIMEOUT_SECONDS` 控制，默认 420 秒。
- LLM 运行时配置优先使用请求体 `llm` 字段，其次读取环境变量。
- 当前主前缀为 `ICU_MUJICA_LLM_*` 和 `X-ICU-MUJICA-LLM-*`，兼容旧 `AGVS4RTL_*` 前缀。

---

## 4. Execute Agent

Execute 在系统中承担 “Architect + Coder” 双角色。

### 4.1 输入与输出边界

输入：

- `WorkTaskPayload`；
- `UserTaskSpec.json` 路径；
- 当前 `iteration`；
- 若为 retry，读取上一轮 `SpecReg_iterN.json` 与 `VerifyRpt_iterN.json`。

输出：

- `SpecReg_iterN.json`；
- 一个或多个 Verilog RTL 文件；
- `HardwareGraph_iterN.json` / `HardwareGraph_iterN.mmd`；
- `ArchitectChat_iterN.json`、`CoderChat_iterN.json` 等 LLM transcript；
- `GenNodeOutput`，仅回传路径与摘要。

### 4.2 Architect 阶段：SpecReg

`SpecReg` 是 Execute 的结构化设计契约。它必须包含：

- `top_module`；
- 参数与端口定义；
- clock/reset；
- protocols；
- functional requirements；
- corner cases / illegal conditions / latency notes；
- RTL graph：`nodes` + `edges`。

Architect LLM 输出必须通过 Pydantic `SpecReg.model_validate(...)` 严格校验。校验失败时允许进行 repair frame 修复，但不允许 silently fallback 到与用户需求无关的 dummy 设计。

### 4.3 Graph 约束

RTL graph 是层次化设计的结构事实来源：

- 顶层统一用特殊端点 `TOP`，但 `TOP` 不得出现在 `nodes` 中。
- 若 `nodes` 非空，则 `edges` 必须非空。
- 每个非 TOP 节点必须至少参与一条边。
- 每个子节点必须从 TOP 输入/双向端口可达，并能反向到达 TOP 输出/双向端口。
- 任何子模块端口若需要被 Coder 使用，必须出现在某条 edge endpoint 中。
- `implementation_hint` 只能补充实现建议，不能承载唯一的接口契约。

### 4.4 Graph-driven Skeleton Elaboration

当 `SpecReg.nodes` 和 `SpecReg.edges` 描述层次结构时，Execute 应确定性生成顶层 skeleton：

- 根据 `SpecReg.ports` 生成顶层 module header。
- 根据 child incident edges 推导子模块端口契约。
- 根据 child-child edges 生成内部 wire。
- 根据 TOP-child edges 连接顶层端口和子模块端口。
- 顶层实例化不交给 LLM 自由发挥。

子模块 RTL 仍可由 Coder LLM 生成，但其 module header 必须服从 graph-derived port contract。子模块输出端口默认可使用 `output reg`，以兼容过程赋值风格。

### 4.5 Coder 阶段：RTL 生成

Coder 必须：

- 输出可综合 Verilog-2001；
- 只输出目标 RTL 文件内容，不输出 Markdown 包裹；
- 遵守 Architect 的 `SpecReg`；
- 在 retry 中消费上一轮 `VerifyRpt` 的错误摘要；
- 多文件任务按 `rtl_paths` 作为同一编译单元产出。

若 Coder 失败，应记录失败 transcript 和错误上下文，不得用虚假 PASS 产物掩盖失败。

---

## 5. Evaluate Agent

Evaluate 是裁决器与诊断器。它不修改 RTL，只判断当前产物是否满足 `SpecReg` 契约，并生成可供 Parser 路由和 Execute retry 使用的反馈。

### 5.1 验证流程

当前 Evaluate 内部流程为：

```text
init_context
  -> semantic_check
  -> compile_check
  -> diagnostic_enhance
  -> finalize
```

### 5.2 Verdict 语义

- `PASS`：静态契约与编译检查通过。
- `FAIL_SEMANTIC`：模块名、端口集合、端口方向、端口位宽、顶层/子模块契约不一致。
- `FAIL_COMPILE`：`iverilog` 编译或 elaboration 失败。
- `FAIL_SIMULATION`：预留给动态仿真/断言失败。
- `INFRA_ERROR`：文件缺失、路径失效、工具不可用、服务异常等基础设施问题。
- `TIMEOUT`：验证执行超时。

### 5.3 静态契约检查

Evaluate 当前至少需要检查：

- SpecReg 文件存在且可解析；
- RTL 文件存在且可读取；
- 顶层 module name 与 `SpecReg.top_module` 一致；
- RTL 顶层端口集合与 `SpecReg.ports` 严格一致；
- 端口方向与位宽一致；
- Verilog-2001 约束未被破坏；
- 多 RTL 文件可作为同一编译单元交给 `iverilog`。

后续应扩展 graph contract 检查：当 `SpecReg.edges` 描述了子模块接口时，Evaluate 应确认子模块 module header 与 graph-derived child port contract 一致。

### 5.4 LLM 诊断增强

Evaluate LLM 只负责解释失败和补充修复建议，不决定 verdict。LLM 调用失败时必须保持确定性检查结果不变。

诊断 transcript 写入：

```text
shared_workspace/TASK_ID/llm/VerifyChat_iterN.json
```

其中不得包含 API key、base URL 或其他敏感运行时配置。

---

## 6. LLM Runtime 与安全边界

运行时配置来源优先级：

1. 请求体 `WorkflowRunRequest.llm`；
2. 环境变量 `ICU_MUJICA_LLM_*`；
3. 兼容环境变量 `AGVS4RTL_LLM_*`。

支持字段包括：

- `enabled`；
- `base_url`；
- `api_key`；
- `model`；
- `profile`；
- `reasoning_effort`。

安全要求：

- API key 不写入 `UserTaskSpec`、trace、Output、shared workspace 或 LLM transcript。
- transcript 只保留 messages、非敏感请求参数、响应文本、usage 和错误摘要。
- 需要剥离模型返回中的 chain-of-thought / reasoning 隐式文本，只保留可执行或可审计输出。

---

## 7. Gradio Control Panel

Gradio GUI 是当前开发与人工审查入口，默认监听：

```text
http://127.0.0.1:7860/
```

必须支持：

- Parser health check；
- workflow request 构造与提交；
- LLM runtime 表单；
- 后台提交 + 轮询刷新，避免长请求阻塞 UI；
- agent progress table；
- Artifact 列表；
- RTL / SpecReg / VerifyRpt 预览；
- HardwareGraph Mermaid 和 JSON 预览；
- Raw response 预览。

未完成任务面板必须动态扫描现有目录，不额外落盘索引文件：

- 来源：`shared_workspace/TASK_*` 与未归档 `output/TASK_*`；
- 操作：Refresh、Inspect、Load For Retry、Retry Task、Delete Task；
- 删除操作同时清理对应 `shared_workspace/TASK_ID` 与 `output/TASK_ID` 目录；
- 对真实任务删除应视为不可逆清理动作。

---

## 8. 文件与归档约定

任务运行时：

```text
shared_workspace/TASK_ID/
  specs/UserTaskSpec.json
  specs/SpecReg_iterN.json
  rtl/*.v
  sim/VerifyRpt_iterN.json
  sim/compile_iterN.log
  graphs/HardwareGraph_iterN.json
  graphs/HardwareGraph_iterN.mmd
  llm/*Chat_iterN.json
```

任务结束后：

- 成功：复制到 `output/TASK_ID/Result/shared_workspace`。
- 失败：复制到 `output/TASK_ID/Archive/shared_workspace`。
- 原始请求保留在 `output/TASK_ID/Origin`。
- Parser 可清理 `shared_workspace/TASK_ID`；GUI 未完成任务列表以目录是否仍存在和归档状态动态推断。

---

## 9. 当前能力边界

当前系统已经具备：

- 三服务生成-验证-归档闭环；
- 基本 retry 路由；
- 真实 LLM Parser / Architect / Coder / Evaluate 诊断路径；
- 严格端口契约检查；
- 多 RTL 文件编译单元支持；
- Verilog-2001 收敛；
- graph-derived top skeleton；
- GUI 实时观察与未完成任务管理。

当前仍不应宣称具备：

- 稳定的复杂微架构综合能力；
- 自动保证 BitFusion / systolic array / pipeline 等结构性需求完全实现；
- 完整动态仿真与覆盖率闭环；
- 对所有 LLM 输出的形式化正确性保证。

现场评估结论：

- 简单和中等 RTL 任务已可作为可审查初稿生成工具使用。
- 复杂结构需求可能退化为扁平功能实现，或出现可修复的 Verilog 细节错误。
- 对复杂架构任务，必须继续把结构语义硬化到 Architect prompt、SpecReg graph validation 和 Evaluate graph contract 中。

---

## 10. 后续演进方向

优先级从高到低：

1. 为结构性需求增加 Architect 硬规则：检测到“低位宽单元组合、复用、BitFusion、tile、adder tree、controller”等关键词时，禁止空 `nodes/edges`。
2. Evaluate 增加 graph-derived child port contract 检查，确保子模块 header 与 `SpecReg.edges` 一致。
3. 对常见 Verilog-2001 错误增加静态预检查，例如 function 参数声明、parameterized width 解析、非法数组声明位置。
4. 增加轻量 testbench / directed simulation 生成能力，覆盖 `functional_requirements` 与 `corner_cases`。
5. 将 GUI 中的失败归因和 retry 建议展示得更直接，减少手工翻 artifact 的成本。
6. 继续维护“不假通过”的系统原则：无法满足结构契约时应失败并解释，而不是生成看似可用的弱实现。
