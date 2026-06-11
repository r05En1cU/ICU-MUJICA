# C1 — Gen 节点中途 kill

## 触发条件
- 三个容器(parser / execute / evaluate)均 healthy
- 宿主 output/ 与 shared_workspace/ 不含 `TASK_*` 临时产物(C1 会使用以 `C1_` 开头的人类可读 task_id 前缀,见 `run_c1.py` 注释)

## 步骤
1. 构造 `WorkflowRunRequest`:
   - `top_module = c1_killed_gen_top`
   - `intent = GEN_WITH_TEST`
   - `refined_requirements = ["Implement a tiny 8-bit register ...", "Use Verilog-2001 only"]`
2. 提交到 `POST http://127.0.0.1:8001/v1/workflow/run`
3. 轮询 `shared_workspace/TASK_*/specs/UserTaskSpec.json`;一旦出现,等待 400ms 缓冲,然后:
   ```
   docker kill icu-mujica_execute
   ```
4. 等待 HTTP 调用线程结束(最长 60s)
5. 校验文件系统 / 响应内容
6. 恢复:`docker start icu-mujica_execute`;轮询 `/health` 直到 success(≤ 10s)
7. 二次提交同样 payload,确认系统可正常 archive_success

## 期望行为

### Parser HTTP 响应
- `status: "error"`
- `data: null`
- `message` 包含以下任一子串:
  - `execute request failed`
  - `execute workflow failed`
  - `All connection attempts failed`
  - `ConnectionError`
  - `RemoteProtocolError`

### 文件系统
| 路径 | 期望 |
|---|---|
| `shared_workspace/{TASK_ID}/specs/UserTaskSpec.json` | 存在(非空) |
| `shared_workspace/{TASK_ID}/rtl/` | 缺失或为空(无 .v 产物) |
| `output/{TASK_ID}/Result/` | 不存在 |
| `output/{TASK_ID}/Archive/` | 不存在 |
| `output/{TASK_ID}/UserTaskSpec.json` | 存在(parser_initialize 已落盘对外规约) |

### 容器恢复
- `docker start icu-mujica_execute` ≤ 10s 内,`/health` 返回 `status=success`
- 二次提交后,`output/{TASK_ID}/Result/shared_workspace/` 应被 archive_success 写入

## 失败判定
- Parser 客户端层 timeout(>60s)→ FAIL:系统挂起,违反「中途 kill 不允许无限等待」
- `output/.../Result/` 被创建 → FAIL:archive_success 不应被错误触发
- `shared_workspace/.../rtl/` 出现非空 .v 文件 → FAIL:Execute 被 kill 不可能产 RTL
- 二次提交仍报 execute 不可用 → FAIL:容器恢复不彻底

## 不在范围
- Gen 节点 OOM / segfault / 自然退出等其他异常
- Evaluate 节点被中途 kill(C2/C3 范围)
- 慢路径(LLM 真实推理)下的 kill 语义
