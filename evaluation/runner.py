"""Run labeled retrieval checks offline or an explicitly selected live Agent evaluation.

Examples:
  python -m evaluation.runner --mode retrieval --rag-mode baseline
  python -m evaluation.runner --mode retrieval --rag-mode advanced
  python -m evaluation.runner --mode agent --limit 5
"""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter

from evaluation.agent_trace import trace_agent, trace_report
from evaluation.dataset import load_cases
from evaluation.metrics import summarize_results
from utils.config_handler import rag_conf


DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "tests" / "eval_dataset.json"


def index_fingerprint(vector_store) -> str:
    """Hash the actual indexed text and metadata, independent of Chroma row order."""
    rows = vector_store.get(include=["documents", "metadatas"])
    entries = sorted(zip(rows["ids"], rows["documents"], rows["metadatas"]), key=lambda row: row[0])
    digest = sha256()
    for row in entries:
        digest.update(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def save_report_to_db(report: dict) -> str:
    from sqlalchemy.orm import Session
    from backend.database import get_engine
    from backend.services.metadata_catalog import EvaluationCatalog

    with Session(get_engine(), expire_on_commit=False) as db:
        return EvaluationCatalog(db).save(report)


def run_retrieval(cases: list[dict], pipeline) -> list[dict]:
    results = []
    for case in cases:
        if not case.get("expected_sources"):
            continue
        start = perf_counter()
        row = {key: case[key] for key in ("id", "category", "question", "expected_tools", "expected_sources", "expected_passage")}
        try:
            docs = pipeline.retrieve(case["question"])
            row["retrieved_sources"] = [str(doc.metadata.get("source", "")) for doc in docs]
            row["retrieved_passages"] = [doc.page_content for doc in docs]
            row["retrieval_trace"] = pipeline.last_trace.copy()
        except Exception as exc:
            row["retrieved_sources"] = []
            row["retrieved_passages"] = []
            row["error_type"] = type(exc).__name__
        row["total_ms"] = (perf_counter() - start) * 1000
        results.append(row)
    return results


def run_agent(cases: list[dict], agent_factory=None) -> list[dict]:
    use_default_agent = agent_factory is None
    if agent_factory is None:
        from agent.react_agent import ReactAgent
        agent_factory = lambda: ReactAgent().agent
    results = []
    for case in cases:
        row = {key: case[key] for key in ("id", "category", "question", "expected_tools")}
        start = perf_counter()
        try:
            if use_default_agent:
                from agent.report_workflow import ReportWorkflow, is_report_request
            if use_default_agent and is_report_request(case["question"]):
                eval_context = case.get("eval_context", {})
                providers = {}
                if "employee_id" in eval_context:
                    providers["employee_id_provider"] = lambda value=eval_context["employee_id"]: value
                if "month" in eval_context:
                    providers["month_provider"] = lambda value=eval_context["month"]: value
                graph = ReportWorkflow(**providers)
                report_case = True
            else:
                graph = agent_factory()
                report_case = False
            setup_ms = (perf_counter() - start) * 1000
            trace = trace_report(graph, case["question"]) if report_case else trace_agent(graph, case["question"])
            trace["total_ms"] += setup_ms
            if trace["first_token_ms"] is not None:
                trace["first_token_ms"] += setup_ms
            row.update(trace)
        except Exception as exc:
            row.update({"answer": "", "observed_tools": [], "first_token_ms": None,
                        "total_ms": (perf_counter() - start) * 1000,
                        "input_tokens": 0, "output_tokens": 0,
                        "error_type": type(exc).__name__})
        results.append(row)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run reproducible RAG / Agent evaluation")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=("retrieval", "agent", "all"), default="retrieval")
    parser.add_argument("--rag-mode", choices=("baseline", "advanced"), default="advanced")
    parser.add_argument("--rewrite", action="store_true", help="Use the configured LLM for query rewriting")
    parser.add_argument("--category", choices=("tool_call", "rag", "mixed", "health_report", "non_it"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--save-db", action="store_true", help="Also save the summary to MySQL")
    parser.add_argument("--input-usd-per-million", type=float, default=0)
    parser.add_argument("--output-usd-per-million", type=float, default=0)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    cases = load_cases(args.dataset)
    if args.category:
        cases = [case for case in cases if case["category"] == args.category]
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        parser.error("No cases match the selected filters")

    retrieval_rows = []
    agent_rows = []
    corpus_fingerprint = None
    if args.mode in ("retrieval", "all"):
        from rag.rag_service import RagSummarizeService

        rewriter = None if args.rewrite else lambda query: query
        rag = RagSummarizeService(mode=args.rag_mode, rewriter=rewriter)
        # Evaluate both Recall@3 and Recall@5 over the same ranking.
        rag.pipeline.final_k = 5
        rag.pipeline.candidate_k = max(rag.pipeline.candidate_k, 5)
        corpus_fingerprint = index_fingerprint(rag.pipeline.vector_store)
        retrieval_rows = run_retrieval(cases, rag.pipeline)
    if args.mode in ("agent", "all"):
        agent_rows = run_agent(cases)

    retrieval_summary = summarize_results(retrieval_rows)
    agent_summary = summarize_results(agent_rows)
    estimated_cost = (agent_summary["input_tokens"] * args.input_usd_per_million
                      + agent_summary["output_tokens"] * args.output_usd_per_million) / 1_000_000
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset), "mode": args.mode, "rag_mode": args.rag_mode,
        "dataset_fingerprint": sha256(args.dataset.read_bytes()).hexdigest(),
        "index_fingerprint": corpus_fingerprint,
        "model_name": os.getenv("CHAT_MODEL_NAME", rag_conf.get("chat_model_name")),
        "model_base_url": os.getenv("OPENAI_BASE_URL", rag_conf.get("openai_base_url")),
        "rewrite_enabled": bool(args.rewrite and args.mode in ("retrieval", "all")),
        "selected_case_count": len(cases),
        "retrieval_summary": retrieval_summary, "agent_summary": agent_summary,
        "estimated_usd": estimated_cost if args.input_usd_per_million or args.output_usd_per_million else None,
        "retrieval_results": retrieval_rows, "agent_results": agent_rows,
        "notes": [
            "Task success is a deterministic proxy (required tools and a nonempty answer), not a semantic judgment.",
            "Retrieval mode without --rewrite does not measure LLM query rewriting.",
            "Missing local reranker weights leave reranked=false in each retrieval trace.",
            "Token totals cover Agent graph AI messages; nested RAG model calls may add uncounted tokens.",
        ],
    }
    output = args.output or Path("reports") / f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.save_db:
        print(f"Saved evaluation summary to MySQL: {save_report_to_db(report)}")
    print(f"Wrote {output}")
    print(json.dumps({"retrieval_summary": retrieval_summary, "agent_summary": agent_summary},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
