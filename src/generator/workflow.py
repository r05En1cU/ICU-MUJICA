from __future__ import annotations

import operator
import json
import re
import time
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, TypedDict

import httpx
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from src.common.llm_safety import sanitize_llm_message, strip_visible_cot
from src.common.models import (
    ArtifactSourceStage,
    ClockResetDef,
    EndpointRef,
    GenNodeOutput,
    LlmRuntimeConfig,
    NodeType,
    PortDef,
    PortDirection,
    PortType,
    ResetType,
    RtlEdge,
    RtlNode,
    SpecReg,
    UserTaskSpec,
    VerifyRpt,
    WorkTaskPayload,
)


PROMPT_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).with_name("prompts"))),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render_template(template_name: str, **context: Any) -> str:
    return PROMPT_ENV.get_template(template_name).render(**context).strip()


class GenWorkflowState(TypedDict):
    """
    Generator 内部 LangGraph 状态。

    说明：
    - task: Parser 下发的轻量任务载荷
    - iteration: 当前生成轮次
    - messages: 预留给后续 LLM 的多轮上下文
    - user_task_spec: 从文件中读取的用户结构化需求
    - verify_rpt: 若为重试轮次，则尝试加载上一轮验证报告
    - previous_spec_reg: 若为重试轮次，则尝试加载上一轮 SpecReg
    - spec_reg: 本轮生成的结构化设计契约
    - rtl_code: 本轮生成的 RTL 代码，兼容单文件路径
    - rtl_files: 本轮生成的 RTL 文件映射，key 为文件名，value 为 Verilog 代码
    - gen_output: 最终输出载荷
    """
    task: WorkTaskPayload
    iteration: int
    messages: Annotated[List[Any], operator.add]
    user_task_spec: Optional[UserTaskSpec]
    verify_rpt: Optional[VerifyRpt]
    previous_spec_reg: Optional[SpecReg]
    spec_reg: Optional[SpecReg]
    rtl_code: Optional[str]
    rtl_files: Optional[Dict[str, str]]
    gen_output: Optional[GenNodeOutput]
    llm_config: Optional[LlmRuntimeConfig]
    llm_transcripts: Annotated[List[Dict[str, Any]], operator.add]


def _load_user_task_spec(task: WorkTaskPayload) -> UserTaskSpec:
    """
    从 Parser 提供的 spec_file_path 中加载 UserTaskSpec。
    """
    user_task_spec_path = Path(task.spec_file_path)
    if not user_task_spec_path.exists():
        raise FileNotFoundError(f"UserTaskSpec not found at {user_task_spec_path}")

    return UserTaskSpec.model_validate_json(user_task_spec_path.read_text(encoding="utf-8"))


def _load_previous_spec_reg(shared_task_dir: Path, previous_iteration: int) -> Optional[SpecReg]:
    """
    尝试加载上一轮 SpecReg。

    规则：
    - 路径约定为 shared_workspace/TASK_ID/specs/SpecReg_iter{n}.json
    - 若文件不存在，则返回 None
    """
    prev_spec_path = shared_task_dir / "specs" / f"SpecReg_iter{previous_iteration}.json"
    if not prev_spec_path.exists():
        return None

    return SpecReg.model_validate_json(prev_spec_path.read_text(encoding="utf-8"))


def _load_previous_verify_rpt(shared_task_dir: Path, previous_iteration: int) -> Optional[VerifyRpt]:
    """
    尝试加载上一轮 VerifyRpt。

    当前约定路径：
    - shared_workspace/TASK_ID/sim/VerifyRpt_iter{n}.json

    注意：
    - 该文件是否存在，取决于 Verify 服务以及 Parser 编排器是否按约定落盘。
    - 若文件缺失，Generator 应保持可运行，不直接失败。
    """
    verify_rpt_path = shared_task_dir / "sim" / f"VerifyRpt_iter{previous_iteration}.json"
    if not verify_rpt_path.exists():
        return None

    return VerifyRpt.model_validate_json(verify_rpt_path.read_text(encoding="utf-8"))


def _build_system_messages(
    task: WorkTaskPayload,
    user_task_spec: UserTaskSpec,
    previous_spec_reg: Optional[SpecReg],
    verify_rpt: Optional[VerifyRpt],
) -> List[Dict[str, str]]:
    """
    构造供后续 LLM 使用的对话上下文。

    当前即便尚未接入 LLM，也提前统一维护 messages 结构，
    便于后续直接替换 architect/coder 内部实现。
    """
    messages: List[Dict[str, str]] = []

    system_prompt = _render_template(
        "context_system.j2",
        task=task,
        refined_requirements_json=json.dumps(user_task_spec.refined_requirements, indent=2, ensure_ascii=False),
        design_rules_json=json.dumps(user_task_spec.design_rules, indent=2, ensure_ascii=False),
    )
    messages.append({"role": "system", "content": system_prompt})

    if previous_spec_reg is not None:
        messages.append(
            {
                "role": "system",
                "content": (
                    "Previous SpecReg from last iteration:\n"
                    f"{previous_spec_reg.model_dump_json(indent=2)}"
                ),
            }
        )

    if verify_rpt is not None:
        messages.append(
            {
                "role": "user",
                "content": (
                    "Previous verification failed. Here is the verification report:\n"
                    f"{verify_rpt.model_dump_json(indent=2)}"
                ),
            }
        )
    elif task.iteration > 0:
        messages.append(
            {
                "role": "user",
                "content": (
                    "Previous iteration failed, but verification report is missing. "
                    "Please re-evaluate the previous design and regenerate a safer implementation."
                ),
            }
        )

    return messages


def _derive_ports_from_task_spec(task: WorkTaskPayload, user_task_spec: UserTaskSpec) -> List[PortDef]:
    """
    依据当前 MVP 规则生成顶层端口列表。

    当前实现目标：
    - 先保证最小闭环可跑通
    - 默认生成一个简单时序模块接口
    - 后续可替换为真正的 LLM / 规则提取逻辑

    当前约定接口：
    - i_clk: 时钟
    - i_rst_n: 低有效异步复位
    - o_done: 输出完成信号
    """
    return [
        PortDef(
            name="i_clk",
            direction=PortDirection.INPUT,
            width="1",
            clock_domain="i_clk",
            is_clock=True,
            description="Primary clock input",
        ),
        PortDef(
            name="i_rst_n",
            direction=PortDirection.INPUT,
            width="1",
            clock_domain="i_clk",
            is_reset=True,
            description="Active-low asynchronous reset",
        ),
        PortDef(
            name="o_done",
            direction=PortDirection.OUTPUT,
            net_type=PortType.REG,
            width="1",
            clock_domain="i_clk",
            description="Done flag output",
        ),
    ]


def _derive_nodes(task: WorkTaskPayload, verify_rpt: Optional[VerifyRpt]) -> List[RtlNode]:
    """
    生成架构节点列表。

    当前实现：
    - 统一生成一个最小可运行的叶子时序节点
    - 若后续需要更复杂架构，可在此接入 LLM 或规则引擎
    """
    description = "Sequential leaf logic that drives o_done with reset-safe behavior"

    if verify_rpt is not None and verify_rpt.requires_code_rewrite():
        description += "; regenerated after code-level verification failure"
    elif verify_rpt is not None and verify_rpt.requires_arch_refactor():
        description += "; regenerated after architecture-level verification failure"

    return [
        RtlNode(
            node_id="seq_done_logic",
            node_type=NodeType.SEQUENTIAL,
            description=description,
        )
    ]


def _derive_edges() -> List[RtlEdge]:
    """
    生成最小图结构连线。

    注意：
    - 当前 models.py 中 RtlEdge.source/target 必须使用 EndpointRef，而不是字符串。
    """
    return [
        RtlEdge(
            source=EndpointRef(node_id="TOP", port_name="i_clk"),
            target=EndpointRef(node_id="seq_done_logic", port_name="clk"),
            signal_name="i_clk",
            width="1",
            description="Clock connection",
        ),
        RtlEdge(
            source=EndpointRef(node_id="TOP", port_name="i_rst_n"),
            target=EndpointRef(node_id="seq_done_logic", port_name="rst_n"),
            signal_name="i_rst_n",
            width="1",
            description="Reset connection",
        ),
        RtlEdge(
            source=EndpointRef(node_id="seq_done_logic", port_name="q"),
            target=EndpointRef(node_id="TOP", port_name="o_done"),
            signal_name="o_done",
            width="1",
            description="Done output connection",
        ),
    ]


def _has_multi_file_directive(user_task_spec: UserTaskSpec) -> bool:
    request_text = "\n".join(
        [
            *user_task_spec.refined_requirements,
            *user_task_spec.design_rules,
        ]
    ).lower()
    explicit_keywords = [
        "agvs4rtl_inject_multi_file",
        "multi-file",
        "rtl files",
        "rtl file",
        "multiple rtl files",
        "separate rtl files",
        "independent rtl files",
        "多个 rtl 文件",
        "多 rtl 文件",
        "多文件",
        "分文件",
        "分别落盘",
    ]
    return any(keyword in request_text for keyword in explicit_keywords)


def _build_multi_file_spec_reg(task: WorkTaskPayload, user_task_spec: UserTaskSpec) -> SpecReg:
    datapath_module = f"{task.top_module}_datapath"
    control_module = f"{task.top_module}_control"

    return SpecReg(
        task_id=task.task_id,
        iteration=task.iteration,
        intent=task.intent,
        top_module=task.top_module,
        source_stage=ArtifactSourceStage.ARCHITECT,
        module_description=f"Hierarchical multi-file SpecReg for {task.top_module}",
        verification_directives=[
            "Compile all generated RTL files together",
            "Check top-level port contract against SpecReg",
            "Check required child module definitions are present",
        ],
        functional_requirements=user_task_spec.refined_requirements,
        ports=[
            PortDef(
                name="i_clk",
                direction=PortDirection.INPUT,
                width="1",
                clock_domain="i_clk",
                is_clock=True,
                description="Primary clock input",
            ),
            PortDef(
                name="i_rst_n",
                direction=PortDirection.INPUT,
                width="1",
                clock_domain="i_clk",
                is_reset=True,
                description="Active-low asynchronous reset",
            ),
            PortDef(
                name="i_data",
                direction=PortDirection.INPUT,
                width="8",
                clock_domain="i_clk",
                description="Input data byte",
            ),
            PortDef(
                name="o_data",
                direction=PortDirection.OUTPUT,
                net_type=PortType.WIRE,
                width="8",
                clock_domain="i_clk",
                description="Registered datapath output",
            ),
            PortDef(
                name="o_valid",
                direction=PortDirection.OUTPUT,
                net_type=PortType.WIRE,
                width="1",
                clock_domain="i_clk",
                description="Output valid flag",
            ),
        ],
        clock_and_reset=[
            ClockResetDef(
                clock_name="i_clk",
                reset_name="i_rst_n",
                reset_type=ResetType.ASYNC_LOW,
            )
        ],
        nodes=[
            RtlNode(
                node_id="u_control",
                node_type=NodeType.MODULE,
                module_name=control_module,
                file_name=f"{control_module}.v",
                parent_node_id="TOP",
                description="Control submodule that raises valid after reset",
                implementation_hint="Generate a reset-safe sequential valid flag",
                is_rtl_file=True,
            ),
            RtlNode(
                node_id="u_datapath",
                node_type=NodeType.MODULE,
                module_name=datapath_module,
                file_name=f"{datapath_module}.v",
                parent_node_id="TOP",
                description="Datapath submodule that registers input data",
                implementation_hint="Generate an 8-bit reset-safe register datapath",
                is_rtl_file=True,
            ),
        ],
        edges=[
            RtlEdge(
                source=EndpointRef(node_id="TOP", port_name="i_data"),
                target=EndpointRef(node_id="u_datapath", port_name="i_data"),
                signal_name="i_data",
                width="8",
                description="Top input data to datapath",
            ),
            RtlEdge(
                source=EndpointRef(node_id="u_datapath", port_name="o_data"),
                target=EndpointRef(node_id="TOP", port_name="o_data"),
                signal_name="o_data",
                width="8",
                description="Datapath output to top output",
            ),
            RtlEdge(
                source=EndpointRef(node_id="u_control", port_name="o_valid"),
                target=EndpointRef(node_id="TOP", port_name="o_valid"),
                signal_name="o_valid",
                width="1",
                description="Control valid to top output",
            ),
        ],
    )


def _build_dummy_spec_reg(
    task: WorkTaskPayload,
    user_task_spec: UserTaskSpec,
    verify_rpt: Optional[VerifyRpt],
) -> SpecReg:
    """
    当前版本的 SpecReg 生成实现。

    说明：
    - 这是 Architect 节点的规则化/占位实现。
    - 目标不是最终智能架构推理，而是先产生严格符合当前模型约束的 SpecReg。
    - 后续接入 LLM 时，可直接替换此函数内部逻辑，但输出结构应保持一致。
    """
    if _has_multi_file_directive(user_task_spec):
        return _build_multi_file_spec_reg(task, user_task_spec)

    module_description = f"Automated SpecReg for {task.top_module}"

    if verify_rpt is not None:
        module_description += f" regenerated after {verify_rpt.verdict}"

    return SpecReg(
        task_id=task.task_id,
        iteration=task.iteration,
        intent=task.intent,
        top_module=task.top_module,
        source_stage=ArtifactSourceStage.ARCHITECT,
        module_description=module_description,
        verification_directives=[
            "Check reset behavior on i_rst_n",
            "Check that o_done deasserts during reset",
            "Check that o_done asserts after reset is released",
        ],
        functional_requirements=user_task_spec.refined_requirements,
        ports=_derive_ports_from_task_spec(task, user_task_spec),
        clock_and_reset=[
            ClockResetDef(
                clock_name="i_clk",
                reset_name="i_rst_n",
                reset_type=ResetType.ASYNC_LOW,
            )
        ],
        nodes=_derive_nodes(task, verify_rpt),
        edges=_derive_edges(),
    )


def _emit_verilog_from_spec(spec_reg: SpecReg) -> str:
    """
    基于当前 SpecReg 输出 Verilog RTL。

    当前实现：
    - 针对最小可运行模板输出一个简单时序模块
    - 后续可替换为模板引擎 / LLM / AST 生成器

    这里仍然坚持一个原则：
    - 代码生成应以 SpecReg 为唯一契约依据，而不是直接回看原始 prompt
    """
    top_module = spec_reg.top_module
    requirements_text = "\n".join(spec_reg.functional_requirements)

    if spec_reg.iteration == 0 and "AGVS4RTL_INJECT_FAIL_SEMANTIC_ONCE" in requirements_text:
        return (
            f"module {top_module}(\n"
            "    input wire i_clk,\n"
            "    input wire i_rst_n\n"
            ");\n"
            "\n"
            "always @(posedge i_clk or negedge i_rst_n) begin\n"
            "    if (!i_rst_n)\n"
            "        o_done <= 1'b0;\n"
            "    else\n"
            "        o_done <= 1'b1;\n"
            "end\n"
            "\n"
            "endmodule\n"
        )

    if spec_reg.iteration == 0 and "AGVS4RTL_INJECT_FAIL_COMPILE_ONCE" in requirements_text:
        return (
            f"module {top_module}(\n"
            "    input wire i_clk,\n"
            "    input wire i_rst_n,\n"
            "    output reg o_done\n"
            ");\n"
            "\n"
            "always @(posedge i_clk or negedge i_rst_n) begin\n"
            "    if (!i_rst_n) begin\n"
            "        o_done <= 1'b0;\n"
            "    else\n"
            "        o_done <= 1'b1;\n"
            "end\n"
            "\n"
            "endmodule\n"
        )

    if spec_reg.iteration == 0 and "AGVS4RTL_INJECT_FAIL_PORT_DIRECTION_ONCE" in requirements_text:
        return (
            f"module {top_module}(\n"
            "    input wire i_clk,\n"
            "    input wire i_rst_n,\n"
            "    input wire o_done\n"
            ");\n"
            "\n"
            "endmodule\n"
        )

    if spec_reg.iteration == 0 and "AGVS4RTL_INJECT_FAIL_PORT_WIDTH_ONCE" in requirements_text:
        return (
            f"module {top_module}(\n"
            "    input wire i_clk,\n"
            "    input wire i_rst_n,\n"
            "    output reg [1:0] o_done\n"
            ");\n"
            "\n"
            "always @(posedge i_clk or negedge i_rst_n) begin\n"
            "    if (!i_rst_n)\n"
            "        o_done <= 2'b00;\n"
            "    else\n"
            "        o_done <= 2'b01;\n"
            "end\n"
            "\n"
            "endmodule\n"
        )

    return (
        f"module {top_module}(\n"
        "    input wire i_clk,\n"
        "    input wire i_rst_n,\n"
        "    output reg o_done\n"
        ");\n"
        "\n"
        "always @(posedge i_clk or negedge i_rst_n) begin\n"
        "    if (!i_rst_n)\n"
        "        o_done <= 1'b0;\n"
        "    else\n"
        "        o_done <= 1'b1;\n"
        "end\n"
        "\n"
        "endmodule\n"
    )


def _mermaid_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not normalized or normalized[0].isdigit():
        normalized = f"n_{normalized}"
    return normalized


def _mermaid_label(value: str) -> str:
    return value.replace('"', "'").replace("\n", "<br/>")


def _spec_reg_to_hardware_graph(spec_reg: SpecReg) -> Dict[str, Any]:
    top_id = "TOP"
    graph_nodes: List[Dict[str, Any]] = [
        {
            "id": top_id,
            "kind": "top",
            "label": f"TOP: {spec_reg.top_module}",
            "module_name": spec_reg.top_module,
        }
    ]
    graph_edges: List[Dict[str, Any]] = []

    for port in spec_reg.ports:
        port_id = _mermaid_id(f"port_{port.name}")
        graph_nodes.append(
            {
                "id": port_id,
                "kind": "port",
                "name": port.name,
                "direction": port.direction.value,
                "width": port.width,
                "clock_domain": port.clock_domain,
                "is_clock": port.is_clock,
                "is_reset": port.is_reset,
                "label": f"{port.direction.value} {port.name}[{port.width}]",
            }
        )
        graph_edges.append(
            {
                "source": port_id if port.direction == PortDirection.INPUT else top_id,
                "target": top_id if port.direction == PortDirection.INPUT else port_id,
                "signal": port.name,
                "width": port.width,
                "kind": "top_port",
            }
        )

    for node in spec_reg.nodes:
        graph_nodes.append(
            {
                "id": _mermaid_id(node.node_id),
                "kind": node.node_type.value,
                "node_id": node.node_id,
                "module_name": node.module_name,
                "file_name": node.file_name,
                "parent_node_id": node.parent_node_id,
                "is_rtl_file": node.is_rtl_file,
                "label": node.module_name or node.node_id,
                "description": node.description,
            }
        )

    for edge in spec_reg.edges:
        graph_edges.append(
            {
                "source": top_id if edge.source.node_id == "TOP" else _mermaid_id(edge.source.node_id),
                "target": top_id if edge.target.node_id == "TOP" else _mermaid_id(edge.target.node_id),
                "signal": edge.signal_name,
                "width": edge.width,
                "source_port": edge.source.port_name,
                "target_port": edge.target.port_name,
                "kind": "rtl_edge",
                "description": edge.description,
            }
        )

    mermaid_lines = ["flowchart LR"]
    for node in graph_nodes:
        node_id = _mermaid_id(str(node["id"]))
        label = _mermaid_label(str(node.get("label") or node_id))
        if node.get("kind") == "port":
            mermaid_lines.append(f'    {node_id}(("{label}"))')
        else:
            mermaid_lines.append(f'    {node_id}["{label}"]')

    for edge in graph_edges:
        source = _mermaid_id(str(edge["source"]))
        target = _mermaid_id(str(edge["target"]))
        signal = _mermaid_label(f"{edge.get('signal', '')}[{edge.get('width', '1')}]")
        mermaid_lines.append(f'    {source} -->|"{signal}"| {target}')

    return {
        "task_id": spec_reg.task_id,
        "iteration": spec_reg.iteration,
        "top_module": spec_reg.top_module,
        "nodes": graph_nodes,
        "edges": graph_edges,
        "mermaid": "\n".join(mermaid_lines) + "\n",
    }


def _has_injection_directive(spec_reg: SpecReg) -> bool:
    requirements_text = "\n".join(spec_reg.functional_requirements)
    return "AGVS4RTL_INJECT_" in requirements_text


def _has_injection_in_user_task_spec(user_task_spec: UserTaskSpec) -> bool:
    request_text = "\n".join(
        [
            *user_task_spec.refined_requirements,
            *user_task_spec.design_rules,
        ]
    )
    return "AGVS4RTL_INJECT_" in request_text


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _port_contract_from_port(port: PortDef) -> Dict[str, str]:
    return {
        "name": port.name,
        "direction": port.direction.value,
        "net_type": port.net_type.value,
        "width": port.width,
        "declaration": port.verilog_declaration,
    }


def _build_port_contract(name: str, direction: PortDirection, net_type: PortType, width: str) -> Dict[str, str]:
    port = PortDef(name=name, direction=direction, net_type=net_type, width=width)
    return _port_contract_from_port(port)


def _top_port_contracts(spec_reg: SpecReg) -> List[Dict[str, str]]:
    return [_port_contract_from_port(port) for port in spec_reg.ports]


def _append_port_contract(
    contracts: List[Dict[str, str]],
    seen_names: set[str],
    name: str,
    direction: PortDirection,
    net_type: PortType,
    width: str,
) -> None:
    if name in seen_names:
        return
    contracts.append(_build_port_contract(name, direction, net_type, width))
    seen_names.add(name)


def _merge_port_direction(current: PortDirection, incoming: PortDirection) -> PortDirection:
    if current == incoming:
        return current
    return PortDirection.INOUT


def _merge_port_net_type(direction: PortDirection) -> PortType:
    if direction == PortDirection.OUTPUT:
        return PortType.REG
    return PortType.WIRE


def _child_port_contracts(spec_reg: SpecReg, node: RtlNode) -> List[Dict[str, str]]:
    port_info: Dict[str, Dict[str, Any]] = {}
    for edge in spec_reg.edges:
        if edge.target.node_id == node.node_id:
            existing = port_info.get(edge.target.port_name)
            direction = PortDirection.INPUT
            if existing is not None:
                direction = _merge_port_direction(existing["direction"], direction)
            port_info[edge.target.port_name] = {"direction": direction, "width": edge.width}
        if edge.source.node_id == node.node_id:
            existing = port_info.get(edge.source.port_name)
            direction = PortDirection.OUTPUT
            if existing is not None:
                direction = _merge_port_direction(existing["direction"], direction)
            port_info[edge.source.port_name] = {"direction": direction, "width": edge.width}

    return [
        _build_port_contract(
            name=port_name,
            direction=info["direction"],
            net_type=_merge_port_net_type(info["direction"]),
            width=info["width"],
        )
        for port_name, info in port_info.items()
    ]


def _file_port_contracts(spec_reg: SpecReg, file_plan: Dict[str, Any]) -> List[Dict[str, str]]:
    node = file_plan.get("node")
    if node is None:
        return _top_port_contracts(spec_reg)
    return _child_port_contracts(spec_reg, node)


def _module_header(module_name: str, port_contracts: List[Dict[str, str]]) -> str:
    if not port_contracts:
        return f"module {module_name} ();"

    lines = []
    for index, contract in enumerate(port_contracts):
        suffix = "," if index < len(port_contracts) - 1 else ""
        lines.append(f"    {contract['declaration']}{suffix}")
    return f"module {module_name} (\n" + "\n".join(lines) + "\n);"


def _verilog_range(width: str) -> str:
    width_text = str(width).strip()
    if width_text == "1":
        return ""
    if re.fullmatch(r"\d+", width_text):
        return f"[{int(width_text) - 1}:0] "
    if width_text.startswith("[") and width_text.endswith("]"):
        return f"{width_text} "
    return f"[{width_text}-1:0] "


def _signal_declaration(name: str, width: str) -> str:
    return f"wire {_verilog_range(width)}{name};".replace("wire  ", "wire ")


def _top_connection_signal(edge: RtlEdge) -> str:
    if edge.source.node_id == "TOP":
        return edge.source.port_name
    if edge.target.node_id == "TOP":
        return edge.target.port_name
    return edge.signal_name


def _elaborate_top_skeleton(spec_reg: SpecReg, planned_files: List[Dict[str, Any]]) -> str:
    module_header = _module_header(spec_reg.top_module, _top_port_contracts(spec_reg))
    child_plans = [plan for plan in planned_files if plan.get("node") is not None]
    if not child_plans:
        return module_header + "\n\nendmodule\n"

    internal_signals: Dict[str, str] = {}
    child_connections: Dict[str, Dict[str, str]] = {}
    for plan in child_plans:
        child_connections[str(plan["module_name"])] = {}

    node_to_module = {
        str(plan["node"].node_id): str(plan["module_name"])
        for plan in child_plans
        if plan.get("node") is not None
    }

    for edge in spec_reg.edges:
        signal_name = _top_connection_signal(edge)
        if edge.source.node_id != "TOP" and edge.target.node_id != "TOP":
            internal_signals.setdefault(signal_name, edge.width)

        if edge.source.node_id != "TOP" and edge.source.node_id in node_to_module:
            child_connections[node_to_module[edge.source.node_id]][edge.source.port_name] = signal_name
        if edge.target.node_id != "TOP" and edge.target.node_id in node_to_module:
            child_connections[node_to_module[edge.target.node_id]][edge.target.port_name] = signal_name

    lines = [module_header, ""]
    if internal_signals:
        lines.append("    // Graph-derived internal wires")
        for signal_name, width in internal_signals.items():
            lines.append(f"    {_signal_declaration(signal_name, width)}")
        lines.append("")

    for plan in child_plans:
        module_name = str(plan["module_name"])
        instance_name = f"u_{module_name}"
        port_contracts = _file_port_contracts(spec_reg, plan)
        connections = child_connections.get(module_name, {})
        lines.append(f"    {module_name} {instance_name} (")
        for index, contract in enumerate(port_contracts):
            port_name = contract["name"]
            signal_name = connections.get(port_name, port_name)
            suffix = "," if index < len(port_contracts) - 1 else ""
            lines.append(f"        .{port_name}({signal_name}){suffix}")
        lines.append("    );")
        lines.append("")

    lines.append("endmodule")
    return "\n".join(lines).rstrip() + "\n"


def _declaration_line_names(line: str) -> List[str]:
    stripped = line.strip()
    if not stripped.endswith(";"):
        return []
    if re.match(r"^(input|output|inout|wire|reg|logic)\b", stripped) is None:
        return []

    body = re.sub(r"//.*$", "", stripped[:-1])
    body = re.sub(r"\[[^\]]+\]", " ", body)
    body = re.sub(r"\b(input|output|inout|wire|reg|logic|signed|unsigned)\b", " ", body)
    body = re.sub(r"=\s*[^,]+", "", body)

    names = []
    for item in body.split(","):
        match = re.search(r"([A-Za-z_][A-Za-z0-9_$]*)\s*$", item.strip())
        if match:
            names.append(match.group(1))
    return names


def _strip_redundant_port_declarations(rtl_code: str, port_names: set[str]) -> str:
    lines = []
    for line in rtl_code.splitlines():
        declared_names = _declaration_line_names(line)
        if declared_names and set(declared_names).issubset(port_names):
            continue
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def _normalize_module_framework(
    rtl_code: str,
    module_name: str,
    port_contracts: List[Dict[str, str]],
) -> str:
    header = _module_header(module_name, port_contracts)
    pattern = rf"\bmodule\s+{re.escape(module_name)}\s*(?:#\s*\(.*?\)\s*)?\(.*?\)\s*;"
    normalized, replacement_count = re.subn(pattern, header, rtl_code, count=1, flags=re.DOTALL)
    if replacement_count != 1:
        raise ValueError(f"failed to normalize module header for {module_name}")
    return _strip_redundant_port_declarations(
        normalized,
        {contract["name"] for contract in port_contracts},
    )


def _extract_verilog_code(content: str) -> str:
    fence_match = re.search(r"```(?:verilog)?\s*(.*?)```", content, re.IGNORECASE | re.DOTALL)
    if fence_match is not None:
        content = fence_match.group(1)

    content = content.strip()
    module_match = re.search(
        r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\s*(?:#\s*\(|\()",
        content,
        re.DOTALL,
    )
    module_index = module_match.start() if module_match is not None else -1
    endmodule_index = content.rfind("endmodule")

    if module_index >= 0 and endmodule_index >= module_index:
        content = content[module_index:endmodule_index + len("endmodule")]

    if not content.startswith("module ") or "endmodule" not in content:
        raise ValueError("LLM response does not contain a complete Verilog module")

    return content.rstrip() + "\n"


def _extract_single_verilog_module(content: str, expected_module_name: str) -> str:
    rtl_code = _extract_verilog_code(content)
    module_names = re.findall(
        r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\s*(?:#\s*\(|\()",
        rtl_code,
        re.DOTALL,
    )
    if len(module_names) != 1:
        raise ValueError(f"LLM response must contain exactly one module for {expected_module_name}: {module_names}")
    if module_names[0] != expected_module_name:
        raise ValueError(f"LLM response module '{module_names[0]}' does not match expected '{expected_module_name}'")
    return rtl_code


def _normalize_rtl_file_name(file_name: str) -> str:
    normalized = Path(file_name).name.strip()
    if not normalized:
        raise ValueError("RTL file name cannot be empty")
    if normalized != file_name.strip():
        raise ValueError(f"RTL file name must not include directories: {file_name}")
    if not normalized.endswith(".v"):
        raise ValueError(f"RTL file name must end with .v: {file_name}")
    return normalized


def _planned_rtl_files(spec_reg: SpecReg) -> List[Dict[str, Any]]:
    planned_files: List[Dict[str, Any]] = [
        {
            "file_name": f"{spec_reg.top_module}.v",
            "module_name": spec_reg.top_module,
            "node": None,
            "role": "top",
        }
    ]

    seen_file_names = {planned_files[0]["file_name"]}
    seen_module_names = {spec_reg.top_module}
    for node in spec_reg.rtl_file_nodes():
        if not node.file_name:
            raise ValueError(f"RTL file node '{node.node_id}' is missing file_name")
        if not node.module_name:
            raise ValueError(f"RTL file node '{node.node_id}' is missing module_name")
        file_name = _normalize_rtl_file_name(node.file_name)
        if file_name == f"{spec_reg.top_module}.v" and node.module_name == spec_reg.top_module:
            continue
        if file_name in seen_file_names:
            raise ValueError(f"duplicate RTL file name in SpecReg: {file_name}")
        if node.module_name in seen_module_names:
            raise ValueError(f"duplicate RTL module name in SpecReg: {node.module_name}")
        seen_file_names.add(file_name)
        seen_module_names.add(node.module_name)
        planned_files.append(
            {
                "file_name": file_name,
                "module_name": node.module_name,
                "node": node,
                "role": "child",
            }
        )

    return planned_files


def _generated_file_context(rtl_files: Dict[str, str]) -> str:
    if not rtl_files:
        return "No RTL files have been generated yet."
    sections = []
    for file_name, rtl_code in rtl_files.items():
        sections.append(f"Generated file {file_name}:\n{rtl_code}")
    return "\n\n".join(sections)


def _extract_json_fragment(content: str) -> tuple[str, int]:
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", content, re.IGNORECASE | re.DOTALL)
    if fence_match is not None:
        fenced_content = fence_match.group(1)
        fenced_offset = fence_match.start(1)
        leading_trimmed = len(fenced_content) - len(fenced_content.lstrip())
        json_text = fenced_content.strip()
        base_line = content[:fenced_offset + leading_trimmed].count("\n") + 1
        return json_text, base_line

    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM architect response does not contain a JSON object")
    return content[start:end + 1], content[:start].count("\n") + 1


def _extract_json_object(content: str) -> Dict[str, Any]:
    json_text, _ = _extract_json_fragment(content)

    parsed = json.loads(json_text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM architect response JSON is not an object")
    return parsed


def _loc_to_path(location: tuple[Any, ...]) -> str:
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path or "<root>"


def _line_for_json_path(json_text: str, location: tuple[Any, ...], base_line: int) -> Optional[int]:
    if not location:
        return base_line

    search_start = 0
    previous_key = None
    for part in location:
        if isinstance(part, str):
            pattern = re.compile(rf'"{re.escape(part)}"\s*:')
            match = pattern.search(json_text, search_start)
            if match is None:
                break
            search_start = match.end()
            previous_key = part
            continue
        if isinstance(part, int) and previous_key is not None:
            cursor = search_start
            for _ in range(part + 1):
                match = re.search(r"\{", json_text[cursor:])
                if match is None:
                    break
                cursor += match.start() + 1
            else:
                search_start = cursor

    key_candidates = [part for part in reversed(location) if isinstance(part, str)]
    for key in key_candidates:
        pattern = re.compile(rf'"{re.escape(key)}"\s*:')
        match = pattern.search(json_text, search_start)
        if match is not None:
            return base_line + json_text[:match.start()].count("\n")

    for key in key_candidates:
        pattern = re.compile(rf'"{re.escape(key)}"\s*:')
        match = pattern.search(json_text)
        if match is not None:
            return base_line + json_text[:match.start()].count("\n")
    return None


def _summarize_architect_error(exc: Exception, json_text: str, base_line: int, max_items: int = 8) -> Dict[str, Any]:
    if isinstance(exc, ValidationError):
        issues = []
        for error in exc.errors()[:max_items]:
            location = tuple(error.get("loc", ()))
            issues.append(
                {
                    "path": _loc_to_path(location),
                    "line": _line_for_json_path(json_text, location, base_line),
                    "type": error.get("type"),
                    "message": error.get("msg"),
                }
            )
        return {
            "kind": "pydantic_validation_error",
            "total_errors": len(exc.errors()),
            "shown_errors": len(issues),
            "issues": issues,
        }
    return {
        "kind": exc.__class__.__name__,
        "message": str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__,
        "line": base_line,
    }


def _format_architect_retry_feedback(
    error_summary: Dict[str, Any],
    repair_frame_path: str,
    repair_frame: Dict[str, Any],
) -> str:
    return _render_template(
        "architect_retry_user.j2",
        error_summary_json=json.dumps(error_summary, indent=2, ensure_ascii=False),
        repair_frame_path=repair_frame_path,
        repair_frame_json=json.dumps(repair_frame, indent=2, ensure_ascii=False),
    )


SPEC_REG_TOP_LEVEL_FIELDS = [
    "task_id",
    "iteration",
    "refactor_label",
    "intent",
    "top_module",
    "source_stage",
    "module_description",
    "parameters",
    "ports",
    "clock_and_reset",
    "protocols",
    "verification_directives",
    "functional_requirements",
    "corner_cases",
    "illegal_conditions",
    "latency_notes",
    "nodes",
    "edges",
]


def _top_level_error_fields(exc: Exception) -> set[str]:
    if not isinstance(exc, ValidationError):
        return set(SPEC_REG_TOP_LEVEL_FIELDS)
    fields = set()
    for error in exc.errors():
        location = tuple(error.get("loc", ()))
        if location and isinstance(location[0], str):
            fields.add(location[0])
    return fields or set(SPEC_REG_TOP_LEVEL_FIELDS)


def _empty_spec_reg_payload(task: WorkTaskPayload, user_task_spec: UserTaskSpec) -> Dict[str, Any]:
    return {
        "task_id": task.task_id,
        "iteration": task.iteration,
        "refactor_label": "NONE",
        "intent": task.intent.value,
        "top_module": task.top_module,
        "source_stage": ArtifactSourceStage.ARCHITECT.value,
        "module_description": "",
        "parameters": [],
        "ports": [],
        "clock_and_reset": [],
        "protocols": [],
        "verification_directives": [],
        "functional_requirements": list(user_task_spec.refined_requirements),
        "corner_cases": [],
        "illegal_conditions": [],
        "latency_notes": [],
        "nodes": [],
        "edges": [],
    }


def _target_field_shape(field_name: str) -> Any:
    shapes: Dict[str, Any] = {
        "module_description": "Describe the module behavior in one non-empty string.",
        "parameters": [
            {
                "name": "UPPER_CASE_PARAMETER",
                "default_value": "1",
                "description": "Parameter purpose.",
            }
        ],
        "ports": [
            {
                "name": "i_signal",
                "direction": "input",
                "net_type": "wire",
                "width": "1",
                "clock_domain": None,
                "is_clock": False,
                "is_reset": False,
                "description": "Port purpose.",
            }
        ],
        "clock_and_reset": [
            {
                "clock_name": "i_clk",
                "reset_name": "i_rst_n",
                "reset_type": "async_low",
            }
        ],
        "protocols": [
            {
                "protocol_type": "custom",
                "role": "endpoint",
                "port_mapping": {"logical_signal": "physical_port_name"},
                "description": "Protocol role and behavior.",
            }
        ],
        "verification_directives": ["One verification directive per string."],
        "functional_requirements": ["One functional requirement per string."],
        "corner_cases": ["One corner case per string."],
        "illegal_conditions": ["One illegal condition per string."],
        "latency_notes": ["One latency note per string."],
        "nodes": [
            {
                "node_id": "u_block",
                "node_type": "module",
                "module_name": "block_module",
                "file_name": "block_module.v",
                "parent_node_id": "TOP",
                "description": "Reusable RTL module node.",
                "implementation_hint": "How to implement this module.",
                "is_pure_comb_logic": False,
                "is_rtl_file": True,
            },
            {
                "node_id": "comb_block",
                "node_type": "combinational",
                "module_name": None,
                "file_name": None,
                "parent_node_id": None,
                "description": "Internal pure combinational logic.",
                "implementation_hint": None,
                "is_pure_comb_logic": True,
                "is_rtl_file": False,
            },
            {
                "node_id": "seq_block",
                "node_type": "sequential",
                "module_name": None,
                "file_name": None,
                "parent_node_id": None,
                "description": "Internal stateful logic.",
                "implementation_hint": None,
                "is_pure_comb_logic": False,
                "is_rtl_file": False,
            },
        ],
        "edges": [
            {
                "source": {"node_id": "TOP", "port_name": "i_signal"},
                "target": {"node_id": "u_block", "port_name": "i_signal"},
                "signal_name": "i_signal",
                "width": "1",
                "description": "Connection purpose.",
            }
        ],
    }
    return shapes.get(field_name, "Use the exact SpecReg schema value for this field.")


def _build_architect_repair_frame(
    task: WorkTaskPayload,
    user_task_spec: UserTaskSpec,
    spec_payload: Optional[Dict[str, Any]],
    exc: Exception,
    error_summary: Dict[str, Any],
) -> Dict[str, Any]:
    base_payload = _empty_spec_reg_payload(task, user_task_spec)
    if isinstance(spec_payload, dict):
        for field_name in SPEC_REG_TOP_LEVEL_FIELDS:
            if field_name in spec_payload:
                base_payload[field_name] = spec_payload[field_name]

    failed_fields = _top_level_error_fields(exc)
    accepted_fields = {
        field_name: base_payload[field_name]
        for field_name in SPEC_REG_TOP_LEVEL_FIELDS
        if field_name not in failed_fields and field_name in base_payload
    }
    fields_to_regenerate = {
        field_name: _target_field_shape(field_name)
        for field_name in SPEC_REG_TOP_LEVEL_FIELDS
        if field_name in failed_fields
    }
    output_frame = {
        field_name: fields_to_regenerate.get(field_name, accepted_fields.get(field_name, base_payload.get(field_name)))
        for field_name in SPEC_REG_TOP_LEVEL_FIELDS
    }

    return {
        "role": "architect_repair_frame",
        "instructions": [
            "Use accepted_spec_reg_fields as fixed context unless a correction is required for consistency.",
            "Regenerate every field listed in fields_to_regenerate using the target shape shown there.",
            "Return only the complete SpecReg JSON object, not this wrapper.",
        ],
        "failed_fields": sorted(failed_fields),
        "error_summary": error_summary,
        "accepted_spec_reg_fields": accepted_fields,
        "fields_to_regenerate": fields_to_regenerate,
        "complete_spec_reg_output_frame": output_frame,
    }


def _write_architect_repair_frame(task: WorkTaskPayload, attempt_number: int, repair_frame: Dict[str, Any]) -> str:
    llm_dir = Path(task.shared_task_dir) / "llm"
    llm_dir.mkdir(parents=True, exist_ok=True)
    repair_frame_path = llm_dir / f"ArchitectRepairFrame_iter{task.iteration}_attempt{attempt_number}.json"
    repair_frame_path.write_text(json.dumps(repair_frame, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(repair_frame_path)


def _write_architect_failure_artifact(
    task: WorkTaskPayload,
    exc: Exception,
    architect_attempts: List[Dict[str, Any]],
    architect_error_summary: Optional[Dict[str, Any]],
) -> str:
    errors_dir = Path(task.shared_task_dir) / "errors"
    errors_dir.mkdir(parents=True, exist_ok=True)
    failure_path = errors_dir / f"ArchitectFailure_iter{task.iteration}.json"
    failure_payload = {
        "task_id": task.task_id,
        "iteration": task.iteration,
        "top_module": task.top_module,
        "stage": "architect",
        "error": str(exc),
        "error_summary": architect_error_summary,
        "attempts": architect_attempts,
        "repair_frame_paths": [
            attempt.get("repair_frame_path")
            for attempt in architect_attempts
            if attempt.get("repair_frame_path")
        ],
    }
    failure_path.write_text(json.dumps(failure_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(failure_path)


class ArchitectSpecRegFailure(RuntimeError):
    def __init__(self, failure_artifact_path: str, original_error: Exception):
        super().__init__(
            "architect SpecReg generation failed after retries; "
            f"diagnostic artifact written to {failure_artifact_path}: {original_error}"
        )
        self.failure_artifact_path = failure_artifact_path
        self.original_error = original_error


def _ensure_text_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _normalize_architect_spec_payload(spec_payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(spec_payload)

    for field_name in [
        "verification_directives",
        "functional_requirements",
        "corner_cases",
        "illegal_conditions",
        "latency_notes",
    ]:
        normalized[field_name] = _ensure_text_list(normalized.get(field_name))

    normalized.setdefault("parameters", [])
    normalized.setdefault("ports", [])
    clock_and_reset = normalized.get("clock_and_reset") or []
    if isinstance(clock_and_reset, list):
        clock_name = None
        reset_name = None
        reset_type = None
        normalized_clock_reset = []
        for item in clock_and_reset:
            if not isinstance(item, dict):
                continue
            if {"clock_name", "reset_name", "reset_type"}.issubset(item.keys()):
                normalized_clock_reset.append(item)
                continue
            item_type = str(item.get("type", "")).lower()
            item_name = item.get("name")
            if item_type == "clock" and item_name:
                clock_name = item_name
            if "reset" in item_type and item_name:
                reset_name = item_name
                active_level = str(item.get("active_level", "")).lower()
                reset_type = "async_low" if active_level == "low" or item_name.endswith("_n") else "async_high"
        if normalized_clock_reset:
            normalized["clock_and_reset"] = normalized_clock_reset
        elif clock_name and reset_name:
            normalized["clock_and_reset"] = [
                {
                    "clock_name": clock_name,
                    "reset_name": reset_name,
                    "reset_type": reset_type or "async_low",
                }
            ]
        else:
            normalized["clock_and_reset"] = []
    else:
        normalized["clock_and_reset"] = []
    normalized.setdefault("protocols", [])

    normalized_nodes = []
    for node in normalized.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = node.get("node_id") or node.get("name") or node.get("id")
        if not node_id:
            continue
        node_type = node.get("node_type") or node.get("type") or "combinational"
        if str(node_type).lower() in {"rtl_module", "rtl-module", "rtl module", "submodule", "rtl_file", "rtl-file"}:
            node_type = "module"
        implementation_hint = node.get("implementation_hint")
        if isinstance(implementation_hint, str) and not implementation_hint.strip():
            implementation_hint = None
        normalized_nodes.append(
            {
                "node_id": node_id,
                "node_type": node_type,
                "module_name": node.get("module_name"),
                "file_name": node.get("file_name"),
                "parent_node_id": node.get("parent_node_id"),
                "description": node.get("description", ""),
                "implementation_hint": implementation_hint,
                "is_pure_comb_logic": node.get("is_pure_comb_logic", node_type == "combinational"),
                "is_rtl_file": node.get("is_rtl_file", False),
            }
        )
    normalized["nodes"] = normalized_nodes

    normalized_edges = []
    for edge in normalized.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(source, dict) or not isinstance(target, dict):
            continue
        if "node_id" not in source or "port_name" not in source:
            continue
        if "node_id" not in target or "port_name" not in target:
            continue
        signal_name = edge.get("signal_name")
        if not signal_name:
            continue
        normalized_edges.append(edge)
    normalized["edges"] = normalized_edges

    return normalized


def _call_openai_compatible_chat(
    llm_config: LlmRuntimeConfig,
    messages: List[Dict[str, str]],
) -> tuple[str, Dict[str, Any]]:
    if not llm_config.base_url:
        raise ValueError("LLM is enabled but base_url is missing")
    if llm_config.api_key is None:
        raise ValueError("LLM is enabled but api_key is missing")
    if not llm_config.model:
        raise ValueError("LLM is enabled but model is missing")

    payload = {
        "model": llm_config.model,
        "messages": messages,
        "temperature": 0.1,
        "stream": False,
    }
    if llm_config.reasoning_effort is not None:
        payload["reasoning_effort"] = llm_config.reasoning_effort
    headers = {
        "Authorization": f"Bearer {llm_config.api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }

    transport_errors = (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadError,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
    )
    max_transport_attempts = 3
    last_transport_error: Optional[Exception] = None
    for transport_attempt in range(max_transport_attempts):
        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(_chat_completions_url(llm_config.base_url), json=payload, headers=headers)
                response.raise_for_status()
            break
        except transport_errors as exc:
            last_transport_error = exc
            if transport_attempt == max_transport_attempts - 1:
                raise
            time.sleep(1.5 * (transport_attempt + 1))
    else:
        raise RuntimeError("LLM transport retry loop exited without a response") from last_transport_error

    response_payload = response.json()
    try:
        content = strip_visible_cot(response_payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("LLM response is not OpenAI chat-completions compatible") from exc

    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response content is empty")

    sanitized_choices = []
    for response_choice in response_payload.get("choices", []):
        if not isinstance(response_choice, dict):
            continue
        message = response_choice.get("message")
        if not isinstance(message, dict):
            continue
        sanitized_choices.append(
            {
                "index": response_choice.get("index"),
                "message": sanitize_llm_message(message),
                "finish_reason": response_choice.get("finish_reason"),
            }
        )

    return content, {
        "request": {
            "messages": messages,
            "temperature": payload["temperature"],
            "stream": payload["stream"],
            "reasoning_effort": payload.get("reasoning_effort"),
        },
        "response": {
            "id": response_payload.get("id"),
            "object": response_payload.get("object"),
            "created": response_payload.get("created"),
            "choices": sanitized_choices,
            "usage": response_payload.get("usage"),
        },
    }


def _emit_verilog_with_llm(
    spec_reg: SpecReg,
    user_task_spec: UserTaskSpec,
    verify_rpt: Optional[VerifyRpt],
    llm_config: LlmRuntimeConfig,
) -> tuple[str, Dict[str, Any]]:
    retry_context = ""
    if verify_rpt is not None:
        retry_context = "\nPrevious verification report:\n" + verify_rpt.model_dump_json(indent=2)

    port_contracts = _top_port_contracts(spec_reg)
    module_header = _module_header(spec_reg.top_module, port_contracts)

    messages = [
        {
            "role": "system",
            "content": _render_template("coder_system.j2", multi_file=False),
        },
        {
            "role": "user",
            "content": _render_template(
                "single_rtl_user.j2",
                module_name=spec_reg.top_module,
                module_header=module_header,
                port_contracts_json=json.dumps(port_contracts, indent=2, ensure_ascii=False),
                user_task_spec_json=user_task_spec.model_dump_json(indent=2),
                spec_reg_json=spec_reg.model_dump_json(indent=2),
                retry_context=retry_context,
            ),
        },
    ]

    content, transcript = _call_openai_compatible_chat(llm_config, messages)
    rtl_code = _normalize_module_framework(
        _extract_verilog_code(content),
        spec_reg.top_module,
        port_contracts,
    )
    transcript.update(
        {
            "stage": "coder",
            "profile": llm_config.profile,
            "module_header": module_header,
            "port_contracts": port_contracts,
            "extracted_rtl": rtl_code,
        }
    )
    return transcript["extracted_rtl"], transcript


def _emit_rtl_files_with_llm(
    spec_reg: SpecReg,
    user_task_spec: UserTaskSpec,
    verify_rpt: Optional[VerifyRpt],
    llm_config: LlmRuntimeConfig,
) -> tuple[Dict[str, str], List[Dict[str, Any]]]:
    retry_context = ""
    if verify_rpt is not None:
        retry_context = "\nPrevious verification report:\n" + verify_rpt.model_dump_json(indent=2)

    planned_files = _planned_rtl_files(spec_reg)
    top_file_name = f"{spec_reg.top_module}.v"
    top_skeleton = _elaborate_top_skeleton(spec_reg, planned_files)
    rtl_files: Dict[str, str] = {}
    transcripts: List[Dict[str, Any]] = []

    for index, file_plan in enumerate(planned_files):
        file_name = str(file_plan["file_name"])
        module_name = str(file_plan["module_name"])
        node = file_plan["node"]
        role = str(file_plan["role"])
        port_contracts = _file_port_contracts(spec_reg, file_plan)
        module_header = _module_header(module_name, port_contracts)

        if role == "top":
            rtl_files[file_name] = top_skeleton
            transcripts.append(
                {
                    "stage": "coder",
                    "profile": llm_config.profile,
                    "turn_index": index,
                    "file_name": file_name,
                    "module_name": module_name,
                    "role": role,
                    "module_header": module_header,
                    "port_contracts": port_contracts,
                    "graph_elaborated": True,
                    "extracted_rtl": top_skeleton,
                }
            )
            continue

        if node is None:
            node_context = (
                "Current file role: top-level RTL file. Generate only the top module. "
                "The top module should declare the SpecReg top-level ports, local wires, and child instantiations. "
                "Do not include child module definitions in this file."
            )
        else:
            node_context = (
                "Current file role: child RTL file. Generate only the child module for this RtlNode.\n"
                f"RtlNode:\n{node.model_dump_json(indent=2)}"
            )

        messages = [
            {
                "role": "system",
                "content": _render_template("coder_system.j2", multi_file=True),
            },
            {
                "role": "user",
                "content": _render_template(
                    "multi_rtl_user.j2",
                    file_index=index + 1,
                    file_count=len(planned_files),
                    file_name=file_name,
                    module_name=module_name,
                    module_header=module_header,
                    node_context=node_context,
                    role=role,
                    port_contracts_json=json.dumps(port_contracts, indent=2, ensure_ascii=False),
                    user_task_spec_json=user_task_spec.model_dump_json(indent=2),
                    spec_reg_json=spec_reg.model_dump_json(indent=2),
                    generated_file_context=_generated_file_context(rtl_files),
                    retry_context=retry_context,
                ),
            },
        ]

        content, transcript = _call_openai_compatible_chat(llm_config, messages)
        rtl_code = _normalize_module_framework(
            _extract_single_verilog_module(content, module_name),
            module_name,
            port_contracts,
        )
        rtl_files[file_name] = rtl_code
        transcript.update(
            {
                "stage": "coder",
                "profile": llm_config.profile,
                "turn_index": index,
                "file_name": file_name,
                "module_name": module_name,
                "role": role,
                "module_header": module_header,
                "port_contracts": port_contracts,
                "extracted_rtl": rtl_code,
            }
        )
        transcripts.append(transcript)

    if top_file_name not in rtl_files:
        rtl_files[top_file_name] = top_skeleton

    return rtl_files, transcripts


def _build_spec_reg_with_llm(
    task: WorkTaskPayload,
    user_task_spec: UserTaskSpec,
    previous_spec_reg: Optional[SpecReg],
    verify_rpt: Optional[VerifyRpt],
    llm_config: LlmRuntimeConfig,
) -> tuple[SpecReg, Dict[str, Any]]:
    previous_context = ""
    if previous_spec_reg is not None:
        previous_context += "\nPrevious SpecReg:\n" + previous_spec_reg.model_dump_json(indent=2)
    if verify_rpt is not None:
        previous_context += "\nPrevious VerifyRpt:\n" + verify_rpt.model_dump_json(indent=2)

    messages = [
        {
            "role": "system",
            "content": _render_template("architect_system.j2"),
        },
        {
            "role": "user",
            "content": _render_template(
                "architect_user.j2",
                task_json=task.model_dump_json(indent=2),
                user_task_spec_json=user_task_spec.model_dump_json(indent=2),
                previous_context=previous_context,
            ),
        },
    ]

    transcripts = []
    max_attempts = 3
    last_error: Optional[Exception] = None
    last_error_summary: Optional[Dict[str, Any]] = None

    for attempt_index in range(max_attempts):
        content, transcript = _call_openai_compatible_chat(llm_config, messages)
        json_text = ""
        json_base_line = 1
        spec_payload_for_repair: Optional[Dict[str, Any]] = None
        try:
            json_text, json_base_line = _extract_json_fragment(content)
            parsed_payload = json.loads(json_text)
            if not isinstance(parsed_payload, dict):
                raise ValueError("LLM architect response JSON is not an object")

            spec_payload = _normalize_architect_spec_payload(parsed_payload)
            spec_payload_for_repair = spec_payload
            spec_payload.update(
                {
                    "task_id": task.task_id,
                    "iteration": task.iteration,
                    "intent": task.intent.value,
                    "top_module": task.top_module,
                    "source_stage": ArtifactSourceStage.ARCHITECT.value,
                }
            )
            if not spec_payload.get("functional_requirements"):
                spec_payload["functional_requirements"] = user_task_spec.refined_requirements

            spec_reg = SpecReg.model_validate(spec_payload)
            transcript.update(
                {
                    "stage": "architect",
                    "profile": llm_config.profile,
                    "attempt": attempt_index + 1,
                    "parsed_spec_reg": spec_reg.model_dump(mode="json"),
                }
            )
            transcripts.append(transcript)
            return spec_reg, {"stage": "architect", "profile": llm_config.profile, "attempts": transcripts}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            last_error_summary = _summarize_architect_error(exc, json_text, json_base_line)
            repair_frame = _build_architect_repair_frame(
                task=task,
                user_task_spec=user_task_spec,
                spec_payload=spec_payload_for_repair,
                exc=exc,
                error_summary=last_error_summary,
            )
            repair_frame_path = _write_architect_repair_frame(task, attempt_index + 1, repair_frame)
            transcript.update(
                {
                    "stage": "architect",
                    "profile": llm_config.profile,
                    "attempt": attempt_index + 1,
                    "error_summary": last_error_summary,
                    "repair_frame_path": repair_frame_path,
                }
            )
            transcripts.append(transcript)
            if attempt_index == max_attempts - 1:
                break

            messages = [
                *messages,
                {"role": "assistant", "content": content},
                {"role": "system", "content": _render_template("architect_retry_system.j2")},
                {
                    "role": "user",
                    "content": _format_architect_retry_feedback(
                        last_error_summary,
                        repair_frame_path,
                        repair_frame,
                    ),
                },
            ]

    if last_error is None:
        raise ValueError("Architect LLM did not produce a validation attempt")
    if last_error_summary is not None:
        setattr(last_error, "architect_error_summary", last_error_summary)
        setattr(last_error, "architect_attempts", transcripts)
    raise last_error


def init_context_node(state: GenWorkflowState) -> Dict[str, Any]:
    """
    节点 1：上下文初始化。

    职责：
    1. 读取 UserTaskSpec。
    2. 若 iteration > 0，尝试读取上一轮 SpecReg。
    3. 若 iteration > 0，尝试读取上一轮 VerifyRpt。
    4. 构建统一 messages，上下文供后续 Architect/Coder 复用。
    """
    task = state["task"]
    shared_task_dir = Path(task.shared_task_dir)

    user_task_spec = _load_user_task_spec(task)

    previous_spec_reg = None
    verify_rpt = None

    if task.is_retry_iteration():
        previous_iteration = task.iteration - 1
        previous_spec_reg = _load_previous_spec_reg(shared_task_dir, previous_iteration)
        verify_rpt = _load_previous_verify_rpt(shared_task_dir, previous_iteration)

    messages = _build_system_messages(
        task=task,
        user_task_spec=user_task_spec,
        previous_spec_reg=previous_spec_reg,
        verify_rpt=verify_rpt,
    )

    return {
        "iteration": task.iteration,
        "messages": messages,
        "user_task_spec": user_task_spec,
        "verify_rpt": verify_rpt,
        "previous_spec_reg": previous_spec_reg,
    }


def architect_node(state: GenWorkflowState) -> Dict[str, Any]:
    """
    节点 2：架构师节点。

    当前职责：
    1. 基于 UserTaskSpec 生成结构化 SpecReg。
    2. 若是重试轮次，则参考 VerifyRpt 调整本轮描述与上下文语义。
    3. 输出严格满足当前 models.py 约束的 SpecReg。

    后续 LLM 接入点：
    - 可在本节点中用 state["messages"] 驱动模型生成 SpecReg JSON，
      再用 SpecReg.model_validate(...) 做强约束校验。
    """
    task = state["task"]
    user_task_spec = state.get("user_task_spec")
    verify_rpt = state.get("verify_rpt")
    previous_spec_reg = state.get("previous_spec_reg")
    llm_config = state.get("llm_config")

    if user_task_spec is None:
        raise ValueError("user_task_spec is missing")

    if llm_config is not None and llm_config.enabled and not _has_injection_in_user_task_spec(user_task_spec):
        try:
            spec_reg, llm_transcript = _build_spec_reg_with_llm(
                task=task,
                user_task_spec=user_task_spec,
                previous_spec_reg=previous_spec_reg,
                verify_rpt=verify_rpt,
                llm_config=llm_config,
            )
            return {"spec_reg": spec_reg, "llm_transcripts": [llm_transcript]}
        except Exception as exc:  # noqa: BLE001
            architect_attempts = getattr(exc, "architect_attempts", [])
            architect_error_summary = getattr(exc, "architect_error_summary", None)
            failure_artifact_path = _write_architect_failure_artifact(
                task=task,
                exc=exc,
                architect_attempts=architect_attempts,
                architect_error_summary=architect_error_summary,
            )
            raise ArchitectSpecRegFailure(failure_artifact_path, exc) from exc

    spec_reg = _build_dummy_spec_reg(
        task=task,
        user_task_spec=user_task_spec,
        verify_rpt=verify_rpt,
    )

    return {"spec_reg": spec_reg}


def coder_node(state: GenWorkflowState) -> Dict[str, Any]:
    """
    节点 3：程序员节点。

    当前职责：
    1. 仅依据 SpecReg 生成 RTL 代码或 RTL 文件集合。
    2. 不直接依赖原始 prompt，避免设计事实漂移。
    3. 输出最终 Verilog 字符串或文件名到 Verilog 字符串的映射。

    后续 LLM 接入点：
    - 可在本节点中将 SpecReg 序列化为上下文提示，让模型生成 RTL；
    - 再对生成结果做静态格式化与必要的语法保护。
    """
    spec_reg = state.get("spec_reg")
    user_task_spec = state.get("user_task_spec")
    verify_rpt = state.get("verify_rpt")
    llm_config = state.get("llm_config")
    if spec_reg is None:
        raise ValueError("spec_reg is missing")
    if user_task_spec is None:
        raise ValueError("user_task_spec is missing")

    if llm_config is not None and llm_config.enabled and not _has_injection_directive(spec_reg):
        if spec_reg.rtl_file_nodes():
            rtl_files, llm_transcripts = _emit_rtl_files_with_llm(
                spec_reg=spec_reg,
                user_task_spec=user_task_spec,
                verify_rpt=verify_rpt,
                llm_config=llm_config,
            )
            return {
                "rtl_code": rtl_files[f"{spec_reg.top_module}.v"],
                "rtl_files": rtl_files,
                "llm_transcripts": llm_transcripts,
            }

        rtl_code, llm_transcript = _emit_verilog_with_llm(
            spec_reg=spec_reg,
            user_task_spec=user_task_spec,
            verify_rpt=verify_rpt,
            llm_config=llm_config,
        )
        return {
            "rtl_code": rtl_code,
            "rtl_files": {f"{spec_reg.top_module}.v": rtl_code},
            "llm_transcripts": [llm_transcript],
        }

    rtl_code = _emit_verilog_from_spec(spec_reg)

    return {"rtl_code": rtl_code, "rtl_files": {f"{spec_reg.top_module}.v": rtl_code}}


def finalize_node(state: GenWorkflowState) -> Dict[str, Any]:
    """
    节点 4：落盘与输出节点。

    职责：
    1. 将 SpecReg 落盘到 shared_workspace/TASK_ID/specs。
    2. 将 RTL 落盘到 shared_workspace/TASK_ID/rtl。
    3. 组装并返回 GenNodeOutput。

    文件命名规则：
    - SpecReg: specs/SpecReg_iter{iteration}.json
    - RTL: rtl/{top_module}.v
    """
    task = state["task"]
    spec_reg = state.get("spec_reg")
    rtl_code = state.get("rtl_code")
    rtl_files = state.get("rtl_files")
    llm_transcripts = state.get("llm_transcripts", [])

    if spec_reg is None:
        raise ValueError("spec_reg is missing at finalize stage")
    if rtl_files is None:
        if rtl_code is None:
            raise ValueError("rtl_code is missing at finalize stage")
        rtl_files = {f"{task.top_module}.v": rtl_code}

    requirements_text = "\n".join(spec_reg.functional_requirements)
    shared_task_dir = Path(task.shared_task_dir)
    specs_dir = shared_task_dir / "specs"
    rtl_dir = shared_task_dir / "rtl"
    graphs_dir = shared_task_dir / "graphs"
    llm_dir = shared_task_dir / "llm"

    specs_dir.mkdir(parents=True, exist_ok=True)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    graphs_dir.mkdir(parents=True, exist_ok=True)

    spec_file_path = specs_dir / f"SpecReg_iter{task.iteration}.json"
    spec_file_path.write_text(spec_reg.model_dump_json(indent=2), encoding="utf-8")

    hardware_graph = _spec_reg_to_hardware_graph(spec_reg)
    hardware_graph_path = graphs_dir / f"HardwareGraph_iter{task.iteration}.json"
    hardware_graph_mermaid_path = graphs_dir / f"HardwareGraph_iter{task.iteration}.mmd"
    hardware_graph_path.write_text(json.dumps(hardware_graph, indent=2, ensure_ascii=False), encoding="utf-8")
    hardware_graph_mermaid_path.write_text(hardware_graph["mermaid"], encoding="utf-8")

    rtl_paths: List[str] = []
    for file_name, file_content in rtl_files.items():
        rtl_file_path = rtl_dir / _normalize_rtl_file_name(file_name)
        rtl_file_path.write_text(file_content, encoding="utf-8")
        rtl_paths.append(str(rtl_file_path))

    rtl_path = rtl_dir / f"{task.top_module}.v"
    if task.iteration == 0 and "AGVS4RTL_INJECT_INFRA_MISSING_RTL_ONCE" in requirements_text:
        rtl_path.unlink()

    if llm_transcripts:
        llm_dir.mkdir(parents=True, exist_ok=True)
        transcripts_by_stage: Dict[str, List[Dict[str, Any]]] = {}
        for transcript in llm_transcripts:
            stage = str(transcript.get("stage", "unknown"))
            transcripts_by_stage.setdefault(stage, []).append(transcript)

        stage_file_names = {
            "architect": "ArchitectChat",
            "coder": "CoderChat",
        }
        for stage, stage_transcripts in transcripts_by_stage.items():
            trace_name = stage_file_names.get(stage, f"{stage.title()}Chat")
            llm_trace_path = llm_dir / f"{trace_name}_iter{task.iteration}.json"
            llm_trace_path.write_text(
                json.dumps(
                    {
                        "task_id": task.task_id,
                        "iteration": task.iteration,
                        "top_module": task.top_module,
                        "transcripts": stage_transcripts,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    verify_rpt = state.get("verify_rpt")
    summary = f"Generated SpecReg and RTL for {task.top_module} at iteration {task.iteration}"
    if verify_rpt is not None:
        summary += f" after previous verification verdict {verify_rpt.verdict}"

    gen_output = GenNodeOutput(
        spec_file_path=str(spec_file_path),
        rtl_path=str(rtl_path),
        rtl_paths=rtl_paths,
        top_rtl_path=str(rtl_path),
        hardware_graph_path=str(hardware_graph_path),
        hardware_graph_mermaid_path=str(hardware_graph_mermaid_path),
        summary=summary,
    )

    return {"gen_output": gen_output}


def build_gen_workflow_graph():
    """
    构建 Generator 内部状态机。

    当前执行路径：
    START
      -> init_context
      -> architect
      -> coder
      -> finalize
      -> END

    后续可扩展方向：
    - architect/coder 之间加入“是否还存在未细化 module 节点”的条件循环
    - 增加 static lint / 格式化节点
    - 增加中间产物自检节点
    """
    graph = StateGraph(GenWorkflowState)

    graph.add_node("init_context", init_context_node)
    graph.add_node("architect", architect_node)
    graph.add_node("coder", coder_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "init_context")
    graph.add_edge("init_context", "architect")
    graph.add_edge("architect", "coder")
    graph.add_edge("coder", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


def run_gen_workflow(payload: WorkTaskPayload, llm_config: Optional[LlmRuntimeConfig] = None) -> GenNodeOutput:
    """
    Generator 工作流统一入口。

    输入：
    - Parser 下发的 WorkTaskPayload

    输出：
    - GenNodeOutput（仅包含路径与摘要，不直接返回大文本代码）
    """
    app = build_gen_workflow_graph()

    initial_state: GenWorkflowState = {
        "task": payload,
        "iteration": payload.iteration,
        "messages": [],
        "user_task_spec": None,
        "verify_rpt": None,
        "previous_spec_reg": None,
        "spec_reg": None,
        "rtl_code": None,
        "rtl_files": None,
        "gen_output": None,
        "llm_config": llm_config,
        "llm_transcripts": [],
    }

    final_state = app.invoke(initial_state)

    gen_output = final_state.get("gen_output")
    if gen_output is None:
        raise RuntimeError("generation workflow failed to produce GenNodeOutput")

    return gen_output