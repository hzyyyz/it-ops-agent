def test_compare_reports_requires_actual_advanced_features():
    from evaluation.compare import compare_reports

    baseline = {"rag_mode": "baseline", "dataset": "cases.json", "selected_case_count": 2,
                "dataset_fingerprint": "same-dataset", "index_fingerprint": "same-index",
                "retrieval_summary": {"rag_recall_at_3": 0.5}, "retrieval_results": [
                    {"id": "a"}, {"id": "b"}]}
    advanced = {"rag_mode": "advanced", "dataset": "cases.json", "selected_case_count": 2,
                "dataset_fingerprint": "same-dataset", "index_fingerprint": "same-index",
                "rewrite_enabled": False, "retrieval_summary": {"rag_recall_at_3": 1.0},
                "retrieval_results": [
                    {"id": "a", "retrieval_trace": {"reranked": False, "rerank_failed": True}},
                    {"id": "b", "retrieval_trace": {"reranked": False, "rerank_failed": True}}]}
    comparison = compare_reports(baseline, advanced)
    assert comparison["rag_recall_at_3_delta"] == 0.5
    assert comparison["comparable"] is True
    assert comparison["reranked_cases"] == 0
    assert comparison["full_advanced_path_verified"] is False


def test_compare_rejects_different_datasets():
    from evaluation.compare import compare_reports
    import pytest

    with pytest.raises(ValueError, match="same dataset"):
        compare_reports({"dataset": "a", "selected_case_count": 1},
                        {"dataset": "b", "selected_case_count": 1})


def test_compare_rejects_changed_dataset_or_index():
    from evaluation.compare import compare_reports

    import pytest

    base = {"dataset": "cases.json", "selected_case_count": 1,
            "dataset_fingerprint": "original", "index_fingerprint": "index-a",
            "retrieval_results": [{"id": "a"}]}
    with pytest.raises(ValueError, match="dataset content"):
        compare_reports(base, {**base, "dataset_fingerprint": "changed"})
    with pytest.raises(ValueError, match="knowledge index"):
        compare_reports(base, {**base, "index_fingerprint": "index-b"})
