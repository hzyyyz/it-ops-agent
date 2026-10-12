from langchain_core.documents import Document


def doc(text, source):
    return Document(page_content=text, metadata={"source": source})


def test_bm25_recovers_exact_operational_terms():
    from rag.retrieval import bm25_search

    corpus = [doc("Redis OOM 内存溢出排查", "redis.md"),
              doc("打印机驱动安装流程", "printer.md")]
    assert bm25_search("Redis OOM", corpus, limit=1)[0].metadata["source"] == "redis.md"


def test_fusion_deduplicates_and_rewards_shared_hits():
    from rag.retrieval import reciprocal_rank_fusion

    a, b, c = [doc(text, text) for text in ("A", "B", "C")]
    result = reciprocal_rank_fusion([a, b], [b, c], limit=3)
    assert [item.metadata["source"] for item in result] == ["B", "A", "C"]


def test_fusion_can_prioritize_semantic_rank_when_keyword_match_is_broad():
    from rag.retrieval import reciprocal_rank_fusion

    a, b = doc("specific", "a"), doc("broad", "b")
    result = reciprocal_rank_fusion([a, b], [b, a], limit=2, vector_weight=2)
    assert result[0].metadata["source"] == "a"


def test_advanced_pipeline_rewrites_fuses_and_reranks():
    from rag.retrieval import RetrievalPipeline

    redis = doc("Redis OOM 故障", "redis.md")
    printer = doc("打印机驱动", "printer.md")

    class Store:
        def similarity_search(self, query, k):
            assert query == "Redis 内存故障排查"
            return [printer, redis]

        def get(self, **kwargs):
            return {"documents": [redis.page_content, printer.page_content],
                    "metadatas": [redis.metadata, printer.metadata]}

    class Reranker:
        def predict(self, pairs):
            return [10 if "OOM" in passage else 0 for _, passage in pairs]

    pipeline = RetrievalPipeline(Store(), rewriter=lambda _: "Redis 内存故障排查",
                                 reranker=Reranker(), candidate_k=10, final_k=1)
    assert pipeline.retrieve("redis怎么老是寄")[0].metadata["source"] == "redis.md"
    assert pipeline.last_trace["rewritten_query"] == "Redis 内存故障排查"
    assert pipeline.last_trace["reranked"] is True


def test_baseline_uses_only_original_vector_query():
    from rag.retrieval import RetrievalPipeline

    class Store:
        def similarity_search(self, query, k):
            assert (query, k) == ("原问题", 3)
            return [doc("answer", "a")]

    pipeline = RetrievalPipeline(Store(), mode="baseline", rewriter=lambda _: 1 / 0)
    assert pipeline.retrieve("原问题")[0].page_content == "answer"
    assert pipeline.last_trace["reranked"] is False


def test_missing_local_reranker_falls_back_to_fused_order():
    from rag.retrieval import RetrievalPipeline

    chosen = doc("CPU 占用过高", "faults.txt")

    class Store:
        def similarity_search(self, query, k):
            return [chosen]

        def get(self, **kwargs):
            return {"documents": [chosen.page_content], "metadatas": [chosen.metadata]}

    class MissingModel:
        def predict(self, pairs):
            raise OSError("not cached")

    pipeline = RetrievalPipeline(Store(), rewriter=lambda q: q, reranker=MissingModel())
    assert pipeline.retrieve("CPU 高")[0].page_content == chosen.page_content
    assert pipeline.last_trace["reranked"] is False
    assert pipeline.last_trace["rerank_failed"] is True


def test_local_reranker_uses_cached_snapshot_path(monkeypatch, tmp_path):
    from model import factory
    from rag.reranker import LocalCrossEncoder
    import sentence_transformers

    loaded = []

    class FakeCrossEncoder:
        def __init__(self, path, *, local_files_only):
            loaded.append((path, local_files_only))

        def predict(self, pairs):
            return [1.0] * len(pairs)

    monkeypatch.setattr(factory, "_resolve_local_model_path", lambda _: str(tmp_path))
    monkeypatch.setattr(sentence_transformers, "CrossEncoder", FakeCrossEncoder)
    assert list(LocalCrossEncoder().predict([("query", "document")])) == [1.0]
    assert loaded == [(str(tmp_path), True)]


def test_lexical_index_is_reused_until_invalidated():
    from rag.retrieval import RetrievalPipeline

    class Store:
        reads = 0

        def similarity_search(self, query, k):
            return []

        def get(self, **kwargs):
            self.reads += 1
            return {"documents": ["Redis OOM"], "metadatas": [{"source": "data/redis.txt"}]}

    store = Store()
    pipeline = RetrievalPipeline(store, rewriter=lambda q: q)
    pipeline.retrieve("Redis")
    pipeline.retrieve("OOM")
    assert store.reads == 1
    pipeline.invalidate_lexical_index()
    pipeline.retrieve("Redis")
    assert store.reads == 2


def test_rag_service_uses_pipeline_and_preserves_answer_prompt(monkeypatch):
    import rag.rag_service as module

    chosen = doc("Redis OOM 的排查步骤", "redis.md")

    class Store:
        def similarity_search(self, query, k):
            return [chosen]

        def get(self, **kwargs):
            return {"documents": [chosen.page_content], "metadatas": [chosen.metadata]}

    class Service:
        vector_store = Store()

        def get_retriever(self):
            return None

    seen = []

    class Chain:
        def invoke(self, value):
            seen.append(value)
            return "回答"

    monkeypatch.setattr(module, "VectorStoreService", Service)
    monkeypatch.setattr(module.RagSummarizeService, "_init_chain", lambda self: Chain())
    rag = module.RagSummarizeService(mode="advanced", rewriter=lambda q: q,
                                     reranker=None)
    assert rag.rag_summarize("Redis 故障") == "回答"
    assert seen[0]["input"] == "Redis 故障"
    assert chosen.page_content in seen[0]["context"]


def test_rag_service_sync_invalidates_current_bm25_index():
    from rag.rag_service import RagSummarizeService

    calls = []

    class Store:
        def load_document(self, *, invalidate):
            invalidate()
            return {"added": 1, "kept": 0, "deleted": 0, "failed": 0}

    class Pipeline:
        def invalidate_lexical_index(self):
            calls.append("invalidated")

    service = object.__new__(RagSummarizeService)
    service.vector_store = Store()
    service.pipeline = Pipeline()
    assert service.sync_knowledge()["added"] == 1
    assert calls == ["invalidated"]
