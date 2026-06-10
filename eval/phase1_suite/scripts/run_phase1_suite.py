#!/usr/bin/env python3
"""Run ICU-MUJICA phase1 eval suite across env profiles.

This runner intentionally does not print .env secrets. It copies .env.<profile>
into .env before each test session, restarts docker compose, calls the
Parser API once, collects artifacts, and optionally runs supplemental iverilog
smoke testbenches when available.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "eval" / "phase1_suite"
DEFAULT_CASE_LIST = SUITE_ROOT / "cases.json"
DEFAULT_RESULTS_ROOT = SUITE_ROOT / "results"
PARSER_URL_DEFAULT = "http://127.0.0.1:8001"

SECRET_KEY_RE = re.compile(r"(API[_-]?KEY|SECRET|TOKEN|PASSWORD|AUTH)", re.I)


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_cmd(cmd: list[str], *, cwd: Path = REPO_ROOT, timeout: int | None = None, check: bool = False) -> CommandResult:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    res = CommandResult(proc.returncode, proc.stdout, proc.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return res


def docker_compose_cmd() -> list[str]:
    # Prefer modern docker compose.
    probe = run_cmd(["docker", "compose", "version"], timeout=20)
    if probe.returncode == 0:
        return ["docker", "compose"]
    probe2 = run_cmd(["docker-compose", "version"], timeout=20)
    if probe2.returncode == 0:
        return ["docker-compose"]
    raise RuntimeError("Neither `docker compose` nor `docker-compose` is available")


def read_env_summary(env_path: Path) -> dict[str, str]:
    values = read_env_values(env_path)
    summary: dict[str, str] = {}
    for key, value in values.items():
        if SECRET_KEY_RE.search(key):
            summary[key] = "***REDACTED***" if value else ""
        else:
            summary[key] = value
    return summary


def read_env_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def env_get(values: dict[str, str], primary: str, legacy: str | None = None, default: str | None = None) -> str | None:
    if primary in values and values[primary] != "":
        return values[primary]
    if legacy is not None and legacy in values and values[legacy] != "":
        return values[legacy]
    return default


def build_llm_payload_from_env(values: dict[str, str]) -> dict[str, Any]:
    enabled_text = (env_get(values, "ICU_MUJICA_LLM_ENABLED", "AGVS4RTL_LLM_ENABLED", "false") or "false").lower()
    payload: dict[str, Any] = {
        "enabled": enabled_text == "true",
        "base_url": env_get(values, "ICU_MUJICA_LLM_BASE_URL", "AGVS4RTL_LLM_BASE_URL"),
        "api_key": env_get(values, "ICU_MUJICA_LLM_API_KEY", "AGVS4RTL_LLM_API_KEY"),
        "model": env_get(values, "ICU_MUJICA_LLM_MODEL", "AGVS4RTL_LLM_MODEL"),
        "profile": env_get(values, "ICU_MUJICA_LLM_PROFILE", "AGVS4RTL_LLM_PROFILE", "default") or "default",
        "reasoning_effort": env_get(values, "ICU_MUJICA_LLM_REASONING_EFFORT", "AGVS4RTL_LLM_REASONING_EFFORT"),
    }
    return {key: value for key, value in payload.items() if value is not None}


def redact_payload(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted: dict[str, Any] = {}
        for key, value in obj.items():
            if SECRET_KEY_RE.search(str(key)):
                redacted[key] = "***REDACTED***" if value else value
            else:
                redacted[key] = redact_payload(value)
        return redacted
    if isinstance(obj, list):
        return [redact_payload(item) for item in obj]
    return obj


def copy_env_for_profile(profile: str) -> tuple[dict[str, str], dict[str, str]]:
    src = REPO_ROOT / f".env.{profile}"
    if not src.exists():
        raise FileNotFoundError(f"missing env profile file: {src}")
    dst = REPO_ROOT / ".env"
    shutil.copyfile(src, dst)
    return read_env_values(src), read_env_summary(src)


def apply_service_timeout_override(
    env_values: dict[str, str],
    env_summary: dict[str, str],
    service_timeout: int | None,
) -> None:
    if service_timeout is None:
        return
    env_path = REPO_ROOT / ".env"
    timeout_text = str(service_timeout)
    with env_path.open("a", encoding="utf-8") as f:
        f.write(
            "\n"
            "# Added by phase1 eval runner for this run; restored after run unless --keep-env is used.\n"
            f"EXECUTE_SERVICE_TIMEOUT_SECONDS={timeout_text}\n"
            f"EVALUATE_SERVICE_TIMEOUT_SECONDS={timeout_text}\n"
        )
    env_values["EXECUTE_SERVICE_TIMEOUT_SECONDS"] = timeout_text
    env_values["EVALUATE_SERVICE_TIMEOUT_SECONDS"] = timeout_text
    env_summary["EXECUTE_SERVICE_TIMEOUT_SECONDS"] = timeout_text
    env_summary["EVALUATE_SERVICE_TIMEOUT_SECONDS"] = timeout_text


def backup_current_env() -> Path | None:
    env = REPO_ROOT / ".env"
    if not env.exists():
        return None
    backup = REPO_ROOT / f".env.eval_backup_{now_tag()}"
    shutil.copyfile(env, backup)
    return backup


def restore_env(backup: Path | None, *, keep_env: bool) -> None:
    env = REPO_ROOT / ".env"
    if keep_env:
        return
    if backup is None:
        if env.exists():
            env.unlink()
    else:
        shutil.copyfile(backup, env)
        backup.unlink(missing_ok=True)


def reset_docker(compose: list[str], *, rebuild: bool, logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    down = run_cmd(compose + ["down", "-v", "--remove-orphans"], timeout=180)
    (logs_dir / "docker_down.stdout.log").write_text(down.stdout, encoding="utf-8")
    (logs_dir / "docker_down.stderr.log").write_text(down.stderr, encoding="utf-8")
    if down.returncode != 0:
        raise RuntimeError(f"docker compose down failed: {down.stderr}")

    up_cmd = compose + ["up", "-d"]
    if rebuild:
        up_cmd = compose + ["up", "--build", "-d"]
    up = run_cmd(up_cmd, timeout=900)
    (logs_dir / "docker_up.stdout.log").write_text(up.stdout, encoding="utf-8")
    (logs_dir / "docker_up.stderr.log").write_text(up.stderr, encoding="utf-8")
    if up.returncode != 0:
        raise RuntimeError(f"docker compose up failed: {up.stderr}")


def wait_parser_ready(parser_url: str, *, timeout_s: int, poll_s: float = 2.0) -> None:
    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{parser_url.rstrip('/')}/health", timeout=5) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                if data.get("status") == "success":
                    return
                last_err = body
        except Exception as exc:  # noqa: BLE001
            last_err = repr(exc)
        time.sleep(poll_s)
    raise TimeoutError(f"Parser not ready after {timeout_s}s: {last_err}")


def post_workflow(parser_url: str, payload: dict[str, Any], *, timeout_s: int) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{parser_url.rstrip('/')}/v1/workflow/run",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": "http_error", "message": str(exc), "body": body}


def load_cases(case_list_path: Path, selected: set[str] | None) -> list[dict[str, Any]]:
    paths = json.loads(case_list_path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    for rel in paths:
        p = (case_list_path.parent / rel).resolve()
        case = json.loads(p.read_text(encoding="utf-8"))
        case["_case_file"] = str(p.relative_to(REPO_ROOT))
        if selected and case["case_id"] not in selected:
            continue
        cases.append(case)
    if not cases:
        raise ValueError("No cases selected")
    return cases


def task_dir_from_response(response: dict[str, Any]) -> str | None:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        task_id = data.get("task_id")
        if isinstance(task_id, str) and task_id:
            return task_id
    return None


def read_json_if_exists(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"_read_error": repr(exc)}


def find_result_paths(task_id: str, top_module: str) -> dict[str, Path]:
    base = REPO_ROOT / "output" / task_id / "Result" / "shared_workspace"
    return {
        "task_base": REPO_ROOT / "output" / task_id,
        "user_task_spec": REPO_ROOT / "output" / task_id / "UserTaskSpec.json",
        "spec_reg": base / "specs" / "SpecReg_iter0.json",
        "verify_rpt": base / "sim" / "VerifyRpt_iter0.json",
        "rtl": base / "rtl" / f"{top_module}.v",
        "rtl_dir": base / "rtl",
        "compile_log": base / "sim" / "compile_iter0.log",
        "graph_json": base / "graphs" / "HardwareGraph_iter0.json",
        "graph_mmd": base / "graphs" / "HardwareGraph_iter0.mmd",
        "llm_dir": base / "llm",
    }


def _enum_value(value: Any) -> Any:
    # SpecReg JSON stores enums as strings; in-process summaries may expose enum objects.
    return getattr(value, "value", value)


def _bit_width(value: Any) -> int | None:
    text = str(value).strip().replace(" ", "")
    if text.isdigit():
        return int(text)
    match = re.fullmatch(r"\[(\d+):(\d+)\]", text)
    if match:
        msb = int(match.group(1))
        lsb = int(match.group(2))
        return abs(msb - lsb) + 1
    return None


def _width_matches(actual: Any, expected: Any) -> bool:
    actual_bits = _bit_width(actual)
    expected_bits = _bit_width(expected)
    if actual_bits is not None and expected_bits is not None:
        return actual_bits == expected_bits
    return str(actual).strip().replace(" ", "") == str(expected).strip().replace(" ", "")


def _as_text_blob(values: Any) -> str:
    if isinstance(values, list):
        return "\n".join(str(v) for v in values)
    return str(values or "")


def _keyword_group_present(values: Any, group: list[Any]) -> bool:
    blob = _as_text_blob(values).lower()
    for token in group:
        if isinstance(token, list):
            if not any(str(alt).lower() in blob for alt in token):
                return False
        elif str(token).lower() not in blob:
            return False
    return True


def _append_keyword_group_failures(
    failures: list[str],
    values: Any,
    groups: list[list[Any]],
    label: str,
) -> None:
    for group in groups:
        if not _keyword_group_present(values, group):
            failures.append(f"{label} missing keyword group: {group}")


def evaluate_user_spec_checks(case: dict[str, Any], user_spec: Any | None) -> tuple[bool | None, list[str]]:
    checks = case.get("expected_user_spec_checks") or {}
    if not checks:
        return None, []
    failures: list[str] = []
    if not isinstance(user_spec, dict):
        return False, ["UserTaskSpec artifact missing or unreadable"]

    requirements = user_spec.get("refined_requirements") or []
    if not isinstance(requirements, list):
        failures.append("UserTaskSpec.refined_requirements is not a list")
        requirements = []
    design_rules = user_spec.get("design_rules") or []
    if not isinstance(design_rules, list):
        failures.append("UserTaskSpec.design_rules is not a list")
        design_rules = []
    searchable_user_spec_text = list(requirements) + list(design_rules)

    min_refined = checks.get("min_refined_requirements")
    if min_refined is not None and len(requirements) < int(min_refined):
        failures.append(f"refined_requirements count {len(requirements)} < {min_refined}")

    max_single_requirement_chars = checks.get("max_single_requirement_chars")
    if max_single_requirement_chars is not None:
        too_long = [len(str(item)) for item in requirements if len(str(item)) > int(max_single_requirement_chars)]
        if too_long:
            failures.append(
                f"{len(too_long)} refined requirement(s) exceed {max_single_requirement_chars} chars; "
                f"longest={max(too_long)}"
            )

    _append_keyword_group_failures(
        failures,
        searchable_user_spec_text,
        checks.get("required_refined_requirement_keyword_groups") or [],
        "refined_requirements/design_rules",
    )
    for key, expected in (checks.get("required_fields") or {}).items():
        if user_spec.get(key) != expected:
            failures.append(f"UserTaskSpec.{key} expected {expected!r}, got {user_spec.get(key)!r}")

    return len(failures) == 0, failures


def _endpoint_module(edge: dict[str, Any], side: str, node_by_id: dict[str, dict[str, Any]]) -> str | None:
    endpoint = edge.get(side) or {}
    if not isinstance(endpoint, dict):
        return None
    node_id = endpoint.get("node_id")
    if node_id == "TOP":
        return "TOP"
    node = node_by_id.get(str(node_id))
    if not node:
        return None
    return str(node.get("module_name") or node.get("node_id"))


def _endpoint_port(edge: dict[str, Any], side: str) -> str | None:
    endpoint = edge.get(side) or {}
    if not isinstance(endpoint, dict):
        return None
    port_name = endpoint.get("port_name")
    return str(port_name) if port_name is not None else None


def _edge_matches_requirement(edge: dict[str, Any], expected: dict[str, Any], node_by_id: dict[str, dict[str, Any]]) -> bool:
    if expected.get("source_module") and _endpoint_module(edge, "source", node_by_id) != expected["source_module"]:
        return False
    if expected.get("target_module") and _endpoint_module(edge, "target", node_by_id) != expected["target_module"]:
        return False
    if expected.get("source_port") and _endpoint_port(edge, "source") != expected["source_port"]:
        return False
    if expected.get("target_port") and _endpoint_port(edge, "target") != expected["target_port"]:
        return False
    return True


def _has_required_graph_path(
    edges: list[Any],
    expected: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
) -> bool:
    edge_modules: list[tuple[str | None, str | None, str | None, str | None]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edge_modules.append(
            (
                _endpoint_module(edge, "source", node_by_id),
                _endpoint_port(edge, "source"),
                _endpoint_module(edge, "target", node_by_id),
                _endpoint_port(edge, "target"),
            )
        )

    source_module = expected.get("source_module")
    target_module = expected.get("target_module")
    source_port = expected.get("source_port")
    target_port = expected.get("target_port")
    if not source_module or not target_module:
        return False

    frontier: list[str] = []
    for src_mod, src_port, dst_mod, dst_port in edge_modules:
        if src_mod != source_module:
            continue
        if source_port and src_port != source_port:
            continue
        if dst_mod is None:
            continue
        if dst_mod == target_module and (not target_port or dst_port == target_port):
            return True
        frontier.append(dst_mod)

    seen = {source_module}
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        for src_mod, src_port, dst_mod, dst_port in edge_modules:
            if src_mod != current or dst_mod is None:
                continue
            if dst_mod == target_module and (not target_port or dst_port == target_port):
                return True
            frontier.append(dst_mod)
    return False


def evaluate_spec_reg_checks(case: dict[str, Any], spec: Any | None) -> tuple[bool | None, list[str]]:
    checks = case.get("expected_spec_checks") or {}
    if not checks:
        return None, []
    failures: list[str] = []
    if not isinstance(spec, dict):
        return False, ["SpecReg artifact missing or unreadable"]

    ports = spec.get("ports") or []
    if not isinstance(ports, list):
        failures.append("SpecReg.ports is not a list")
        ports = []
    port_by_name = {str(p.get("name")): p for p in ports if isinstance(p, dict) and p.get("name")}

    expected_top_ports = checks.get("required_top_ports") or []
    if checks.get("exact_top_ports"):
        expected_names = {str(item["name"]) for item in expected_top_ports}
        actual_names = set(port_by_name)
        if actual_names != expected_names:
            failures.append(f"top port set mismatch: expected {sorted(expected_names)}, got {sorted(actual_names)}")

    for expected in expected_top_ports:
        name = str(expected.get("name"))
        actual = port_by_name.get(name)
        if actual is None:
            failures.append(f"missing top port {name}")
            continue
        for field in ["direction", "net_type", "is_clock", "is_reset"]:
            if field in expected and _enum_value(actual.get(field)) != expected[field]:
                failures.append(f"top port {name}.{field} expected {expected[field]!r}, got {actual.get(field)!r}")
        if "width" in expected and not _width_matches(actual.get("width"), expected["width"]):
            failures.append(f"top port {name}.width expected {expected['width']!r}, got {actual.get('width')!r}")

    actual_cr = spec.get("clock_and_reset") or []
    for expected in checks.get("required_clock_resets") or []:
        found = False
        for cr in actual_cr if isinstance(actual_cr, list) else []:
            if not isinstance(cr, dict):
                continue
            if (
                cr.get("clock_name") == expected.get("clock_name")
                and cr.get("reset_name") == expected.get("reset_name")
                and _enum_value(cr.get("reset_type")) == expected.get("reset_type")
            ):
                found = True
                break
        if not found:
            failures.append(f"missing clock/reset definition {expected}")

    nodes = spec.get("nodes") or []
    if not isinstance(nodes, list):
        failures.append("SpecReg.nodes is not a list")
        nodes = []
    node_by_id = {str(n.get("node_id")): n for n in nodes if isinstance(n, dict) and n.get("node_id")}
    module_nodes = [n for n in nodes if isinstance(n, dict) and _enum_value(n.get("node_type")) == "module"]
    module_names = [str(n.get("module_name")) for n in module_nodes if n.get("module_name")]

    exact_module_names = checks.get("exact_module_names")
    if exact_module_names is not None and set(module_names) != set(exact_module_names):
        failures.append(f"module node set mismatch: expected {sorted(exact_module_names)}, got {sorted(module_names)}")

    expected_module_count = checks.get("expected_module_node_count")
    if expected_module_count is not None and len(module_nodes) != int(expected_module_count):
        failures.append(f"module node count {len(module_nodes)} != {expected_module_count}")

    for expected in checks.get("required_module_nodes") or []:
        module_name = str(expected.get("module_name"))
        matches = [n for n in module_nodes if n.get("module_name") == module_name]
        if not matches:
            failures.append(f"missing module node {module_name}")
            continue
        if len(matches) > 1:
            failures.append(f"module node {module_name} appears {len(matches)} times")
        actual = matches[0]
        for field in ["file_name", "is_rtl_file", "parent_node_id"]:
            if field in expected and actual.get(field) != expected[field]:
                failures.append(f"module node {module_name}.{field} expected {expected[field]!r}, got {actual.get(field)!r}")

    edges = spec.get("edges") or []
    if not isinstance(edges, list):
        failures.append("SpecReg.edges is not a list")
        edges = []
    for expected in checks.get("required_edge_paths") or []:
        if not any(isinstance(edge, dict) and _edge_matches_requirement(edge, expected, node_by_id) for edge in edges):
            failures.append(f"missing required direct edge {expected}")
    for expected in checks.get("required_graph_paths") or []:
        if not _has_required_graph_path(edges, expected, node_by_id):
            failures.append(f"missing required graph path {expected}")

    text_groups = checks.get("required_text_keyword_groups") or {}
    for field, groups in text_groups.items():
        _append_keyword_group_failures(failures, spec.get(field) or [], groups, f"SpecReg.{field}")

    return len(failures) == 0, failures


def _collect_rtl_sources(paths: dict[str, Path]) -> list[Path]:
    rtl_dir = paths.get("rtl_dir")
    if rtl_dir is not None and rtl_dir.exists():
        files = sorted(p for p in rtl_dir.glob("*.v") if p.is_file())
        if files:
            return files
    rtl_path = paths.get("rtl")
    if rtl_path is not None and rtl_path.exists():
        return [rtl_path]
    return []


def _strip_verilog_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def _split_verilog_port_items(header: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    bracket_depth = 0
    for ch in header:
        if ch == "[":
            bracket_depth += 1
        elif ch == "]" and bracket_depth > 0:
            bracket_depth -= 1
        if ch == "," and bracket_depth == 0:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
        else:
            current.append(ch)
    item = "".join(current).strip()
    if item:
        items.append(item)
    return items


def _declared_module_ports(verilog_text: str, module_name: str) -> list[str] | None:
    text = _strip_verilog_comments(verilog_text)
    match = re.search(rf"\bmodule\s+{re.escape(module_name)}\s*\((.*?)\)\s*;", text, flags=re.S)
    if not match:
        return None
    ports: list[str] = []
    for item in _split_verilog_port_items(match.group(1)):
        names = re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", item)
        # Drop common declaration/type words and keep the declared port identifiers.
        names = [n for n in names if n not in {"input", "output", "inout", "wire", "reg", "signed"}]
        if names:
            ports.append(names[-1])
    return ports


def evaluate_rtl_checks(case: dict[str, Any], paths: dict[str, Path]) -> tuple[bool | None, list[str], dict[str, Any]]:
    checks = case.get("expected_rtl_checks") or {}
    if not checks:
        return None, [], {}
    failures: list[str] = []
    rtl_sources = _collect_rtl_sources(paths)
    facts: dict[str, Any] = {
        "rtl_file_count": len(rtl_sources),
        "rtl_files": [str(p.relative_to(REPO_ROOT)) for p in rtl_sources],
    }
    if not rtl_sources:
        return False, ["no RTL sources found"], facts

    texts = {p: p.read_text(encoding="utf-8", errors="replace") for p in rtl_sources}
    combined = "\n".join(texts.values())
    combined_no_comments = _strip_verilog_comments(combined)
    declared_modules = re.findall(r"(?m)^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)\b", combined_no_comments)
    facts["rtl_module_declarations"] = sorted(set(declared_modules))

    for module_name in checks.get("required_module_declarations") or []:
        if module_name not in declared_modules:
            failures.append(f"missing RTL module declaration {module_name}")

    for module_name, expected_ports in (checks.get("required_module_ports") or {}).items():
        actual_ports = _declared_module_ports(combined, str(module_name))
        facts[f"rtl_ports_{module_name}"] = actual_ports
        if actual_ports is None:
            failures.append(f"missing RTL module declaration {module_name}")
            continue
        missing_ports = [port for port in expected_ports if port not in actual_ports]
        if missing_ports:
            failures.append(f"module {module_name} missing ports {missing_ports}; actual={actual_ports}")
        if checks.get("exact_module_ports") and set(actual_ports) != set(expected_ports):
            failures.append(f"module {module_name} port set mismatch: expected {expected_ports}, actual={actual_ports}")

    for file_name in checks.get("required_files") or []:
        if not any(p.name == file_name for p in rtl_sources):
            failures.append(f"missing RTL file {file_name}")

    for item in checks.get("required_top_instantiations") or []:
        module_name = str(item)
        # Verilog-2001 instance, optionally parameterized: module_name #( ... ) inst_name (...)
        pattern = rf"\b{re.escape(module_name)}\s*(?:#\s*\([^;]*?\)\s*)?[A-Za-z_][A-Za-z0-9_$]*\s*\("
        if not re.search(pattern, combined_no_comments, flags=re.S):
            failures.append(f"missing instantiation of {module_name}")

    for token in checks.get("forbidden_tokens") or []:
        if re.search(rf"\b{re.escape(str(token))}\b", combined_no_comments):
            failures.append(f"forbidden RTL/SystemVerilog token present: {token}")

    for file_name, groups in (checks.get("required_file_keyword_groups") or {}).items():
        matching_sources = [p for p in rtl_sources if p.name == file_name]
        if not matching_sources:
            failures.append(f"cannot check required keywords for missing RTL file {file_name}")
            continue
        file_text = _strip_verilog_comments(matching_sources[0].read_text(encoding="utf-8", errors="replace"))
        for group in groups:
            if not _keyword_group_present(file_text, group):
                failures.append(f"RTL file {file_name} missing keyword group: {group}")

    return len(failures) == 0, failures, facts


def summarize_artifacts(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    task_id = task_dir_from_response(response)
    summary: dict[str, Any] = {
        "case_id": case["case_id"],
        "top_module": case["top_module"],
        "prompt_type": case.get("prompt_type"),
        "category": case.get("category"),
        "difficulty": case.get("difficulty"),
        "task_id": task_id,
        "api_status": response.get("status") if isinstance(response, dict) else None,
        "api_message": response.get("message") if isinstance(response, dict) else None,
    }
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        summary.update(
            {
                "workflow_success": data.get("success"),
                "final_stage": data.get("final_stage"),
                "trace_len": len(data.get("trace") or []),
            }
        )

    if not task_id:
        if case.get("expected_user_spec_checks") or case.get("expected_spec_checks") or case.get("expected_rtl_checks"):
            summary["strict_static_check_pass"] = False
            summary["strict_static_check_failures"] = ["workflow did not return task_id; artifacts unavailable"]
        return summary

    paths = find_result_paths(task_id, case["top_module"])
    verify = read_json_if_exists(paths["verify_rpt"])
    spec = read_json_if_exists(paths["spec_reg"])
    user_spec = read_json_if_exists(paths["user_task_spec"])

    if isinstance(user_spec, dict):
        requirements = user_spec.get("refined_requirements") or []
        if isinstance(requirements, list):
            summary["user_spec_requirement_count"] = len(requirements)
            summary["user_spec_longest_requirement_chars"] = max((len(str(item)) for item in requirements), default=0)
    user_spec_pass, user_spec_failures = evaluate_user_spec_checks(case, user_spec)
    if user_spec_pass is not None:
        summary["user_spec_check_pass"] = user_spec_pass
        summary["user_spec_check_failure_count"] = len(user_spec_failures)
        summary["user_spec_check_failures"] = user_spec_failures

    if isinstance(verify, dict):
        summary["verify_verdict"] = verify.get("verdict")
        err = verify.get("error_details") or {}
        if isinstance(err, dict):
            summary["compile_error_count"] = len(err.get("compile_errors") or [])
            summary["mismatched_port_count"] = len(err.get("mismatched_ports") or [])
            summary["infra_error_count"] = len(err.get("infra_errors") or [])
    if isinstance(spec, dict):
        summary["spec_size_bytes"] = paths["spec_reg"].stat().st_size if paths["spec_reg"].exists() else None
        summary["port_count"] = len(spec.get("ports") or [])
        summary["functional_requirement_count"] = len(spec.get("functional_requirements") or [])
        summary["corner_case_count"] = len(spec.get("corner_cases") or [])
        summary["clock_and_reset_count"] = len(spec.get("clock_and_reset") or [])
        ports = spec.get("ports") or []
        summary["is_clock_count"] = sum(1 for p in ports if isinstance(p, dict) and p.get("is_clock"))
        summary["is_reset_count"] = sum(1 for p in ports if isinstance(p, dict) and p.get("is_reset"))
    spec_pass, spec_failures = evaluate_spec_reg_checks(case, spec)
    if spec_pass is not None:
        summary["spec_check_pass"] = spec_pass
        summary["spec_check_failure_count"] = len(spec_failures)
        summary["spec_check_failures"] = spec_failures

    rtl_sources = _collect_rtl_sources(paths)
    if rtl_sources:
        summary["rtl_size_bytes"] = sum(p.stat().st_size for p in rtl_sources)
        summary["rtl_file_count"] = len(rtl_sources)
    rtl_pass, rtl_failures, rtl_facts = evaluate_rtl_checks(case, paths)
    summary.update(rtl_facts)
    if rtl_pass is not None:
        summary["rtl_check_pass"] = rtl_pass
        summary["rtl_check_failure_count"] = len(rtl_failures)
        summary["rtl_check_failures"] = rtl_failures

    strict_results = [value for value in [user_spec_pass, spec_pass, rtl_pass] if value is not None]
    if strict_results:
        strict_failures = user_spec_failures + spec_failures + rtl_failures
        summary["strict_static_check_pass"] = all(strict_results)
        summary["strict_static_check_failure_count"] = len(strict_failures)
        summary["strict_static_check_failures"] = strict_failures
    llm_dir = paths["llm_dir"]
    summary["architect_repair_frame_count"] = 0
    summary["llm_transcript_count"] = 0
    summary["parser_chat_count"] = 0
    summary["architect_chat_count"] = 0
    summary["coder_chat_count"] = 0
    summary["verify_chat_count"] = 0
    if llm_dir.exists():
        summary["architect_repair_frame_count"] = len(list(llm_dir.glob("ArchitectRepairFrame_*.json")))
        summary["llm_transcript_count"] = len(list(llm_dir.glob("*.json")))
        summary["parser_chat_count"] = len(list(llm_dir.glob("ParserChat_iter*.json")))
        summary["architect_chat_count"] = len(list(llm_dir.glob("ArchitectChat_iter*.json")))
        summary["coder_chat_count"] = len(list(llm_dir.glob("CoderChat_iter*.json")))
        summary["verify_chat_count"] = len(list(llm_dir.glob("VerifyChat_iter*.json")))
    return summary


def host_iverilog_available() -> bool:
    return shutil.which("iverilog") is not None and shutil.which("vvp") is not None


def run_smoke_tb(
    case: dict[str, Any],
    task_id: str | None,
    *,
    result_dir: Path,
    compose: list[str],
    timeout_s: int,
) -> dict[str, Any]:
    tb_path = SUITE_ROOT / "testbenches" / f"{case['case_id']}_tb.v"
    result = {
        "tb_available": tb_path.exists(),
        "tb_pass": None,
        "tb_mode": None,
        "tb_stdout_path": None,
        "tb_stderr_path": None,
    }
    if not tb_path.exists() or not task_id:
        return result
    paths = find_result_paths(task_id, case["top_module"])
    rtl_sources = _collect_rtl_sources(paths)
    if not rtl_sources:
        result["tb_pass"] = False
        result["tb_error"] = f"missing RTL sources under: {paths['rtl_dir']}"
        return result

    stdout_path = result_dir / "smoke_tb.stdout.log"
    stderr_path = result_dir / "smoke_tb.stderr.log"
    out_path = result_dir / "smoke_tb.out"

    if host_iverilog_available():
        cmd = ["iverilog", "-g2001", "-o", str(out_path), str(tb_path)] + [str(p) for p in rtl_sources]
        comp = run_cmd(cmd, timeout=timeout_s)
        if comp.returncode == 0:
            sim = run_cmd(["vvp", str(out_path)], timeout=timeout_s)
            stdout = comp.stdout + sim.stdout
            stderr = comp.stderr + sim.stderr
            rc = sim.returncode
        else:
            stdout = comp.stdout
            stderr = comp.stderr
            rc = comp.returncode
        result["tb_mode"] = "host_iverilog"
    else:
        # Fallback: copy TB into output task dir so evaluate container can access it via /ICU-MUJICA/output mount.
        tb_copy = paths["task_base"] / "eval_smoke_tb.v"
        shutil.copyfile(tb_path, tb_copy)
        rel_tb = tb_copy.relative_to(REPO_ROOT)
        container_tb = f"/ICU-MUJICA/{rel_tb.as_posix()}"
        container_rtls = []
        for rtl_source in rtl_sources:
            rel_rtl = rtl_source.relative_to(REPO_ROOT)
            container_rtls.append(f"/ICU-MUJICA/{rel_rtl.as_posix()}")
        container_out = f"/tmp/{case['case_id']}_{task_id}.out"
        shell = " ".join(["iverilog", "-g2001", "-o", container_out, container_tb] + container_rtls) + f" && vvp {container_out}"
        sim = run_cmd(compose + ["exec", "-T", "evaluate", "sh", "-lc", shell], timeout=timeout_s)
        stdout = sim.stdout
        stderr = sim.stderr
        rc = sim.returncode
        result["tb_mode"] = "verify_container"

    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    result["tb_pass"] = rc == 0
    result["tb_stdout_path"] = str(stdout_path.relative_to(REPO_ROOT))
    result["tb_stderr_path"] = str(stderr_path.relative_to(REPO_ROOT))
    return result


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def maybe_clean_shared_workspace() -> None:
    root = REPO_ROOT / "shared_workspace"
    if not root.exists():
        return
    for child in root.iterdir():
        if child.name == ".gitignore":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ICU-MUJICA phase1 eval suite")
    parser.add_argument("--profiles", nargs="+", default=["gpt", "ds"], help="env profiles, mapped to .env.<profile>")
    parser.add_argument("--cases", default=str(DEFAULT_CASE_LIST), help="case list JSON path")
    parser.add_argument("--select", nargs="*", help="optional case_id filter")
    parser.add_argument("--parser-url", default=PARSER_URL_DEFAULT)
    parser.add_argument("--max-iterations", type=int, default=None, help="override case max_iterations")
    parser.add_argument("--request-timeout", type=int, default=900)
    parser.add_argument("--service-timeout", type=int, default=None, help="override parser->execute/evaluate service timeout seconds for this run")
    parser.add_argument("--health-timeout", type=int, default=180)
    parser.add_argument("--tb-timeout", type=int, default=60)
    parser.add_argument("--rebuild", action="store_true", help="rebuild docker images before each run; default is up/down only")
    parser.add_argument("--no-docker-reset", action="store_true", help="do not docker compose down/up before each run")
    parser.add_argument("--clean-shared-workspace", action="store_true", help="delete shared_workspace contents except .gitignore before each run")
    parser.add_argument("--keep-env", action="store_true", help="leave last copied .env in place instead of restoring previous .env")
    parser.add_argument("--no-explicit-llm", action="store_true", help="do not include llm runtime config in workflow payload; rely on container env only")
    parser.add_argument("--dry-run", action="store_true", help="print run plan without executing docker/API calls")
    args = parser.parse_args()

    case_list = Path(args.cases).resolve()
    cases = load_cases(case_list, set(args.select) if args.select else None)
    run_id = f"run_{now_tag()}"
    results_root = DEFAULT_RESULTS_ROOT / run_id
    results_root.mkdir(parents=True, exist_ok=True)

    backup = backup_current_env()
    all_rows: list[dict[str, Any]] = []
    compose: list[str] | None = None
    if not args.dry_run:
        compose = docker_compose_cmd()

    plan = {
        "run_id": run_id,
        "profiles": args.profiles,
        "case_count": len(cases),
        "cases": [c["case_id"] for c in cases],
        "parser_url": args.parser_url,
        "max_iterations_override": args.max_iterations,
        "service_timeout_override": args.service_timeout,
        "docker_reset_per_run": not args.no_docker_reset,
        "rebuild": args.rebuild,
        "clean_shared_workspace": args.clean_shared_workspace,
        "explicit_llm_payload": not args.no_explicit_llm,
    }
    (results_root / "run_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2))

    try:
        if args.dry_run:
            return 0
        assert compose is not None
        for profile in args.profiles:
            env_values, env_summary = copy_env_for_profile(profile)
            apply_service_timeout_override(env_values, env_summary, args.service_timeout)
            llm_payload = build_llm_payload_from_env(env_values)
            expected_llm_enabled = bool(llm_payload.get("enabled"))
            profile_dir = results_root / profile
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "env_summary.redacted.json").write_text(
                json.dumps(env_summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            for case in cases:
                case_id = case["case_id"]
                result_dir = profile_dir / case_id
                result_dir.mkdir(parents=True, exist_ok=True)
                print(f"\n=== profile={profile} case={case_id} ===", flush=True)

                if args.clean_shared_workspace:
                    maybe_clean_shared_workspace()

                if not args.no_docker_reset:
                    reset_docker(compose, rebuild=args.rebuild, logs_dir=result_dir / "docker_logs")
                    wait_parser_ready(args.parser_url, timeout_s=args.health_timeout)

                max_iterations = args.max_iterations if args.max_iterations is not None else int(case.get("max_iterations", 3))
                payload = {
                    "top_module": case["top_module"],
                    "raw_input_text": case["raw_input_text"],
                    "max_iterations": max_iterations,
                }
                if not args.no_explicit_llm:
                    payload["llm"] = llm_payload
                (result_dir / "request_payload.json").write_text(
                    json.dumps(redact_payload(payload), ensure_ascii=False, indent=2), encoding="utf-8"
                )

                started = time.time()
                response = post_workflow(args.parser_url, payload, timeout_s=args.request_timeout)
                elapsed = time.time() - started
                (result_dir / "api_response.json").write_text(
                    json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
                )

                summary = summarize_artifacts(case, response)
                summary.update(
                    {
                        "run_id": run_id,
                        "profile": profile,
                        "elapsed_seconds": round(elapsed, 3),
                        "max_iterations": max_iterations,
                        "env_model": env_summary.get("ICU_MUJICA_LLM_MODEL") or env_summary.get("AGVS4RTL_LLM_MODEL"),
                        "env_reasoning_effort": env_summary.get("ICU_MUJICA_LLM_REASONING_EFFORT") or env_summary.get("AGVS4RTL_LLM_REASONING_EFFORT"),
                        "env_profile": env_summary.get("ICU_MUJICA_LLM_PROFILE") or env_summary.get("AGVS4RTL_LLM_PROFILE"),
                        "expected_llm_enabled": expected_llm_enabled,
                        "explicit_llm_payload": not args.no_explicit_llm,
                    }
                )
                summary["invalid_llm_not_used"] = bool(
                    expected_llm_enabled
                    and summary.get("workflow_success") is True
                    and (int(summary.get("architect_chat_count") or 0) + int(summary.get("coder_chat_count") or 0)) == 0
                )
                tb = run_smoke_tb(case, summary.get("task_id"), result_dir=result_dir, compose=compose, timeout_s=args.tb_timeout)
                summary.update(tb)
                (result_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                all_rows.append(summary)
                write_csv(all_rows, results_root / "summary.csv")
                print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    finally:
        restore_env(backup, keep_env=args.keep_env)

    write_csv(all_rows, results_root / "summary.csv")
    (results_root / "summary.json").write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults written to: {results_root.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
