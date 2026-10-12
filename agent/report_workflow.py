"""Request-local LangGraph workflow for asset health reports."""

import ast
import re
from typing import Callable, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from observability.tracing import record, span
from utils.prompt_loader import load_report_prompts


_EMPLOYEE_ID = re.compile(r"\bEMP\d{4}\b", re.IGNORECASE)
_MONTH = re.compile(r"(?<!\d)(20\d{2})\s*(?:-|/|\.|年)\s*(0?[1-9]|1[0-2])\s*(?:月)?(?!\d)")
_MONTH_CANDIDATE = re.compile(r"(?<!\d)20\d{2}\s*(?:-|/|\.|年)\s*\d{1,2}(?:月)?(?!\d)")
_FOLLOWUP = ("刚才", "之前", "上次", "这份", "那份", "同样", "再生成", "重新生成", "继续")


def _written_month(message: str) -> str | None:
    match = _MONTH.search(message)
    return f"{match.group(1)}-{int(match.group(2)):02d}" if match else None


def _previous_month(month: str) -> str:
    year, number = map(int, month.split("-"))
    return f"{year - 1}-12" if number == 1 else f"{year}-{number - 1:02d}"


def _prior_user_text(history: list[dict[str, str]]) -> list[str]:
    return [item.get("content", "") for item in reversed(history) if item.get("role") == "user"]


def is_report_request(message: str) -> bool:
    """Route explicit asset-report intent while leaving ordinary IT questions alone."""
    text = message.lower()
    if any(phrase in text for phrase in ("怎么写", "如何写", "什么是")):
        return False
    if "模板" in text and not any(phrase in text for phrase in ("生成", "做一份", "写一份")):
        return False
    if "健康报告" in text and any(phrase in text for phrase in ("生成", "做", "写", "查询", "查看")):
        return True
    asset_topic = any(word in text for word in ("设备", "资产", "电脑", "维保"))
    if asset_topic and any(word in text for word in ("报告", "健康度", "健康分析")):
        return True
    return "维保" in text and "安全评分" in text and any(word in text for word in ("分析", "汇总"))


def is_report_followup(message: str, history: list[dict[str, str]] | None) -> bool:
    """Keep elliptical report follow-ups on the report workflow."""
    return ("报告" in message and any(cue in message for cue in _FOLLOWUP)
            and any(is_report_request(previous) for previous in _prior_user_text(history or [])))


class ReportState(TypedDict, total=False):
    message: str
    history: list[dict[str, str]]
    employee_id: str
    demo_employee: bool
    month: str
    default_month: bool
    asset_record: str
    status: dict[str, str]
    answer: str
    report_context: bool
    report_generated: bool
    input_tokens: int
    output_tokens: int


def _demo_employee_id() -> str:
    from agent.tools.agent_tools import get_employee_id

    return get_employee_id.invoke({})


def _current_month() -> str:
    from agent.tools.agent_tools import get_current_month

    return get_current_month.invoke({})


def _asset_record(employee_id: str, month: str) -> str:
    from agent.tools.agent_tools import query_asset_record

    return query_asset_record.invoke({"employee_id": employee_id, "month": month})


class ReportWorkflow:
    def __init__(self, *, employee_id_provider: Callable[[], str] = _demo_employee_id,
                 month_provider: Callable[[], str] = _current_month,
                 asset_lookup: Callable[[str, str], str] = _asset_record,
                 report_model=None):
        self.employee_id_provider = employee_id_provider
        self.month_provider = month_provider
        self.asset_lookup = asset_lookup
        self.report_model = report_model
        graph = StateGraph(ReportState)
        graph.add_node("resolve_identity", self._resolve_identity)
        graph.add_node("resolve_month", self._resolve_month)
        graph.add_node("lookup_asset", self._lookup_asset)
        graph.add_node("collect_status", self._collect_status)
        graph.add_node("generate_report", self._generate_report)
        graph.add_node("missing_record", self._missing_record)
        graph.add_node("reset_state", self._reset_state)
        graph.add_edge(START, "resolve_identity")
        graph.add_edge("resolve_identity", "resolve_month")
        graph.add_edge("resolve_month", "lookup_asset")
        graph.add_conditional_edges("lookup_asset", lambda state: "collect_status" if state.get("asset_record") else "missing_record")
        graph.add_edge("collect_status", "generate_report")
        graph.add_edge("generate_report", "reset_state")
        graph.add_edge("missing_record", "reset_state")
        graph.add_edge("reset_state", END)
        self.graph = graph.compile()

    def _resolve_identity(self, state: ReportState) -> ReportState:
        with span("report.resolve_identity"):
            match = _EMPLOYEE_ID.search(state["message"])
            if not match and any(cue in state["message"] for cue in _FOLLOWUP):
                for previous in _prior_user_text(state.get("history", [])):
                    match = _EMPLOYEE_ID.search(previous)
                    if match:
                        break
            return {"employee_id": match.group().upper() if match else self.employee_id_provider(),
                    "demo_employee": match is None, "report_context": True}

    def _resolve_month(self, state: ReportState) -> ReportState:
        with span("report.resolve_month"):
            message = state["message"]
            month = _written_month(message)
            if not month and _MONTH_CANDIDATE.search(message):
                raise ValueError("月份格式无效，请使用 YYYY-MM 且月份在 01 到 12 之间")
            default_month = False
            if not month and "上个月" in message:
                month = _previous_month(self.month_provider())
            if not month and not any(term in message for term in ("本月", "这个月", "当前月份")):
                if any(cue in message for cue in _FOLLOWUP):
                    for previous in _prior_user_text(state.get("history", [])):
                        month = _written_month(previous)
                        if month:
                            break
            if not month:
                month = self.month_provider()
                default_month = True
            return {"month": month, "default_month": default_month}

    def _lookup_asset(self, state: ReportState) -> ReportState:
        with span("report.lookup_asset"):
            result = self.asset_lookup(state["employee_id"], state["month"])
            record("report.asset_found", status="ok" if result else "missing")
            return {"asset_record": result}

    def _collect_status(self, state: ReportState) -> ReportState:
        with span("report.collect_status"):
            record_data = ast.literal_eval(state["asset_record"])
            if not isinstance(record_data, dict):
                raise ValueError("Asset record has an invalid format")
            required = ("设备配置", "运行状态", "维保记录", "安全评分")
            if not all(isinstance(record_data.get(key), str) for key in required):
                raise ValueError("Asset record is incomplete")
            return {"status": {key: record_data[key] for key in required}}

    def _generate_report(self, state: ReportState) -> ReportState:
        with span("report.generate"):
            if self.report_model is None:
                from model.factory import chat_model

                model = chat_model
            else:
                model = self.report_model
            label = "演示员工" if state["demo_employee"] else "员工"
            status = state["status"]
            details = (f"{label}：{state['employee_id']}\n月份：{state['month']}\n"
                       f"设备配置：{status['设备配置']}\n运行状态：{status['运行状态']}\n"
                       f"维保记录：{status['维保记录']}\n安全评分：{status['安全评分']}")
            messages = [SystemMessage(content=load_report_prompts()), HumanMessage(content=details)]
            writer = get_stream_writer()
            pieces = []
            if state["demo_employee"]:
                disclosure = (f"演示数据：员工号 {state['employee_id']} 由系统随机选取，"
                              "未核验请求者身份。\n\n")
                pieces.append(disclosure)
                writer({"type": "report_delta", "text": disclosure})
            usage = None
            for chunk in model.stream(messages):
                chunk_usage = getattr(chunk, "usage_metadata", None)
                if chunk_usage:
                    usage = chunk_usage
                content = getattr(chunk, "content", None)
                if isinstance(content, str) and content:
                    pieces.append(content)
                    writer({"type": "report_delta", "text": content})
            if usage:
                record("report.model.usage", input_tokens=usage.get("input_tokens", 0),
                       output_tokens=usage.get("output_tokens", 0))
            answer = "".join(pieces).strip()
            if not answer:
                raise ValueError("Report model returned an empty answer")
            return {"answer": answer, "report_generated": True,
                    "input_tokens": usage.get("input_tokens", 0) if usage else 0,
                    "output_tokens": usage.get("output_tokens", 0) if usage else 0}

    def _missing_record(self, state: ReportState) -> ReportState:
        with span("report.missing_record"):
            label = "演示员工" if state["demo_employee"] else "员工"
            answer = (f"未找到{label} {state['employee_id']} 在 {state['month']} 的设备资产记录，"
                      "因此无法生成有依据的健康报告。请提供有记录的员工号和月份。")
            get_stream_writer()({"type": "report_delta", "text": answer})
            return {"answer": answer, "report_generated": False}

    def _reset_state(self, state: ReportState) -> ReportState:
        record("report.reset")
        return {"report_context": False, "employee_id": "", "month": "",
                "asset_record": "", "status": {}, "history": []}

    def stream(self, message: str, history: list[dict[str, str]] | None = None):
        try:
            for mode, event in self.graph.stream({"message": message, "history": history or []},
                                                 stream_mode=["custom", "updates"]):
                if mode == "custom" and event.get("type") == "report_delta":
                    yield event["text"]
        finally:
            # Graph state is request-local; this records reset on interruption too.
            record("report.scope_closed")
