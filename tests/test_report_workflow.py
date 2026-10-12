"""The health report is a bounded stateful workflow, not an open tool loop."""

from langchain_core.messages import AIMessageChunk
import json
import pytest
from tests.test_sessions_api import session_api  # noqa: F401 - shared API fixture


def test_report_intent_routes_only_asset_health_requests():
    from agent.report_workflow import is_report_request

    assert is_report_request("生成我的本月设备健康报告")
    assert is_report_request("生成健康报告")
    assert is_report_request("查一下我这个月的资产健康度")
    assert is_report_request("请分析 EMP1004 在 2025-12 的维保与安全评分")
    assert not is_report_request("Redis 连接失败怎么排查？")
    assert not is_report_request("查看当前 CPU 使用率")
    assert not is_report_request("怎么写设备健康报告模板？")


def test_labeled_health_report_cases_enter_the_workflow():
    from pathlib import Path
    from evaluation.dataset import load_cases
    from agent.report_workflow import is_report_request

    cases = load_cases(Path(__file__).with_name("eval_dataset.json"))
    assert all(is_report_request(case["question"]) for case in cases
               if case["category"] == "health_report")


def test_report_graph_collects_record_streams_answer_and_resets_context():
    from agent.report_workflow import ReportWorkflow

    calls = []

    class Model:
        def stream(self, messages):
            calls.append(("generate", messages[1].content))
            yield AIMessageChunk(content="# IT设备资产健康度报告与运维建议\n")
            yield AIMessageChunk(content="安全评分 95 分。")

    def lookup(employee_id, month):
        calls.append(("lookup", employee_id, month))
        return str({"设备配置": "ThinkPad", "运行状态": "CPU 23%", "维保记录": "已更新补丁", "安全评分": "95分"})

    workflow = ReportWorkflow(asset_lookup=lookup, report_model=Model(),
                              employee_id_provider=lambda: "EMP1009", month_provider=lambda: "2026-10")
    chunks = list(workflow.stream("生成 EMP1001 在 2025-06 的设备报告"))
    assert chunks == ["# IT设备资产健康度报告与运维建议\n", "安全评分 95 分。"]
    assert calls[0] == ("lookup", "EMP1001", "2025-06")
    assert "CPU 23%" in calls[1][1]
    state = workflow.graph.invoke({"message": "生成 EMP1001 在 2025-06 的设备报告"})
    assert state["report_context"] is False
    assert state["status"] == {}
    assert state["asset_record"] == ""
    assert state["employee_id"] == ""
    assert state["month"] == ""


def test_missing_record_never_calls_model_and_explains_gap():
    from agent.report_workflow import ReportWorkflow

    class Model:
        def stream(self, messages):
            raise AssertionError("model must not run without a record")

    workflow = ReportWorkflow(asset_lookup=lambda employee_id, month: "", report_model=Model(),
                              employee_id_provider=lambda: "EMP1001", month_provider=lambda: "2026-10")
    answer = "".join(workflow.stream("生成我的本月设备健康报告"))
    assert "2026-10" in answer
    assert "演示员工" in answer
    assert "未找到" in answer
    state = workflow.graph.invoke({"message": "生成我的本月设备健康报告"})
    assert state["report_context"] is False


def test_explicit_employee_and_month_skip_demo_defaults():
    from agent.report_workflow import ReportWorkflow

    def unexpected():
        raise AssertionError("explicit value was ignored")

    workflow = ReportWorkflow(asset_lookup=lambda employee_id, month: "", report_model=None,
                              employee_id_provider=unexpected, month_provider=unexpected)
    answer = "".join(workflow.stream("给 emp1002 做 2025-09 的资产健康分析"))
    assert "EMP1002" in answer
    assert "2025-09" in answer
    assert "演示员工" not in answer


@pytest.mark.parametrize("written", ["2025年6月", "2025/06", "2025.6", "2025-6"])
def test_common_written_months_are_normalized(written):
    from agent.report_workflow import ReportWorkflow

    seen = []
    workflow = ReportWorkflow(asset_lookup=lambda employee_id, month: seen.append((employee_id, month)) or "",
                              employee_id_provider=lambda: "EMP1009", month_provider=lambda: "2026-10")
    list(workflow.stream(f"生成 EMP1001 在 {written} 的设备报告"))
    assert seen == [("EMP1001", "2025-06")]


def test_previous_month_handles_year_boundary():
    from agent.report_workflow import ReportWorkflow

    seen = []
    workflow = ReportWorkflow(asset_lookup=lambda employee_id, month: seen.append(month) or "",
                              employee_id_provider=lambda: "EMP1009", month_provider=lambda: "2026-01")
    list(workflow.stream("生成 EMP1001 上个月的设备报告"))
    assert seen == ["2025-12"]


def test_invalid_written_month_is_not_replaced_with_current_month():
    from agent.report_workflow import ReportWorkflow

    def unexpected(employee_id, month):
        raise AssertionError("invalid month must not reach lookup")

    workflow = ReportWorkflow(asset_lookup=unexpected, month_provider=lambda: "2026-10")
    with pytest.raises(ValueError, match="月份"):
        list(workflow.stream("生成 EMP1001 在 2025年13月 的设备报告"))


def test_report_followup_uses_recent_user_context_and_explicit_month_override():
    from agent.report_workflow import ReportWorkflow

    seen = []
    workflow = ReportWorkflow(asset_lookup=lambda employee_id, month: seen.append((employee_id, month)) or "",
                              employee_id_provider=lambda: "EMP1009", month_provider=lambda: "2026-10")
    history = [{"role": "user", "content": "生成 EMP1001 在 2025-06 的设备健康报告"},
               {"role": "assistant", "content": "报告完成"}]
    list(workflow.stream("给刚才那位员工生成 2025-09 的设备报告", history=history))
    assert seen == [("EMP1001", "2025-09")]


def test_report_followup_without_month_reuses_previous_month():
    from agent.report_workflow import ReportWorkflow

    seen = []
    workflow = ReportWorkflow(asset_lookup=lambda employee_id, month: seen.append((employee_id, month)) or "",
                              employee_id_provider=lambda: "EMP1009", month_provider=lambda: "2026-10")
    history = [{"role": "user", "content": "生成 EMP1001 在 2025-06 的设备健康报告"}]
    list(workflow.stream("再生成这份设备报告", history=history))
    assert seen == [("EMP1001", "2025-06")]


def test_demo_report_always_starts_with_disclosure():
    from agent.report_workflow import ReportWorkflow

    class Model:
        def stream(self, messages):
            yield AIMessageChunk(content="设备正常")

    workflow = ReportWorkflow(asset_lookup=lambda employee_id, month: str({
        "设备配置": "ThinkPad", "运行状态": "正常", "维保记录": "已更新", "安全评分": "95分"}),
        report_model=Model(), employee_id_provider=lambda: "EMP1001", month_provider=lambda: "2025-06")
    answer = "".join(workflow.stream("生成我的设备健康报告"))
    assert answer.startswith("演示数据：")
    assert "未核验请求者身份" in answer
    assert answer.endswith("设备正常")


def test_react_agent_uses_report_workflow_without_calling_normal_graph():
    from agent.react_agent import ReactAgent

    class NormalGraph:
        def stream(self, *args, **kwargs):
            raise AssertionError("normal graph must not run")

    class Report:
        def stream(self, message, history=None):
            assert "报告" in message
            assert history == [{"role": "user", "content": "EMP1001"}]
            yield "报告正文"

    agent = object.__new__(ReactAgent)
    agent.agent = NormalGraph()
    agent.report_workflow = Report()
    assert list(agent.execute_stream("生成设备健康报告", history=[{"role": "user", "content": "EMP1001"}])) == ["报告正文"]


def test_report_followup_without_asset_keyword_stays_on_report_route():
    from agent.react_agent import ReactAgent

    class NormalGraph:
        def stream(self, *args, **kwargs):
            raise AssertionError("normal graph must not run")

    class Report:
        def stream(self, message, history=None):
            assert history[0]["content"] == "生成 EMP1001 在 2025-06 的设备健康报告"
            yield "报告正文"

    agent = object.__new__(ReactAgent)
    agent.agent = NormalGraph()
    agent.report_workflow = Report()
    history = [{"role": "user", "content": "生成 EMP1001 在 2025-06 的设备健康报告"}]
    assert list(agent.execute_stream("再生成这份报告", history=history)) == ["报告正文"]


def test_report_model_usage_is_recorded_without_report_content(monkeypatch, tmp_path):
    from agent.report_workflow import ReportWorkflow
    from observability.tracing import trace_scope

    trace_file = tmp_path / "report.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(trace_file))

    class Model:
        def stream(self, messages):
            yield AIMessageChunk(content="private report text", usage_metadata={
                "input_tokens": 12, "output_tokens": 7, "total_tokens": 19,
            })

    workflow = ReportWorkflow(asset_lookup=lambda employee_id, month: str({
        "设备配置": "ThinkPad", "运行状态": "CPU 23%", "维保记录": "已更新补丁", "安全评分": "95分"}),
        report_model=Model())
    with trace_scope("report-test"):
        assert "".join(workflow.stream("生成 EMP1001 在 2025-06 的设备报告")) == "private report text"
    rows = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    usage = next(row for row in rows if row["event"] == "report.model.usage")
    assert (usage["input_tokens"], usage["output_tokens"]) == (12, 7)
    assert "private report text" not in trace_file.read_text(encoding="utf-8")


def test_report_workflow_uses_real_local_asset_record_with_fake_model():
    from agent.report_workflow import ReportWorkflow

    seen = []

    class Model:
        def stream(self, messages):
            seen.append(messages[1].content)
            yield AIMessageChunk(content="台账报告")

    workflow = ReportWorkflow(report_model=Model())
    assert "".join(workflow.stream("生成 EMP1001 在 2025-06 的设备健康报告")) == "台账报告"
    assert "EMP1001" in seen[0]
    assert "2025-06" in seen[0]
    assert "安全评分" in seen[0]
    assert "".join(workflow.stream("生成 EMP1001 在 2026-10 的设备健康报告")).startswith("未找到")
    assert len(seen) == 1


def test_failed_report_does_not_affect_the_next_request():
    from agent.report_workflow import ReportWorkflow

    class FlakyModel:
        calls = 0

        def stream(self, messages):
            self.calls += 1
            if self.calls == 1:
                yield AIMessageChunk(content="partial")
                raise RuntimeError("model unavailable")
            yield AIMessageChunk(content="完整报告")

    workflow = ReportWorkflow(asset_lookup=lambda employee_id, month: str({
        "设备配置": "ThinkPad", "运行状态": "正常", "维保记录": "已更新", "安全评分": "95分"}),
        report_model=FlakyModel())
    with pytest.raises(RuntimeError, match="model unavailable"):
        list(workflow.stream("生成 EMP1001 在 2025-06 的设备报告"))
    assert "".join(workflow.stream("生成 EMP1002 在 2025-09 的设备报告")) == "完整报告"


def test_report_chunks_reach_sse_and_are_saved_only_after_completion(session_api):
    from agent.react_agent import ReactAgent
    from backend.api.chat import get_agent_service
    from backend.main import app
    from backend.services.agent_service import AgentService

    class Report:
        def stream(self, message, history=None):
            yield "# 报告\n"
            yield "设备正常"

    agent = object.__new__(ReactAgent)
    agent.report_workflow = Report()
    app.dependency_overrides[get_agent_service] = lambda: AgentService(lambda: agent)
    client, _, _ = session_api
    response = client.post("/api/chat/stream", json={"message": "生成设备健康报告"})
    assert response.status_code == 200
    assert 'event: delta\ndata: {"text": "# 报告\\n"}' in response.text
    assert 'event: done' in response.text
    sid = response.text.split('"session_id": "')[1].split('"')[0]
    detail = client.get(f"/api/sessions/{sid}").json()
    assert detail["messages"][-1]["content"] == "# 报告\n设备正常"
