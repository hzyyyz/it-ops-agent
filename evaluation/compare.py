"""Compare two saved retrieval reports without overstating feature coverage."""

import argparse
import json
from pathlib import Path


def compare_reports(baseline: dict, advanced: dict) -> dict:
    if (baseline.get("dataset") != advanced.get("dataset")
            or baseline.get("selected_case_count") != advanced.get("selected_case_count")):
        raise ValueError("Reports must use the same dataset and case count")
    if not baseline.get("dataset_fingerprint") or not advanced.get("dataset_fingerprint"):
        raise ValueError("Reports are missing dataset content fingerprints; rerun both evaluations")
    if baseline["dataset_fingerprint"] != advanced["dataset_fingerprint"]:
        raise ValueError("Reports use different dataset content")
    if not baseline.get("index_fingerprint") or not advanced.get("index_fingerprint"):
        raise ValueError("Reports are missing knowledge index fingerprints; rerun both evaluations")
    if baseline["index_fingerprint"] != advanced["index_fingerprint"]:
        raise ValueError("Reports use different knowledge indexes")
    left = baseline.get("retrieval_results", [])
    right = advanced.get("retrieval_results", [])
    if [row.get("id") for row in left] != [row.get("id") for row in right]:
        raise ValueError("Reports must contain the same retrieval case IDs in order")
    reranked = sum(row.get("retrieval_trace", {}).get("reranked") is True for row in right)
    rewrite_ok = sum(not row.get("retrieval_trace", {}).get("rewrite_failed", False) for row in right)
    baseline_recall = baseline.get("retrieval_summary", {}).get("rag_recall_at_3")
    advanced_recall = advanced.get("retrieval_summary", {}).get("rag_recall_at_3")
    return {
        "comparable": True,
        "retrieval_case_count": len(right),
        "baseline_rag_recall_at_3": baseline_recall,
        "advanced_rag_recall_at_3": advanced_recall,
        "rag_recall_at_3_delta": (advanced_recall - baseline_recall
                                   if baseline_recall is not None and advanced_recall is not None else None),
        "reranked_cases": reranked,
        "rewrite_requested": bool(advanced.get("rewrite_enabled")),
        "rewrite_success_cases": rewrite_ok if advanced.get("rewrite_enabled") else 0,
        "full_advanced_path_verified": bool(right) and reranked == len(right)
        and bool(advanced.get("rewrite_enabled")) and rewrite_ok == len(right),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare baseline and advanced RAG reports")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("advanced", type=Path)
    args = parser.parse_args(argv)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    advanced = json.loads(args.advanced.read_text(encoding="utf-8"))
    print(json.dumps(compare_reports(baseline, advanced), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
