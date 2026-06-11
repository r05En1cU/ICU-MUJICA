#!/usr/bin/env python3
"""
ICU-MUJICA Safety Eval Suite — C1 runner.

行为级用例:
  1. 提交一个普通 GEN_WITH_TEST 请求到 Parser
  2. 监听 shared_workspace/{TASK_*/specs/UserTaskSpec.json,看到落盘后等待一个
     短缓冲(让 Parser 真正进入 execute_stateless 节点的 HTTP 调用),然后
     `docker kill icu-mujica_execute` 把 Gen 节点直接干掉
  3. 等待 /v1/workflow/run 返回,断言:
       - 返回 status=error / data=null
       - shared_workspace/.../rtl/ 缺失或为空
       - output/.../ 不存在 Result/ 或 Archive/
  4. 恢复:`docker start icu-mujica_execute`,等待 /health=success
  5. 二次提交同样的 payload,确认系统能正常 archive_success

使用:
  python3 eval/safety_suite/C1/run_c1.py                # 默认
  python3 eval/safety_suite/C1/run_c1.py --no-restart  # kill 后不重启
  python3 eval/safety_suite/C1/run_c1.py --dry-run     # 不发请求,只打印步骤
  python3 eval/safety_suite/C1/run_c1.py -h            # 帮助
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_WORKSPACE = Path(
    os.environ.get("ICU_MUJICA_SHARED_WORKSPACE", REPO_ROOT / "shared_workspace")
)
OUTPUT_ROOT = Path(os.environ.get("ICU_MUJICA_OUTPUT_ROOT", REPO_ROOT / "output"))

PARSER_URL = os.environ.get("ICU_MUJICA_PARSER_URL", "http://127.0.0.1:8001")
GEN_CONTAINER = os.environ.get("ICU_MUJICA_GEN_CONTAINER", "icu-mujica_execute")
EVAL_CONTAINER = os.environ.get("ICU_MUJICA_EVAL_CONTAINER", "icu-mujica_evaluate")
GEN_HEALTH_URL = os.environ.get(
    "ICU_MUJICA_GEN_HEALTH_URL", "http://127.0.0.1:8001"  # 仅在宿主机可直连时使用
)

# parser_initialize_node 落盘 spec 后的 settle 窗口,用于保证「中途」语义
KILL_SETTLE_SECONDS = float(os.environ.get("ICU_MUJICA_C1_SETTLE", "0.4"))
# 等待 /v1/workflow/run 收尾的最长秒数(实际通常几秒)
HTTP_WAIT_SECONDS = float(os.environ.get("ICU_MUJICA_C1_HTTP_WAIT", "60"))
# 提交后等待 spec 出现的最长秒数
SPEC_WAIT_SECONDS = float(os.environ.get("ICU_MUJICA_C1_SPEC_WAIT", "15"))
# 容器恢复后 /health 轮询超时
RECOVERY_HEALTH_TIMEOUT = float(os.environ.get("ICU_MUJICA_C1_RECOVERY", "10"))

REQUEST_TIMEOUT_SECONDS = max(HTTP_WAIT_SECONDS + 30.0, 90.0)

CASE_PAYLOAD: Dict[str, Any] = {
    "top_module": "c1_killed_gen_top",
    "intent": "GEN_WITH_TEST",
    "refined_requirements": [
        "Implement a tiny 8-bit register with synchronous active-low reset and an o_done flag.",
        "Use Verilog-2001 only; no SystemVerilog logic types.",
    ],
    "raw_input_text": "Safety eval C1: kill Gen node mid-flight.",
    "input_filename": "c1_request.txt",
    "max_iterations": 2,
}

EXPECTED_ERROR_HINTS = (
    "execute request failed",
    "execute workflow failed",
    "All connection attempts failed",
    "ConnectionError",
    "RemoteProtocolError",
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def log(stage: str, msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [{stage}] {msg}", flush=True)


def _docker(*args: str, check: bool = False) -> Tuple[int, str, str]:
    proc = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"docker {' '.join(args)} failed: rc={proc.returncode} stderr={proc.stderr.strip()}"
        )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def container_is_running(name: str) -> bool:
    rc, out, _ = _docker("inspect", "-f", "{{.State.Running}}", name)
    return rc == 0 and out.strip().lower() == "true"


def gen_alive() -> bool:
    try:
        # 先看 docker 层面是不是还在
        return container_is_running(GEN_CONTAINER)
    except Exception:
        return False


def parse_parser_url() -> str:
    return PARSER_URL.rstrip("/")


def find_new_task_dir(baseline: set[Path]) -> Optional[Path]:
    """返回 shared_workspace/ 下自 baseline 之后新增/更新的 TASK_ 目录。"""
    if not SHARED_WORKSPACE.exists():
        return None
    candidates = []
    for child in SHARED_WORKSPACE.iterdir():
        if not child.is_dir():
            continue
        if not child.name.startswith("TASK_"):
            continue
        if child in baseline:
            continue
        candidates.append((child.stat().st_mtime, child))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def wait_for_user_task_spec(
    baseline: set[Path], max_wait: float
) -> Optional[Path]:
    """轮询直到新 TASK_ 目录的 specs/UserTaskSpec.json 出现。"""
    deadline = time.monotonic() + max_wait
    last_task: Optional[Path] = None
    while time.monotonic() < deadline:
        task_dir = find_new_task_dir(baseline)
        if task_dir is not None:
            last_task = task_dir
            spec = task_dir / "specs" / "UserTaskSpec.json"
            if spec.exists() and spec.stat().st_size > 0:
                return task_dir
        time.sleep(0.1)
    return last_task  # 可能为 None


def post_workflow(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """提交工作流并返回 (parsed_response, error_str)。"""
    url = f"{parse_parser_url()}/v1/workflow/run"
    try:
        resp = httpx.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    try:
        body = resp.json()
    except ValueError:
        body = {"_raw": resp.text}
    return body, None if resp.status_code == 200 else f"http {resp.status_code}: {resp.text[:300]}"


def assert_passed(cond: bool, msg: str, failures: list[str]) -> None:
    if cond:
        log("PASS", msg)
    else:
        log("FAIL", msg)
        failures.append(msg)


def kill_gen() -> None:
    log("KILL", f"docker kill {GEN_CONTAINER}")
    _docker("kill", GEN_CONTAINER)


def start_gen() -> None:
    log("START", f"docker start {GEN_CONTAINER}")
    rc, out, err = _docker("start", GEN_CONTAINER)
    if rc != 0:
        log("START", f"start rc={rc} stderr={err}")


def wait_for_gen_health(timeout: float) -> bool:
    """通过 docker inspect 等待容器状态回到 running(无 Execute 内部探活 host 路径时使用)。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if container_is_running(GEN_CONTAINER):
            # 再等一小段时间让 uvicorn 真正起来
            time.sleep(0.5)
            return True
        time.sleep(0.2)
    return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def preflight() -> Optional[str]:
    """检查前置条件;返回 None 表示通过,否则返回错误说明。"""
    if not shutil.which("docker"):
        return "docker CLI 不在 PATH 中,无法执行 kill/start"
    if not container_is_running("icu-mujica_parser"):
        return f"Parser 容器(icu-mujica_parser)未运行,请先 docker compose up -d"
    if not container_is_running(GEN_CONTAINER):
        return f"Gen 容器({GEN_CONTAINER})未运行,请先 docker compose up -d"
    if not container_is_running(EVAL_CONTAINER):
        return f"Evaluate 容器({EVAL_CONTAINER})未运行,请先 docker compose up -d"
    # Parser 探活
    try:
        r = httpx.get(f"{parse_parser_url()}/health", timeout=5.0)
        if r.status_code != 200:
            return f"Parser /health 返回 {r.status_code}"
        body = r.json()
        if body.get("status") != "success":
            return f"Parser /health status != success: {body}"
    except httpx.HTTPError as exc:
        return f"Parser /health 不可达: {exc}"
    return None


def run_case(dry_run: bool, restart: bool) -> int:
    failures: list[str] = []

    log("PRE", "运行前置检查")
    pre_err = preflight()
    if pre_err is not None:
        log("PRE", f"前置不通过: {pre_err}")
        log("HINT", "如需查看参数,运行 python3 eval/safety_suite/C1/run_c1.py -h")
        # 不强制退出码非零:让用户在 dry-run / 容器未起的环境下也能看到用法
        return 2

    SHARED_WORKSPACE.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    baseline = {p for p in SHARED_WORKSPACE.iterdir() if p.is_dir()}
    log("BASE", f"baseline TASK_ 目录数 = {len(baseline)}")

    # ----------- 阶段 1: 提交 + 中途 kill -----------
    log("STEP1", "提交 /v1/workflow/run(后台线程)")

    response_box: Dict[str, Any] = {}

    def worker() -> None:
        body, err = post_workflow(CASE_PAYLOAD)
        response_box["body"] = body
        response_box["err"] = err

    if not dry_run:
        th = threading.Thread(target=worker, daemon=True)
        th.start()
        log("STEP1", "等待 parser_initialize 落盘 UserTaskSpec.json")
        task_dir = wait_for_user_task_spec(baseline, SPEC_WAIT_SECONDS)
        if task_dir is None:
            log("STEP1", "超时未看到 UserTaskSpec.json,系统可能未启动或被卡在更早阶段")
        else:
            log("STEP1", f"已落盘: {task_dir / 'specs' / 'UserTaskSpec.json'}")
            time.sleep(KILL_SETTLE_SECONDS)
            kill_gen()
        log("STEP1", f"等待 HTTP 响应(最多 {HTTP_WAIT_SECONDS}s)")
        th.join(timeout=HTTP_WAIT_SECONDS)
        if th.is_alive():
            log("STEP1", "HTTP 线程仍在运行,超时退出")
    else:
        task_dir = None
        log("STEP1", "dry-run: 跳过实际提交与 kill")

    body = response_box.get("body")
    err = response_box.get("err")

    # ----------- 阶段 2: 解析失败响应 -----------
    log("STEP2", "校验 Parser HTTP 响应")
    if dry_run:
        log("STEP2", "dry-run: 跳过响应校验")
    else:
        if err is not None and body is None:
            # 连接/超时也算符合"中途 kill → 不允许无限等待",但要单独标记
            log("STEP2", f"客户端层异常: {err}")
        assert_passed(
            isinstance(body, dict),
            "HTTP 响应为可解析 JSON 对象",
            failures,
        )
        if isinstance(body, dict):
            assert_passed(
                body.get("status") == "error",
                f"响应 status == 'error' (实际 {body.get('status')!r})",
                failures,
            )
            assert_passed(
                body.get("data") is None,
                f"响应 data is None (实际 {body.get('data')!r})",
                failures,
            )
            message = (body.get("message") or "")
            assert_passed(
                any(hint in message for hint in EXPECTED_ERROR_HINTS),
                f"message 含预期错误线索 (实际: {message[:200]!r})",
                failures,
            )

    # ----------- 阶段 3: 校验文件系统 -----------
    log("STEP3", "校验文件系统")
    if dry_run:
        log("STEP3", "dry-run: 跳过文件系统校验")
    else:
        if task_dir is None:
            # 没找到 task_dir 就只能检查 output 目录确实没新东西
            new_outputs = [
                p for p in OUTPUT_ROOT.iterdir()
                if p.is_dir() and p.name.startswith("TASK_")
            ]
            assert_passed(
                len(new_outputs) == 0,
                f"output/ 下未出现新的 TASK_ 目录(实际 {len(new_outputs)} 个)",
                failures,
            )
        else:
            spec = task_dir / "specs" / "UserTaskSpec.json"
            assert_passed(
                spec.exists() and spec.stat().st_size > 0,
                f"shared_workspace/{task_dir.name}/specs/UserTaskSpec.json 存在且非空",
                failures,
            )
            rtl_dir = task_dir / "rtl"
            if rtl_dir.exists():
                rtl_files = [p for p in rtl_dir.rglob("*") if p.is_file()]
                assert_passed(
                    len(rtl_files) == 0,
                    f"shared_workspace/{task_dir.name}/rtl/ 不含 .v 产物(实际 {len(rtl_files)} 个文件)",
                    failures,
                )
            else:
                log("PASS", f"shared_workspace/{task_dir.name}/rtl/ 缺失(符合预期)")

            output_task = OUTPUT_ROOT / task_dir.name
            assert_passed(
                not (output_task / "Result").exists(),
                f"output/{task_dir.name}/Result/ 不存在",
                failures,
            )
            assert_passed(
                not (output_task / "Archive").exists(),
                f"output/{task_dir.name}/Archive/ 不存在",
                failures,
            )

    # ----------- 阶段 4: 恢复 + 二次提交 -----------
    if restart and not dry_run:
        log("STEP4", "重启 Execute 容器")
        start_gen()
        ok = wait_for_gen_health(RECOVERY_HEALTH_TIMEOUT)
        assert_passed(ok, f"{GEN_CONTAINER} 在 {RECOVERY_HEALTH_TIMEOUT}s 内回到 running", failures)

        log("STEP4", "二次提交同样 payload,确认系统可恢复")
        baseline2 = {p for p in SHARED_WORKSPACE.iterdir() if p.is_dir()}
        body2, err2 = post_workflow(CASE_PAYLOAD)
        if err2 is not None:
            log("FAIL", f"二次提交客户端异常: {err2}")
            failures.append("二次提交异常")
        elif isinstance(body2, dict):
            data2 = body2.get("data") or {}
            assert_passed(
                body2.get("status") == "success",
                f"二次提交 status == 'success' (实际 {body2.get('status')!r})",
                failures,
            )
            assert_passed(
                data2.get("success") is True,
                f"二次提交 data.success is True (实际 {data2.get('success')!r})",
                failures,
            )
            assert_passed(
                data2.get("final_stage") == "archive_success",
                f"二次提交 final_stage == 'archive_success' (实际 {data2.get('final_stage')!r})",
                failures,
            )
            # 二次任务会留下 Result 目录;保留可观测,不再删除
            t2 = data2.get("task_id")
            if t2:
                log("STEP4", f"二次任务归档: output/{t2}/Result/")
    else:
        log("STEP4", "跳过恢复阶段(--no-restart 或 --dry-run)")

    # ----------- 汇总 -----------
    log("DONE", "C1 行为级 EVAL 结束")
    if failures:
        log("DONE", f"FAIL(失败 {len(failures)} 项):")
        for f in failures:
            log("DONE", f"  - {f}")
        return 1
    log("DONE", "PASS(全部断言通过)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="ICU-MUJICA Safety Eval — C1: Gen 节点中途 kill 行为级测试",
    )
    ap.add_argument(
        "--no-restart",
        action="store_true",
        help="执行 kill 后不重启 Gen 容器(便于人工排查)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="不发请求、不 kill,只打印步骤与前置检查结果",
    )
    args = ap.parse_args()

    return run_case(dry_run=args.dry_run, restart=not args.no_restart)


if __name__ == "__main__":
    sys.exit(main())
