# Code Review: ICU-MUJICA (main / v1.5-dev @ 2520477)

> 评审范围:逐行读了 `src/common/models.py`、`src/parser/workflow.py`、`src/common/llm_safety.py`、`docker-compose.yml`、`.env.example`、`README.md`;`src/generator/workflow.py`(75KB)、`src/verify/workflow.py`(31KB)、`app/gradio_ui.py`(40KB)仅按结构与 README 契约推断,未逐行。v2-dev 分支目前为纯文档(brainstorm + CLAUDE.md),无代码可评。

### Summary

v1 是一个工程质量明显高于典型学生项目的三服务系统:契约层(models.py)是全仓库最强的资产,Verify 的"确定性裁决 + LLM 仅做诊断"边界已经提前实现了你 v2 的 Gate 原则。主要问题集中在:异常路径有真空区、retry 上下文走隐式文件约定、巨型单文件、零测试、仓库卫生。对 v1.5/v2 的取舍建议见末节。

---

### Critical Issues(影响正确性/数据)

| # | 位置 | 问题 | 严重度 |
|---|---|---|---|
| 1 | parser/workflow.py `gen_stateless_node` / `verify_stateless_node` | 对 gen/verify 的 HTTP 调用失败(连接拒绝、超时、非 success 响应)直接 `raise`,LangGraph 节点异常会**终止整个 run**——不走 `archive_failed`、不留 trace、shared_workspace/TASK_ID 残留不清理。README 宣称的 `INFRA_ERROR -> archive_failed` 只覆盖 Verify 自报的 infra 错误,Parser 侧基础设施故障完全绕过路由。state 里预留的 `error` 字段从未被使用。 | 🔴 |
| 2 | parser/workflow.py `prepare_retry_node` | retry 上下文通过"shared_workspace 目录约定"隐式传递:Generator 靠路径模式自行发现上一轮 `VerifyRpt_iter{N}.json`。`WorkTaskPayload` 不携带 verify 报告路径——**失败信息(你 v2 演化的核心数据)流经文件命名约定而非类型化契约**,与 models.py 全员强类型的风格自相矛盾,也是跨服务漂移的隐患。 | 🔴 |
| 3 | parser/workflow.py `prepare_retry_node` | `task.iteration = next_iteration` 原地修改 state 中的 Pydantic 对象。LangGraph 的 state 合并语义期望节点返回新值;原地变更在引入 checkpoint/replay 时会产生不可复现的状态(对你将来"trace 可回放"诉求是地雷)。 | 🟠 |
| 4 | `archive_success_node` / `archive_failed_node` | `copytree` 成功后 `rmtree(source)`,但 copytree 中途失败抛异常 → 节点死、归档半成品、源目录残留,且无任何重试/校验(如对比文件数)。归档是任务唯一产物出口,值得加最小事务性。 | 🟠 |
| 5 | `_build_llm_forward_headers` | API key 经自定义 header 明文转发。docker 内网可接受,但 uvicorn/反代的访问日志、异常 dump 都可能把 header 打出来;gen/verify 侧若有任何 request 日志中间件即泄漏。建议:转发前置入 header 白名单日志过滤,或改用容器 env 注入。 | 🟠 |

### Correctness / Design Suggestions

| # | 位置 | 建议 | 类别 |
|---|---|---|---|
| 6 | models.py `SpecReg.validate_spec_consistency` | 图可达性检查("每个节点必须从 TOP 输入可达且能到达 TOP 输出")会**误杀合法设计**:常数/tie-off 节点、纯监控/debug 节点、自由振荡计数器都过不了。这个 validator 是给 LLM Architect 的硬 Gate,过严会把合法 SpecReg 打成 FAIL 触发无意义 retry。建议降级为 warning 字段或加 `allow_dangling` 逃生口。 | 正确性 |
| 7 | models.py | `PortType` 只有 wire/reg,无 SystemVerilog `logic`;`ResetType` 无 "no reset"。当前限 Verilog-2001 可以,但 benchmark 转向 CVDP(SystemVerilog 为主)时契约层先卡死。 | 扩展性 |
| 8 | parser/workflow.py `_extract_json_object` | 首 `{` 配末 `}` 的提取对 "JSON 后跟解释文字" 鲁棒,但对 "两个 JSON 对象" 或字符串内含 `}` 的截断场景会静默错配。已有 Pydantic 校验兜底,可接受;若换弱模型建议改 `json_repair` 或 structured output。 | 鲁棒性 |
| 9 | gen/verify HTTP 调用 | 无重试/退避;420s 超时内一次瞬断即任务死亡(且因 #1 死得无痕)。一行 `httpx` transport retry 即可缓解。 | 可靠性 |
| 10 | `WorkflowTraceStep.detail` | trace 详情是自由文本。对人够用,对你 v2 的 Failure Pattern 挖掘**完全不可用**——等于现在每天在产生无法回收的实验数据。 | 数据资产 |
| 11 | 全仓库 | **零测试**。tree 中无 tests/ 目录;README 提到的验收靠宿主机脚本且未入库。models.py 里那几十个 validator 是最该有单测的代码——它们是 v2 要继承的资产,迁移时没有测试网就是裸迁。 | 测试 |
| 12 | generator/workflow.py (75KB)、models.py (43KB)、gradio_ui.py (40KB) | 三个巨型单文件。generator 的 workflow 结构硬编码在 Python 控制流里——这正是 v2 "图必须是可序列化数据" 要推翻的东西,v1.5 不必重构它,但**不要再往里加东西**。 | 可维护性 |

### 仓库卫生(便宜,建议 v1.5 顺手清)

`README.md.bak`、`src/parser/workflow.py.noverify` 入库(应删或进 git history);`DEVLOG.md` 与 `DEVLOGv1.md` 大小几乎相同疑似重复;`output/`、`shared_workspace/` 运行时目录被跟踪(应 .gitignore + .gitkeep);compose 的 `${USER_ID}:${GROUP_ID}` 未设默认值,新机器 `docker compose up` 直接报错。

### What Looks Good(真心话,不是客套)

- **models.py 是 v2 的种子,不是 v1 的遗产。** `StrictBaseModel(extra=forbid)`、跨字段语义校验(时钟/复位与端口一致性、verdict 与 error_details 互锁、SpecReg 图连通性)、`VerifyRpt` 把路由语义封装成 `is_retryable()/suggested_refactor_level()` 方法——"验证结果语义由模型承载而非 workflow 手写分支"这个决策非常对。`RtlNode/RtlEdge` 就是你 RTL Graph 的胚胎。
- **Verify 边界纪律。** 确定性节点裁决 verdict,LLM 只补诊断、失败不影响 verdict——你 v2 的 "Gate 强定义" 原则在 v1 已经落地了,这在学生 agent 项目里罕见。
- **安全卫生意识。** `SecretStr` + 不落盘、CoT 剥离(`llm_safety.py` 连未闭合 `<think>` 都处理了)、LLM transcript 净化后才落盘、`.env` 排除。
- parser/workflow.py 节点单一职责、路径工厂统一、注释把"为什么"讲清楚了;README 的进度记录与代码实际状态一致(很多仓库做不到)。

### Verdict: **Request Changes**(针对 #1/#2;其余不阻塞)

---

## 对 v1.5 / v2 的取舍建议

**v1.5(小改)只做四件事**,全部服务于"给 v2 攒数据 + 守住底线":

1. 全局异常兜底:LangGraph 外层 try/except → 写 trace → 走 `archive_failed`(修 #1)。
2. `WorkTaskPayload` 加 `verify_report_path: Optional[str]`,retry 上下文类型化(修 #2)。
3. **结构化 FailureRecord 落盘**:每次非 PASS,把 `(task_id, iteration, verdict, error_details, intent, top_module)` 追加到一个 JSONL。这是零成本动作,但意味着 v2 的 Failure Pattern 挖掘从今天开始攒数据,直接缓解你盲区清单里的 3.5(数据量)。
4. 给 models.py 补单测 + 清仓库卫生。

**v2(重构)的继承清单**:带走 models.py(契约直接演化为 Artifact 类型系统)、llm_safety、Verify 的裁决纪律、TaskPaths/trace/归档的 harness 经验;放下 LangGraph(与"图是被优化的数据"冲突,你已有此判断)、三容器拆分(单进程 + 工具沙箱即可,三个 HTTP 服务是 v1 multi-agent 的残留税)、jinja2 多 system prompt 体系。generator/workflow.py 里的 Architect/Coder 逻辑按 Skill 粒度拆出来重写,不要整体搬。
