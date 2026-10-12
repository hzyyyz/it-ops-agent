from pathlib import Path
import json

import pytest


def test_dataset_has_fifty_labeled_cases():
    from evaluation.dataset import load_cases

    cases = load_cases(Path(__file__).with_name("eval_dataset.json"))
    assert len(cases) == 50
    assert {case["category"] for case in cases} == {
        "tool_call", "rag", "mixed", "health_report", "non_it"
    }
    assert len({case["id"] for case in cases}) == 50
    assert all(case.get("expected_passage") for case in cases if case.get("expected_sources"))


def test_dataset_requires_relative_source_path(tmp_path):
    from evaluation.dataset import load_cases

    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{"id": "x", "category": "rag", "question": "test",
                                 "expected_tools": [], "expected_sources": ["same.txt"],
                                 "expected_passage": "text"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="source"):
        load_cases(path)


def test_recall_and_tool_metrics_have_explicit_denominators():
    from evaluation.metrics import recall_at_k, passage_recall_at_k, summarize_results

    assert recall_at_k(["other.txt", "data/故障排除.txt"], ["data/故障排除.txt"], 1) == 0
    assert recall_at_k(["other.txt", "data/故障排除.txt"], ["data/故障排除.txt"], 3) == 1
    assert recall_at_k(["other/同名.txt"], ["data/同名.txt"], 3) == 0
    assert passage_recall_at_k(["其他步骤", "蓝屏错误代码 0x000000D1"], "0x000000D1", 1) == 0
    assert passage_recall_at_k(["其他步骤", "蓝屏错误代码 0x000000D1"], "0x000000D1", 3) == 1
    results = [
        {"id": "a", "category": "tool_call", "expected_tools": ["get_cpu_usage"],
         "observed_tools": ["get_cpu_usage"], "answer": "CPU 20%", "first_token_ms": 10,
         "total_ms": 30, "input_tokens": 5, "output_tokens": 3},
        {"id": "b", "category": "tool_call", "expected_tools": ["get_memory_usage"],
         "observed_tools": [], "answer": "", "first_token_ms": None,
         "total_ms": 50, "input_tokens": 0, "output_tokens": 0},
    ]
    summary = summarize_results(results)
    assert summary["tool_selection_recall"] == 0.5
    assert summary["task_success_proxy_rate"] == 0.5
    assert summary["first_token_latency_ms"]["mean"] == 10
    assert summary["total_latency_ms"]["mean"] == 40
    assert summary["input_tokens"] == 5
    assert summary["output_tokens"] == 3
    assert summarize_results([{"id": "failed", "expected_tools": [], "observed_tools": [],
                               "answer": "", "error_type": "AuthenticationError"}])["error_count"] == 1
    retrieval = summarize_results([{"id": "r", "expected_sources": ["data/故障排除.txt"],
                                    "retrieved_sources": ["data/故障排除.txt"],
                                    "expected_passage": "蓝屏错误代码",
                                    "retrieved_passages": ["无关内容"]}])
    assert retrieval["source_recall_at_3"] == 1
    assert retrieval["rag_recall_at_3"] == 0


def test_agent_trace_counts_tools_tokens_and_first_token():
    from evaluation.agent_trace import trace_agent
    from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

    class Graph:
        def stream(self, *args, **kwargs):
            assert kwargs["stream_mode"] == ["messages", "values"]
            yield "messages", (AIMessageChunk(content="CPU"), {"langgraph_node": "model"})
            yield "values", {"messages": [
                HumanMessage(content="CPU?"),
                AIMessage(content="", tool_calls=[{"name": "get_cpu_usage", "args": {}, "id": "1"}],
                          usage_metadata={"input_tokens": 8, "output_tokens": 2, "total_tokens": 10}),
                ToolMessage(content="20%", tool_call_id="1"),
                AIMessage(content="CPU 20%", usage_metadata={"input_tokens": 10, "output_tokens": 4,
                                                        "total_tokens": 14}),
            ]}

    trace = trace_agent(Graph(), "CPU?")
    assert trace["answer"] == "CPU 20%"
    assert trace["observed_tools"] == ["get_cpu_usage"]
    assert trace["input_tokens"] == 18
    assert trace["output_tokens"] == 6
    assert trace["first_token_ms"] is not None


def test_retrieval_runner_records_sources_and_latency():
    from evaluation.runner import run_retrieval
    from langchain_core.documents import Document

    class Pipeline:
        last_trace = {"mode": "advanced", "reranked": True}

        def retrieve(self, question):
            assert question == "蓝屏怎么办"
            return [Document(page_content="步骤", metadata={"source": "data/故障排除.txt"})]

    cases = [{"id": "x", "category": "rag", "question": "蓝屏怎么办",
              "expected_tools": ["search_knowledge_base"], "expected_sources": ["data/故障排除.txt"],
              "expected_passage": "步骤"}]
    rows = run_retrieval(cases, Pipeline())
    assert rows[0]["retrieved_sources"] == ["data/故障排除.txt"]
    assert rows[0]["retrieved_passages"] == ["步骤"]
    assert rows[0]["retrieval_trace"]["reranked"] is True
    assert rows[0]["total_ms"] >= 0


def test_agent_runner_includes_initialization_in_latency():
    import time
    from evaluation.runner import run_agent
    from langchain_core.messages import AIMessage, AIMessageChunk

    class Graph:
        def stream(self, *args, **kwargs):
            yield "messages", (AIMessageChunk(content="好"), {"langgraph_node": "model"})
            yield "values", {"messages": [AIMessage(content="好")]}

    def factory():
        time.sleep(0.02)
        return Graph()

    rows = run_agent([{"id": "x", "category": "non_it", "question": "你好",
                       "expected_tools": []}], agent_factory=factory)
    assert rows[0]["first_token_ms"] >= 15
    assert rows[0]["total_ms"] >= 15


def test_report_trace_measures_real_workflow_steps_and_model_usage():
    from agent.report_workflow import ReportWorkflow
    from evaluation.agent_trace import trace_report
    from langchain_core.messages import AIMessageChunk

    class Model:
        def stream(self, messages):
            yield AIMessageChunk(content="报告", usage_metadata={
                "input_tokens": 11, "output_tokens": 4, "total_tokens": 15,
            })

    workflow = ReportWorkflow(asset_lookup=lambda employee_id, month: str({
        "设备配置": "ThinkPad", "运行状态": "正常", "维保记录": "已更新", "安全评分": "95分"}),
        report_model=Model())
    row = trace_report(workflow, "生成 EMP1001 在 2025-06 的设备健康报告")
    assert row["answer"] == "报告"
    assert row["observed_tools"] == ["query_asset_record"]
    assert row["report_generated"] is True
    assert (row["input_tokens"], row["output_tokens"]) == (11, 4)
    assert row["first_token_ms"] is not None


def test_missing_report_data_does_not_count_as_task_success():
    from evaluation.metrics import summarize_results

    summary = summarize_results([{"id": "missing", "category": "health_report",
                                  "expected_tools": ["query_asset_record"],
                                  "observed_tools": ["query_asset_record"],
                                  "answer": "未找到台账", "report_generated": False}])
    assert summary["task_success_proxy_rate"] == 0


def test_default_agent_runner_uses_new_report_workflow(monkeypatch):
    from agent import report_workflow
    from evaluation.runner import run_agent
    from langchain_core.messages import AIMessageChunk

    class Model:
        def stream(self, messages):
            yield AIMessageChunk(content="新工作流报告")

    real_workflow = report_workflow.ReportWorkflow
    monkeypatch.setattr(report_workflow, "ReportWorkflow", lambda: real_workflow(
        asset_lookup=lambda employee_id, month: str({
            "设备配置": "ThinkPad", "运行状态": "正常", "维保记录": "已更新", "安全评分": "95分"}),
        report_model=Model()))
    rows = run_agent([{"id": "r", "category": "health_report",
                       "question": "生成 EMP1001 在 2025-06 的设备健康报告",
                       "expected_tools": ["query_asset_record"]}])
    assert rows[0]["answer"] == "新工作流报告"
    assert rows[0]["report_generated"] is True


def test_default_runner_routes_by_request_text_even_if_case_label_differs(monkeypatch):
    from agent import report_workflow
    from evaluation.runner import run_agent
    from langchain_core.messages import AIMessageChunk

    class Model:
        def stream(self, messages):
            yield AIMessageChunk(content="报告")

    real_workflow = report_workflow.ReportWorkflow
    monkeypatch.setattr(report_workflow, "ReportWorkflow", lambda **kwargs: real_workflow(
        asset_lookup=lambda employee_id, month: str({
            "设备配置": "ThinkPad", "运行状态": "正常", "维保记录": "已更新", "安全评分": "95分"}),
        report_model=Model(), **kwargs))
    rows = run_agent([{"id": "r", "category": "mixed",
                       "question": "生成 EMP1001 在 2025-06 的设备健康报告",
                       "expected_tools": ["query_asset_record"]}])
    assert rows[0]["report_generated"] is True


def test_report_eval_uses_pinned_demo_context(monkeypatch):
    from agent import report_workflow
    from evaluation.runner import run_agent

    seen = []
    real_workflow = report_workflow.ReportWorkflow
    monkeypatch.setattr(report_workflow, "ReportWorkflow", lambda **kwargs: real_workflow(
        asset_lookup=lambda employee_id, month: seen.append((employee_id, month)) or "", **kwargs))
    run_agent([{"id": "r", "category": "health_report", "question": "生成我的本月设备健康报告",
                "expected_tools": ["get_employee_id", "get_current_month", "query_asset_record"],
                "eval_context": {"employee_id": "EMP1001", "month": "2025-06"}}])
    assert seen == [("EMP1001", "2025-06")]
