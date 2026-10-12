"""Validate the labeled evaluation set before running any costly cases."""

import json
from pathlib import Path
import re


CATEGORIES = {"tool_call", "rag", "mixed", "health_report", "non_it"}


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("Evaluation dataset must be a nonempty JSON array")
    ids = set()
    for case in data:
        if (not isinstance(case, dict) or not isinstance(case.get("id"), str)
                or not isinstance(case.get("question"), str) or not case["question"].strip()
                or case.get("category") not in CATEGORIES
                or not isinstance(case.get("expected_tools"), list)
                or any(not isinstance(tool, str) for tool in case["expected_tools"])):
            raise ValueError("Invalid evaluation case")
        if case["id"] in ids:
            raise ValueError(f"Duplicate evaluation case: {case['id']}")
        ids.add(case["id"])
        context = case.get("eval_context")
        if context is not None and (case["category"] != "health_report" or not isinstance(context, dict)
                                    or set(context) != {"employee_id", "month"}
                                    or not isinstance(context["employee_id"], str)
                                    or not re.fullmatch(r"EMP\d{4}", context["employee_id"])
                                    or not isinstance(context["month"], str)
                                    or not re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", context["month"])):
            raise ValueError(f"Invalid evaluation context: {case['id']}")
        if case["category"] in ("rag", "mixed") and not case.get("expected_sources"):
            raise ValueError(f"Missing expected source: {case['id']}")
        for source in case.get("expected_sources", []):
            normalized = source.replace("\\", "/") if isinstance(source, str) else ""
            if ("/" not in normalized or normalized.startswith("/")
                    or ":" in normalized.split("/")[0] or ".." in normalized.split("/")):
                raise ValueError(f"Expected source must be a relative path: {case['id']}")
        if case["category"] in ("rag", "mixed") and not case.get("expected_passage"):
            raise ValueError(f"Missing expected passage: {case['id']}")
    return data
