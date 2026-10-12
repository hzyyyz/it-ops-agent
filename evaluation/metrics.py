"""Pure aggregation of observed evaluation results."""

from statistics import mean


def recall_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    if not expected:
        raise ValueError("Expected source set cannot be empty")
    found = [path.replace("\\", "/").strip("/").casefold() for path in retrieved[:k]]
    wanted = [path.replace("\\", "/").strip("/").casefold() for path in expected]
    return sum(any(actual == target or actual.endswith("/" + target) for actual in found)
               for target in wanted) / len(wanted)


def passage_recall_at_k(retrieved: list[str], expected_passage: str, k: int) -> float:
    if not expected_passage:
        raise ValueError("Expected passage cannot be empty")
    needle = expected_passage.casefold()
    return float(any(needle in passage.casefold() for passage in retrieved[:k]))


def _latency(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "mean": None, "p50": None, "p95": None}
    return {"count": len(ordered), "mean": mean(ordered),
            "p50": ordered[(len(ordered) - 1) // 2],
            "p95": ordered[max(0, int(len(ordered) * 0.95 + 0.9999) - 1)]}


def summarize_results(results: list[dict]) -> dict:
    tool_cases = [row for row in results if "observed_tools" in row]
    required = sum(len(set(row["expected_tools"])) for row in tool_cases)
    selected = sum(len(set(row["expected_tools"]) & set(row["observed_tools"])) for row in tool_cases)
    observed = sum(len(set(row["observed_tools"])) for row in tool_cases)
    successes = sum(bool(row.get("answer", "").strip())
                    and set(row["expected_tools"]) <= set(row["observed_tools"])
                    and (bool(row["expected_tools"]) or not row["observed_tools"])
                    and row.get("report_generated", True)
                    for row in tool_cases)
    retrieval_cases = [row for row in results if row.get("expected_sources") and "retrieved_sources" in row]
    passage_cases = [row for row in retrieval_cases if row.get("expected_passage") and "retrieved_passages" in row]
    return {
        "case_count": len(results),
        "error_count": sum("error_type" in row for row in results),
        "tool_case_count": len(tool_cases),
        "tool_selection_recall": selected / required if required else None,
        "tool_selection_precision": selected / observed if observed else None,
        "task_success_proxy_rate": successes / len(tool_cases) if tool_cases else None,
        "retrieval_case_count": len(retrieval_cases),
        "source_recall_at_3": mean(recall_at_k(row["retrieved_sources"], row["expected_sources"], 3)
                                for row in retrieval_cases) if retrieval_cases else None,
        "source_recall_at_5": mean(recall_at_k(row["retrieved_sources"], row["expected_sources"], 5)
                                for row in retrieval_cases) if retrieval_cases else None,
        "rag_recall_at_3": mean(passage_recall_at_k(row["retrieved_passages"], row["expected_passage"], 3)
                                    for row in passage_cases) if passage_cases else None,
        "rag_recall_at_5": mean(passage_recall_at_k(row["retrieved_passages"], row["expected_passage"], 5)
                                    for row in passage_cases) if passage_cases else None,
        "first_token_latency_ms": _latency([row["first_token_ms"] for row in results
                                             if row.get("first_token_ms") is not None]),
        "total_latency_ms": _latency([row["total_ms"] for row in results
                                       if row.get("total_ms") is not None]),
        "input_tokens": sum(row.get("input_tokens", 0) for row in results),
        "output_tokens": sum(row.get("output_tokens", 0) for row in results),
    }
