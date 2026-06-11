# ICU-MUJICA Safety Eval Suite

系统安全性测试子项,用于评估 LLM 生成 RTL / SpecReg / Verify 报告时是否遵守硬性
安全约束与硬性系统边界。该套件与 `eval/phase1_suite/`(功能正确性基准)并列。

## 子项占位

| 编号 | 名称(待定) | 说明 |
|---|---|---|
| C1 | _TBD_ | 占位,待补用例 JSON 与 TB |
| C2 | _TBD_ | 占位,待补用例 JSON 与 TB |
| C3 | _TBD_ | 占位,待补用例 JSON 与 TB |
| C4 | _TBD_ | 占位,待补用例 JSON 与 TB |
| C5 | _TBD_ | 占位,待补用例 JSON 与 TB |

每个 `C{1..5}/` 目录下后续按需补:

- `case.json` —— 用例输入与预期硬性约束
- `tb.v`(可选)—— 仿真/对照
- `expected.md`(可选)—— 期望的安全/约束行为描述

## 暂存与后续

- 本次仅创建空目录结构 + `.gitkeep`,未填具体用例。
- 用例语义、验证脚本与 `run_phase1_suite.py` 的对接待 v1.5 主线开发明确后再补。
