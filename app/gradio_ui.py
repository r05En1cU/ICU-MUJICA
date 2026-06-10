from __future__ import annotations

import concurrent.futures
import json
import os
import html
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import gradio as gr
import httpx


DEFAULT_PARSER_URL = os.getenv("ICU_MUJICA_PARSER_URL", "http://127.0.0.1:8001")
DEFAULT_OUTPUT_ROOT = Path(os.getenv("ICU_MUJICA_OUTPUT_ROOT", "output"))
DEFAULT_SHARED_ROOT = Path(os.getenv("ICU_MUJICA_SHARED_ROOT", "shared_workspace"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("ICU_MUJICA_UI_TIMEOUT_SECONDS", "480"))
UI_POLL_SECONDS = max(0.5, float(os.getenv("ICU_MUJICA_UI_POLL_SECONDS", "2")))

AGENT_ORDER = ["Parser", "Execute", "Evaluate", "Archive"]
NODE_TO_AGENT = {
    "parser_initialize": "Parser",
    "execute_stateless": "Execute",
    "evaluate_stateless": "Evaluate",
    "prepare_retry": "Parser",
    "archive_success": "Archive",
    "archive_failed": "Archive",
}
AGENT_WEIGHTS = {
    "Parser": 15,
    "Execute": 40,
    "Evaluate": 30,
    "Archive": 15,
}
BOX_NODE_RE = re.compile(r'^\s*(?P<id>[A-Za-z_][A-Za-z0-9_]*)\["(?P<label>.*?)"\]\s*$')
PORT_NODE_RE = re.compile(r'^\s*(?P<id>[A-Za-z_][A-Za-z0-9_]*)\(\("(?P<label>.*?)"\)\)\s*$')
EDGE_RE = re.compile(
    r'^\s*(?P<source>[A-Za-z_][A-Za-z0-9_]*)\s*-->\s*'
    r'(?:\|"(?P<label>.*?)"\|\s*)?(?P<target>[A-Za-z_][A-Za-z0-9_]*)\s*$'
)


def _normalize_parser_url(parser_url: str) -> str:
    parser_url = parser_url.strip().rstrip("/")
    if not parser_url:
        raise ValueError("Parser URL cannot be empty")
    return parser_url


def _initial_status_rows() -> List[List[Any]]:
    return [[agent, "waiting", 0, "-", "-", "-", "-"] for agent in AGENT_ORDER]


def _running_status_rows() -> List[List[Any]]:
    rows = _initial_status_rows()
    rows[0] = ["Parser", "running", 10, "workflow request", 0, "request submitted to Parser", "-"]
    return rows


def _agent_progress_from_trace(trace: Iterable[Dict[str, Any]]) -> Tuple[List[List[Any]], int]:
    latest: Dict[str, Dict[str, Any]] = {}
    completed_weight = 0
    failed = False

    for step in trace:
        agent = NODE_TO_AGENT.get(str(step.get("node", "")), "Parser")
        latest[agent] = step
        if step.get("status") == "success":
            completed_weight += AGENT_WEIGHTS.get(agent, 0)
        else:
            failed = True

    completed_weight = min(completed_weight, 100)
    rows: List[List[Any]] = []
    for agent in AGENT_ORDER:
        step = latest.get(agent)
        if step is None:
            rows.append([agent, "waiting", 0, "-", "-", "-", "-"])
            continue

        status = "failed" if step.get("status") == "error" else "completed"
        rows.append(
            [
                agent,
                status,
                100,
                step.get("node", "-"),
                step.get("iteration", "-"),
                step.get("detail", "-"),
                step.get("created_at", "-"),
            ]
        )

    if failed:
        return rows, completed_weight
    return rows, 100 if completed_weight >= 100 else completed_weight


def _build_request_payload(
    top_module: str,
    raw_input_text: str,
    refined_requirements_text: str,
    max_iterations: int,
    llm_enabled: bool,
    llm_base_url: str,
    llm_model: str,
    llm_api_key: str,
    llm_profile: str,
    llm_reasoning_effort: str,
) -> Dict[str, Any]:
    refined_requirements = [line.strip() for line in refined_requirements_text.splitlines() if line.strip()]
    payload: Dict[str, Any] = {
        "top_module": top_module.strip(),
        "raw_input_text": raw_input_text.strip(),
        "refined_requirements": refined_requirements,
        "max_iterations": int(max_iterations),
    }

    if llm_enabled:
        payload["llm"] = {
            "enabled": True,
            "base_url": llm_base_url.strip() or None,
            "model": llm_model.strip() or None,
            "api_key": llm_api_key.strip() or None,
            "profile": llm_profile.strip() or "default",
            "reasoning_effort": llm_reasoning_effort.strip() or None,
        }

    return payload


def _summarize_result(response_payload: Dict[str, Any]) -> str:
    if response_payload.get("status") != "success" or response_payload.get("data") is None:
        return f"Request failed: {response_payload.get('message', 'unknown error')}"

    data = response_payload["data"]
    verify_output = data.get("verify_output") or {}
    report = verify_output.get("report") or {}
    verdict = report.get("verdict", "unknown")
    task_id = data.get("task_id", "-")
    final_stage = data.get("final_stage", "-")
    success = data.get("success", False)

    lines = [
        f"Task: {task_id}",
        f"Workflow: {'success' if success else 'failed'}",
        f"Final stage: {final_stage}",
        f"Verify verdict: {verdict}",
    ]

    gen_output = data.get("gen_output") or {}
    if gen_output.get("summary"):
        lines.append(f"Generator: {gen_output['summary']}")
    if verify_output.get("summary"):
        lines.append(f"Verify: {verify_output['summary']}")

    return "\n".join(lines)


def _artifact_rows(task_id: Optional[str], output_root: Path = DEFAULT_OUTPUT_ROOT) -> List[List[str]]:
    if not task_id:
        return []

    task_dir = output_root / task_id
    if not task_dir.exists():
        return []

    rows: List[List[str]] = []
    for artifact_path in sorted(path for path in task_dir.rglob("*") if path.is_file()):
        try:
            relative_path = artifact_path.relative_to(output_root)
        except ValueError:
            relative_path = artifact_path
        rows.append([str(relative_path), str(artifact_path.stat().st_size)])
    return rows


def _shared_artifact_rows(task_id: Optional[str], shared_root: Path = DEFAULT_SHARED_ROOT) -> List[List[str]]:
    if not task_id:
        return []

    task_dir = shared_root / task_id
    if not task_dir.exists():
        return []

    rows: List[List[str]] = []
    for artifact_path in sorted(path for path in task_dir.rglob("*") if path.is_file()):
        try:
            relative_path = artifact_path.relative_to(shared_root)
        except ValueError:
            relative_path = artifact_path
        rows.append([str(relative_path), str(artifact_path.stat().st_size)])
    return rows


def _latest_task_id(*, include_shared: bool = True, include_output: bool = True) -> Optional[str]:
    task_dirs: List[Path] = []
    if include_shared and DEFAULT_SHARED_ROOT.exists():
        task_dirs.extend(path for path in DEFAULT_SHARED_ROOT.glob("TASK_*") if path.is_dir())
    if include_output and DEFAULT_OUTPUT_ROOT.exists():
        task_dirs.extend(path for path in DEFAULT_OUTPUT_ROOT.glob("TASK_*") if path.is_dir())
    if not task_dirs:
        return None

    latest = max(task_dirs, key=lambda path: path.stat().st_mtime)
    return latest.name


def _known_task_ids() -> set[str]:
    task_ids: set[str] = set()
    if DEFAULT_SHARED_ROOT.exists():
        task_ids.update(path.name for path in DEFAULT_SHARED_ROOT.glob("TASK_*") if path.is_dir())
    if DEFAULT_OUTPUT_ROOT.exists():
        task_ids.update(path.name for path in DEFAULT_OUTPUT_ROOT.glob("TASK_*") if path.is_dir())
    return task_ids


def _latest_new_task_id(known_task_ids: set[str]) -> Optional[str]:
    task_dirs: List[Path] = []
    if DEFAULT_SHARED_ROOT.exists():
        task_dirs.extend(path for path in DEFAULT_SHARED_ROOT.glob("TASK_*") if path.is_dir() and path.name not in known_task_ids)
    if DEFAULT_OUTPUT_ROOT.exists():
        task_dirs.extend(path for path in DEFAULT_OUTPUT_ROOT.glob("TASK_*") if path.is_dir() and path.name not in known_task_ids)
    if not task_dirs:
        return None
    return max(task_dirs, key=lambda path: path.stat().st_mtime).name


def _task_exists_in_shared(task_id: Optional[str]) -> bool:
    return bool(task_id) and (DEFAULT_SHARED_ROOT / str(task_id)).exists()


def _artifacts_for_task(task_id: Optional[str]) -> List[List[str]]:
    return _shared_artifact_rows(task_id) + _artifact_rows(task_id)


def _is_archived_task(task_id: str) -> bool:
    output_task_dir = DEFAULT_OUTPUT_ROOT / task_id
    return (output_task_dir / "Result" / "shared_workspace").exists() or (output_task_dir / "Archive" / "shared_workspace").exists()


def _unfinished_task_ids() -> List[str]:
    task_ids: set[str] = set()
    if DEFAULT_SHARED_ROOT.exists():
        task_ids.update(path.name for path in DEFAULT_SHARED_ROOT.glob("TASK_*") if path.is_dir())
    if DEFAULT_OUTPUT_ROOT.exists():
        task_ids.update(path.name for path in DEFAULT_OUTPUT_ROOT.glob("TASK_*") if path.is_dir() and not _is_archived_task(path.name))
    return sorted(task_ids, reverse=True)


def _unfinished_task_rows() -> List[List[str]]:
    rows: List[List[str]] = []
    for task_id in _unfinished_task_ids():
        shared_task_dir = DEFAULT_SHARED_ROOT / task_id
        output_task_dir = DEFAULT_OUTPUT_ROOT / task_id
        spec_files = sorted((shared_task_dir / "specs").glob("SpecReg_iter*.json")) if shared_task_dir.exists() else []
        rtl_files = sorted((shared_task_dir / "rtl").glob("*.v")) if shared_task_dir.exists() else []
        verify_files = sorted((shared_task_dir / "sim").glob("VerifyRpt_iter*.json")) if shared_task_dir.exists() else []
        origin_path = output_task_dir / "Origin" / "request.txt"
        if verify_files:
            stage = "evaluate"
        elif rtl_files or spec_files:
            stage = "execute"
        elif origin_path.exists():
            stage = "parser"
        else:
            stage = "unknown"
        paths = [path for path in [shared_task_dir, output_task_dir] if path.exists()]
        latest_mtime = max((path.stat().st_mtime for path in paths), default=0)
        rows.append([
            task_id,
            stage,
            str(len(spec_files)),
            str(len(rtl_files)),
            str(len(verify_files)),
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest_mtime)) if latest_mtime else "-",
        ])
    return rows


def _task_choices() -> List[str]:
    return _unfinished_task_ids()


def _running_snapshot(task_id: Optional[str], started_at: float) -> Tuple[str, int, List[List[Any]]]:
    rows = _initial_status_rows()
    elapsed = max(0, int(time.monotonic() - started_at))
    if not task_id:
        rows[0] = ["Parser", "running", 10, "workflow request", 0, "waiting for task workspace", "-"]
        return f"Request submitted to Parser\nElapsed: {elapsed}s\nWaiting for task workspace...", 10, rows

    shared_task_dir = DEFAULT_SHARED_ROOT / task_id
    output_task_dir = DEFAULT_OUTPUT_ROOT / task_id
    result_dir = output_task_dir / "Result" / "shared_workspace"
    archive_dir = output_task_dir / "Archive" / "shared_workspace"
    artifact_roots = [root for root in [shared_task_dir, result_dir, archive_dir] if root.exists()]
    parser_chat_candidates = [root / "llm" / "ParserChat_iter0.json" for root in artifact_roots]
    user_task_spec_candidates = [root / "specs" / "UserTaskSpec.json" for root in artifact_roots]
    parser_chat = next((path for path in parser_chat_candidates if path.exists()), shared_task_dir / "llm" / "ParserChat_iter0.json")
    user_task_spec = next((path for path in user_task_spec_candidates if path.exists()), shared_task_dir / "specs" / "UserTaskSpec.json")
    spec_files = sorted(path for root in artifact_roots for path in (root / "specs").glob("SpecReg_iter*.json"))
    rtl_files = sorted(path for root in artifact_roots for path in (root / "rtl").glob("*.v"))
    verify_files = sorted(path for root in artifact_roots for path in (root / "sim").glob("VerifyRpt_iter*.json"))

    parser_done = user_task_spec.exists()
    execute_done = bool(spec_files and rtl_files)
    evaluate_done = bool(verify_files)
    archived = result_dir.exists() or archive_dir.exists()

    rows[0] = [
        "Parser",
        "completed" if parser_done else "running",
        100 if parser_done else 30,
        "parser_initialize",
        0,
        "task spec saved" if parser_done else "building task spec",
        _mtime_text(user_task_spec if user_task_spec.exists() else parser_chat),
    ]
    rows[1] = [
        "Execute",
        "completed" if execute_done else ("running" if parser_done else "waiting"),
        100 if execute_done else (45 if parser_done else 0),
        "execute_stateless",
        _latest_iteration(spec_files),
        "RTL emitted" if rtl_files else ("executing RTL generation" if parser_done else "-"),
        _mtime_text(rtl_files[-1] if rtl_files else (spec_files[-1] if spec_files else None)),
    ]
    rows[2] = [
        "Evaluate",
        "completed" if evaluate_done else ("running" if execute_done else "waiting"),
        100 if evaluate_done else (65 if execute_done else 0),
        "evaluate_stateless",
        _latest_iteration(verify_files),
        "evaluate report saved" if evaluate_done else ("evaluating RTL" if execute_done else "-"),
        _mtime_text(verify_files[-1] if verify_files else None),
    ]
    rows[3] = [
        "Archive",
        "completed" if archived else ("running" if evaluate_done else "waiting"),
        100 if archived else (85 if evaluate_done else 0),
        "archive",
        "-",
        "artifacts archived" if archived else ("waiting for final archive" if evaluate_done else "-"),
        _mtime_text(result_dir if result_dir.exists() else archive_dir if archive_dir.exists() else None),
    ]

    progress = 10
    if parser_done:
        progress = 25
    if execute_done:
        progress = 65
    if evaluate_done:
        progress = 85
    if archived:
        progress = 100

    summary = [f"Task: {task_id}", "Workflow: running", f"Elapsed: {elapsed}s"]
    if parser_chat.exists():
        summary.append("Parser LLM trace is available")
    if spec_files:
        summary.append(f"Latest SpecReg: {spec_files[-1].name}")
    if rtl_files:
        summary.append(f"RTL files: {len(rtl_files)}")
    if verify_files:
        summary.append(f"Latest VerifyRpt: {verify_files[-1].name}")

    return "\n".join(summary), progress, rows


def _mtime_text(path: Optional[Path]) -> str:
    if path is None or not path.exists():
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime))


def _latest_iteration(paths: List[Path]) -> str:
    if not paths:
        return "-"
    match = re.search(r"iter(\d+)", paths[-1].name)
    return match.group(1) if match else "-"


def _read_first_existing(paths: Iterable[Path], max_chars: int = 12000) -> str:
    for path in paths:
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            return text[:max_chars]
    return ""


def _latest_glob_text(task_dir: Path, relative_glob: str) -> str:
    matches = sorted(task_dir.glob(relative_glob), key=lambda path: path.stat().st_mtime if path.exists() else 0)
    return _read_first_existing(reversed(matches))


def _spec_to_mermaid(spec_payload: Dict[str, Any]) -> str:
    top_module = str(spec_payload.get("top_module") or "TOP")
    lines = ["flowchart LR", f'    TOP["TOP: {top_module}"]']

    for port in spec_payload.get("ports") or []:
        if not isinstance(port, dict):
            continue
        name = str(port.get("name") or "port")
        port_id = f"port_{name}".replace("$", "_")
        direction = str(port.get("direction") or "")
        width = str(port.get("width") or "1")
        lines.append(f'    {port_id}(("{direction} {name}[{width}]"))')
        if direction == "output":
            lines.append(f'    TOP -->|"{name}[{width}]"| {port_id}')
        else:
            lines.append(f'    {port_id} -->|"{name}[{width}]"| TOP')

    for node in spec_payload.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("node_id") or "node")
        module_name = str(node.get("module_name") or node_id)
        lines.append(f'    {node_id}["{module_name}"]')

    for edge in spec_payload.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source") or {}
        target = edge.get("target") or {}
        if not isinstance(source, dict) or not isinstance(target, dict):
            continue
        source_id = "TOP" if source.get("node_id") == "TOP" else str(source.get("node_id") or "TOP")
        target_id = "TOP" if target.get("node_id") == "TOP" else str(target.get("node_id") or "TOP")
        signal = str(edge.get("signal_name") or "signal")
        width = str(edge.get("width") or "1")
        lines.append(f'    {source_id} -->|"{signal}[{width}]"| {target_id}')

    return "\n".join(lines) + "\n"


def _render_mermaid_svg(mermaid_text: str) -> str:
    node_map: Dict[str, Dict[str, str]] = {}
    edges: List[Dict[str, str]] = []

    for line in mermaid_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("flowchart") or stripped.startswith("graph"):
            continue

        edge_match = EDGE_RE.match(stripped)
        if edge_match is not None:
            edges.append(edge_match.groupdict(default=""))
            continue

        port_match = PORT_NODE_RE.match(stripped)
        if port_match is not None:
            node_map[port_match.group("id")] = {"label": port_match.group("label"), "kind": "port"}
            continue

        box_match = BOX_NODE_RE.match(stripped)
        if box_match is not None:
            node_map[box_match.group("id")] = {"label": box_match.group("label"), "kind": "box"}

    if not node_map:
        return "<div style='padding:12px;color:#666;'>No Mermaid graph available.</div>"

    incoming = {node_id: 0 for node_id in node_map}
    outgoing = {node_id: 0 for node_id in node_map}
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if source in outgoing:
            outgoing[source] += 1
        if target in incoming:
            incoming[target] += 1

    columns: Dict[str, int] = {}
    for node_id, node in node_map.items():
        label = node["label"].lower()
        if node["kind"] == "port" and incoming.get(node_id, 0) == 0:
            columns[node_id] = 0
        elif node["kind"] == "port" and outgoing.get(node_id, 0) == 0:
            columns[node_id] = 3
        elif node_id == "TOP" or label.startswith("top:"):
            columns[node_id] = 1
        else:
            columns[node_id] = 2

    column_nodes: Dict[int, List[str]] = {0: [], 1: [], 2: [], 3: []}
    for node_id in node_map:
        column_nodes.setdefault(columns.get(node_id, 2), []).append(node_id)

    node_width = 220
    node_height = 54
    x_gap = 92
    y_gap = 34
    margin = 32
    positions: Dict[str, Tuple[int, int]] = {}
    max_rows = 1

    for column, node_ids in column_nodes.items():
        max_rows = max(max_rows, len(node_ids))
        for row, node_id in enumerate(node_ids):
            positions[node_id] = (
                margin + column * (node_width + x_gap),
                margin + row * (node_height + y_gap),
            )

    width = margin * 2 + 4 * node_width + 3 * x_gap
    height = margin * 2 + max_rows * node_height + max(0, max_rows - 1) * y_gap
    marker_id = "arrowhead"
    svg_parts = [
        "<div style='width:100%;overflow:auto;border:1px solid #ddd;border-radius:8px;background:#fff;'>",
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}' role='img'>",
        "<defs>",
        f"<marker id='{marker_id}' markerWidth='10' markerHeight='8' refX='9' refY='4' orient='auto'>",
        "<path d='M 0 0 L 10 4 L 0 8 z' fill='#5b6472'/>",
        "</marker>",
        "</defs>",
        "<style>",
        ".node-text{font:13px sans-serif;fill:#172033}.edge-text{font:11px sans-serif;fill:#4b5563}",
        "</style>",
    ]

    for index, edge in enumerate(edges):
        source = edge["source"]
        target = edge["target"]
        if source not in positions or target not in positions:
            continue
        source_x, source_y = positions[source]
        target_x, target_y = positions[target]
        source_col = columns.get(source, 2)
        target_col = columns.get(target, 2)
        if source_col <= target_col:
            x1 = source_x + node_width
            x2 = target_x
        else:
            x1 = source_x
            x2 = target_x + node_width
        y1 = source_y + node_height / 2
        y2 = target_y + node_height / 2
        mid_x = (x1 + x2) / 2
        path = f"M {x1:.1f} {y1:.1f} C {mid_x:.1f} {y1:.1f}, {mid_x:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}"
        label = html.escape(edge.get("label") or "")
        svg_parts.append(
            f"<path d='{path}' fill='none' stroke='#5b6472' stroke-width='1.6' marker-end='url(#{marker_id})'/>"
        )
        if label:
            text_y = (y1 + y2) / 2 - 5 - (index % 3) * 3
            svg_parts.append(
                f"<text class='edge-text' x='{mid_x:.1f}' y='{text_y:.1f}' text-anchor='middle'>{label}</text>"
            )

    for node_id, node in node_map.items():
        x, y = positions[node_id]
        label = html.escape(node["label"])
        if node["kind"] == "port":
            svg_parts.append(
                f"<rect x='{x}' y='{y}' width='{node_width}' height='{node_height}' rx='27' fill='#eef7ff' stroke='#5b8def' stroke-width='1.4'/>"
            )
        else:
            fill = "#f4f7fb" if node_id == "TOP" else "#fff8e8"
            stroke = "#7f8aa3" if node_id == "TOP" else "#d19b2a"
            svg_parts.append(
                f"<rect x='{x}' y='{y}' width='{node_width}' height='{node_height}' rx='8' fill='{fill}' stroke='{stroke}' stroke-width='1.4'/>"
            )
        svg_parts.append(
            f"<text class='node-text' x='{x + node_width / 2:.1f}' y='{y + node_height / 2 + 5:.1f}' text-anchor='middle'>{label}</text>"
        )

    svg_parts.extend(["</svg>", "</div>"])
    return "".join(svg_parts)


def _preview_artifacts(
    task_id: Optional[str],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    shared_root: Path = DEFAULT_SHARED_ROOT,
) -> Tuple[str, str, str, str, str, Dict[str, Any]]:
    if not task_id:
        return "", "", "", "", _render_mermaid_svg(""), {}

    task_dir = output_root / task_id
    roots = [
        shared_root / task_id,
        task_dir / "Result" / "shared_workspace",
        task_dir / "Archive" / "shared_workspace",
    ]
    rtl_preview = ""
    spec_preview = ""
    verify_preview = ""
    mermaid_preview = ""
    graph_payload: Dict[str, Any] = {}

    for root in roots:
        if not root.exists():
            continue
        rtl_preview = rtl_preview or _read_first_existing((root / "rtl").glob("*.v"))
        spec_preview = spec_preview or _latest_glob_text(root, "specs/SpecReg_iter*.json")
        verify_preview = verify_preview or _latest_glob_text(root, "sim/VerifyRpt_iter*.json")
        mermaid_preview = mermaid_preview or _latest_glob_text(root, "graphs/HardwareGraph_iter*.mmd")
        graph_text = _latest_glob_text(root, "graphs/HardwareGraph_iter*.json")
        if graph_text and not graph_payload:
            try:
                graph_payload = json.loads(graph_text)
            except json.JSONDecodeError:
                graph_payload = {"raw": graph_text}

    if not mermaid_preview and spec_preview:
        try:
            mermaid_preview = _spec_to_mermaid(json.loads(spec_preview))
        except json.JSONDecodeError:
            mermaid_preview = ""

    return rtl_preview, spec_preview, verify_preview, mermaid_preview, _render_mermaid_svg(mermaid_preview), graph_payload


def check_parser(parser_url: str) -> Tuple[str, Dict[str, Any]]:
    try:
        base_url = _normalize_parser_url(parser_url)
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{base_url}/health")
            response.raise_for_status()
        payload = response.json()
        return "Parser is ready", payload
    except Exception as exc:  # noqa: BLE001
        return f"Parser check failed: {exc}", {"error": str(exc)}


def run_workflow(
    parser_url: str,
    top_module: str,
    raw_input_text: str,
    refined_requirements_text: str,
    max_iterations: int,
    llm_enabled: bool,
    llm_base_url: str,
    llm_model: str,
    llm_api_key: str,
    llm_profile: str,
    llm_reasoning_effort: str,
):
    try:
        base_url = _normalize_parser_url(parser_url)
        payload = _build_request_payload(
            top_module=top_module,
            raw_input_text=raw_input_text,
            refined_requirements_text=refined_requirements_text,
            max_iterations=max_iterations,
            llm_enabled=llm_enabled,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_api_key=llm_api_key,
            llm_profile=llm_profile,
            llm_reasoning_effort=llm_reasoning_effort,
        )
    except Exception as exc:  # noqa: BLE001
        error_payload = {"error": str(exc)}
        yield (
            f"Request build failed: {exc}",
            0,
            _initial_status_rows(),
            [],
            "",
            "",
            "",
            "",
            _render_mermaid_svg(""),
            {},
            error_payload,
        )
        return

    redacted_request = {"request": {**payload, "llm": {**payload.get("llm", {}), "api_key": "***" if llm_api_key else None}}}
    yield (
        "Request submitted to Parser",
        10,
        _running_status_rows(),
        [],
        "",
        "",
        "",
        "",
        _render_mermaid_svg(""),
        {},
        redacted_request,
    )

    known_task_ids = _known_task_ids()
    started_at = time.monotonic()
    task_id: Optional[str] = None

    def _post_workflow() -> Dict[str, Any]:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.post(f"{base_url}/v1/workflow/run", json=payload)
            response.raise_for_status()
            return response.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_post_workflow)
        while not future.done():
            task_id = task_id or _latest_new_task_id(known_task_ids)
            summary_text, progress_value, rows = _running_snapshot(task_id, started_at)
            artifacts = _artifacts_for_task(task_id)
            rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_payload = _preview_artifacts(task_id)
            yield (
                summary_text,
                progress_value,
                rows,
                artifacts,
                rtl_preview,
                spec_preview,
                verify_preview,
                mermaid_preview,
                mermaid_svg,
                graph_payload,
                redacted_request,
            )
            time.sleep(UI_POLL_SECONDS)

        try:
            response_payload = future.result()
        except Exception as exc:  # noqa: BLE001
            error_payload = {"error": str(exc)}
            rows = _running_status_rows()
            rows[0] = ["Parser", "failed", 10, "workflow request", 0, str(exc), "-"]
            yield (f"Request failed: {exc}", 10, rows, [], "", "", "", "", _render_mermaid_svg(""), {}, error_payload)
            return

    data = response_payload.get("data") or {}
    trace = data.get("trace") or []
    rows, progress = _agent_progress_from_trace(trace)
    task_id = data.get("task_id") or task_id
    artifacts = _artifacts_for_task(task_id)
    rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_payload = _preview_artifacts(task_id)

    yield (
        _summarize_result(response_payload),
        progress,
        rows,
        artifacts,
        rtl_preview,
        spec_preview,
        verify_preview,
        mermaid_preview,
        mermaid_svg,
        graph_payload,
        response_payload,
    )


def refresh_latest_output() -> Tuple[List[List[str]], str, int, List[List[Any]], str, str, str, str, str, Dict[str, Any]]:
    latest_task_id = _latest_task_id()
    if not latest_task_id:
        return [], "No output tasks found", 0, _initial_status_rows(), "", "", "", "", _render_mermaid_svg(""), {}

    summary_text, progress_value, rows = _running_snapshot(latest_task_id, time.monotonic())
    if not _task_exists_in_shared(latest_task_id):
        summary_text = f"Latest task: {latest_task_id}"
    rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_payload = _preview_artifacts(latest_task_id)
    return _artifacts_for_task(latest_task_id), summary_text, progress_value, rows, rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_payload


def refresh_unfinished_tasks() -> Tuple[List[List[str]], Dict[str, Any]]:
    choices = _task_choices()
    return _unfinished_task_rows(), gr.update(choices=choices, value=choices[0] if choices else None)


def inspect_unfinished_task(task_id: Optional[str]) -> Tuple[List[List[str]], str, int, List[List[Any]], str, str, str, str, str, Dict[str, Any]]:
    if not task_id:
        return [], "No unfinished task selected", 0, _initial_status_rows(), "", "", "", "", _render_mermaid_svg(""), {}
    summary_text, progress_value, rows = _running_snapshot(task_id, time.monotonic())
    rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_payload = _preview_artifacts(task_id)
    return _artifacts_for_task(task_id), summary_text, progress_value, rows, rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_payload


def delete_unfinished_task(task_id: Optional[str]) -> Tuple[List[List[str]], Dict[str, Any], str, List[List[str]], int, List[List[Any]], str, str, str, str, str, Dict[str, Any]]:
    if not task_id:
        choices = _task_choices()
        return _unfinished_task_rows(), gr.update(choices=choices, value=choices[0] if choices else None), "No unfinished task selected", [], 0, _initial_status_rows(), "", "", "", "", _render_mermaid_svg(""), {}

    deleted_paths = []
    for root in [DEFAULT_SHARED_ROOT, DEFAULT_OUTPUT_ROOT]:
        task_dir = root / task_id
        if task_dir.exists() and task_dir.is_dir():
            shutil.rmtree(task_dir)
            deleted_paths.append(str(task_dir))

    choices = _task_choices()
    message = f"Deleted task {task_id}: " + (", ".join(deleted_paths) if deleted_paths else "no directories found")
    return _unfinished_task_rows(), gr.update(choices=choices, value=choices[0] if choices else None), message, [], 0, _initial_status_rows(), "", "", "", "", _render_mermaid_svg(""), {}


def load_task_for_retry(task_id: Optional[str]) -> Tuple[str, str, str, List[List[str]], str, int, List[List[Any]], str, str, str, str, str, Dict[str, Any]]:
    if not task_id:
        return "", "", "No unfinished task selected", [], "No unfinished task selected", 0, _initial_status_rows(), "", "", "", "", _render_mermaid_svg(""), {}

    output_task_dir = DEFAULT_OUTPUT_ROOT / task_id
    user_spec_candidates = [
        output_task_dir / "UserTaskSpec.json",
        DEFAULT_SHARED_ROOT / task_id / "specs" / "UserTaskSpec.json",
        output_task_dir / "Result" / "shared_workspace" / "specs" / "UserTaskSpec.json",
        output_task_dir / "Archive" / "shared_workspace" / "specs" / "UserTaskSpec.json",
    ]
    user_spec_path = next((path for path in user_spec_candidates if path.exists()), user_spec_candidates[0])
    origin_path = output_task_dir / "Origin" / "request.txt"

    top_module = ""
    refined_text = ""
    if user_spec_path.exists():
        try:
            user_spec = json.loads(user_spec_path.read_text(encoding="utf-8", errors="replace"))
            top_module = str(user_spec.get("top_module") or "")
            refined_items = user_spec.get("refined_requirements") or []
            if isinstance(refined_items, list):
                refined_text = "\n".join(str(item) for item in refined_items)
        except json.JSONDecodeError:
            pass

    raw_text = origin_path.read_text(encoding="utf-8", errors="replace") if origin_path.exists() else ""
    artifacts, summary_text, progress_value, rows, rtl_text, spec_text, verify_text, mermaid_text, mermaid_html, graph_payload = inspect_unfinished_task(task_id)
    retry_note = f"Loaded {task_id} into the request form. Click Run Workflow to retry as a new task."
    return top_module, raw_text, refined_text, artifacts, retry_note + "\n" + summary_text, progress_value, rows, rtl_text, spec_text, verify_text, mermaid_text, mermaid_html, graph_payload


def retry_unfinished_task(
    task_id: Optional[str],
    parser_url: str,
    max_iterations: int,
    llm_enabled: bool,
    llm_base_url: str,
    llm_model: str,
    llm_api_key: str,
    llm_profile: str,
    llm_reasoning_effort: str,
):
    if not task_id:
        yield ("No unfinished task selected", 0, _initial_status_rows(), [], "", "", "", "", _render_mermaid_svg(""), {}, {})
        return

    top_module, raw_text, refined_text, *_ = load_task_for_retry(task_id)
    if not top_module or not raw_text:
        yield (f"Cannot retry {task_id}: missing top_module or original request", 0, _initial_status_rows(), [], "", "", "", "", _render_mermaid_svg(""), {}, {})
        return

    for result in run_workflow(
        parser_url=parser_url,
        top_module=top_module,
        raw_input_text=raw_text,
        refined_requirements_text=refined_text,
        max_iterations=max_iterations,
        llm_enabled=llm_enabled,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_profile=llm_profile,
        llm_reasoning_effort=llm_reasoning_effort,
    ):
        yield result


with gr.Blocks(title="ICU-MUJICA Control Panel") as demo:
    gr.Markdown("# ICU-MUJICA Control Panel")

    with gr.Row():
        with gr.Column(scale=5):
            parser_url = gr.Textbox(label="Parser URL", value=DEFAULT_PARSER_URL)
            top_module = gr.Textbox(label="Top module", value="gradio_done_logic")
            raw_input_text = gr.Textbox(
                label="Raw request",
                value="Generate a simple sequential done logic module with clock, active-low reset, and done output.",
                lines=6,
            )
            refined_requirements = gr.Textbox(label="Refined requirements", lines=4)
            max_iterations = gr.Slider(label="Max iterations", minimum=1, maximum=10, step=1, value=2)

            with gr.Accordion("LLM runtime", open=False):
                llm_enabled = gr.Checkbox(label="Enable LLM", value=False)
                llm_base_url = gr.Textbox(label="Base URL")
                llm_model = gr.Textbox(label="Model")
                llm_api_key = gr.Textbox(label="API key", type="password")
                llm_profile = gr.Textbox(label="Profile", value="default")
                llm_reasoning_effort = gr.Textbox(label="Reasoning effort", value="high")

            with gr.Row():
                health_button = gr.Button("Check Parser")
                run_button = gr.Button("Run Workflow", variant="primary")
                refresh_button = gr.Button("Refresh Latest Output")

            with gr.Accordion("Unfinished tasks", open=True):
                unfinished_task_select = gr.Dropdown(label="Task", choices=_task_choices(), value=(_task_choices()[0] if _task_choices() else None))
                with gr.Row():
                    unfinished_refresh_button = gr.Button("Refresh Tasks")
                    unfinished_inspect_button = gr.Button("Inspect Task")
                    unfinished_retry_button = gr.Button("Load For Retry")
                    unfinished_run_retry_button = gr.Button("Retry Task", variant="primary")
                    unfinished_delete_button = gr.Button("Delete Task", variant="stop")
                unfinished_table = gr.Dataframe(
                    headers=["Task", "Stage", "SpecReg", "RTL", "VerifyRpt", "Updated At"],
                    datatype=["str", "str", "str", "str", "str", "str"],
                    value=_unfinished_task_rows(),
                    interactive=False,
                )

        with gr.Column(scale=7):
            summary = gr.Textbox(label="Run summary", lines=7)
            progress = gr.Slider(label="Progress", minimum=0, maximum=100, value=0, interactive=False)
            status_table = gr.Dataframe(
                headers=["Agent", "Status", "Progress", "Node", "Iteration", "Detail", "Created At"],
                datatype=["str", "str", "number", "str", "str", "str", "str"],
                value=_initial_status_rows(),
                interactive=False,
            )

    with gr.Tabs():
        with gr.Tab("Artifacts"):
            artifact_table = gr.Dataframe(
                headers=["Path", "Size Bytes"],
                datatype=["str", "str"],
                value=[],
                interactive=False,
            )
        with gr.Tab("RTL"):
            rtl_preview = gr.Textbox(label="RTL preview", lines=24)
        with gr.Tab("SpecReg"):
            spec_preview = gr.Code(label="SpecReg preview", language="json", lines=24)
        with gr.Tab("VerifyRpt"):
            verify_preview = gr.Code(label="Verify report preview", language="json", lines=24)
        with gr.Tab("Hardware Graph"):
            mermaid_svg = gr.HTML(label="Graph render", value=_render_mermaid_svg(""))
            mermaid_preview = gr.Code(label="Mermaid graph", language="markdown", lines=24)
            graph_preview = gr.JSON(label="Hardware graph JSON")
        with gr.Tab("Raw response"):
            raw_response = gr.JSON(label="Parser response")

    health_button.click(check_parser, inputs=[parser_url], outputs=[summary, raw_response])
    run_button.click(
        run_workflow,
        inputs=[
            parser_url,
            top_module,
            raw_input_text,
            refined_requirements,
            max_iterations,
            llm_enabled,
            llm_base_url,
            llm_model,
            llm_api_key,
            llm_profile,
            llm_reasoning_effort,
        ],
        outputs=[summary, progress, status_table, artifact_table, rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_preview, raw_response],
    )
    refresh_button.click(
        refresh_latest_output,
        inputs=[],
        outputs=[artifact_table, summary, progress, status_table, rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_preview],
    )
    unfinished_refresh_button.click(
        refresh_unfinished_tasks,
        inputs=[],
        outputs=[unfinished_table, unfinished_task_select],
    )
    unfinished_inspect_button.click(
        inspect_unfinished_task,
        inputs=[unfinished_task_select],
        outputs=[artifact_table, summary, progress, status_table, rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_preview],
    )
    unfinished_retry_button.click(
        load_task_for_retry,
        inputs=[unfinished_task_select],
        outputs=[top_module, raw_input_text, refined_requirements, artifact_table, summary, progress, status_table, rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_preview],
    )
    unfinished_run_retry_button.click(
        retry_unfinished_task,
        inputs=[
            unfinished_task_select,
            parser_url,
            max_iterations,
            llm_enabled,
            llm_base_url,
            llm_model,
            llm_api_key,
            llm_profile,
            llm_reasoning_effort,
        ],
        outputs=[summary, progress, status_table, artifact_table, rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_preview, raw_response],
    )
    unfinished_delete_button.click(
        delete_unfinished_task,
        inputs=[unfinished_task_select],
        outputs=[unfinished_table, unfinished_task_select, summary, artifact_table, progress, status_table, rtl_preview, spec_preview, verify_preview, mermaid_preview, mermaid_svg, graph_preview],
    )


if __name__ == "__main__":
    demo.queue().launch(server_name="127.0.0.1", server_port=7860)