"""Configurable vector baseline and hybrid retrieval over the existing Chroma index."""

from collections import Counter
from contextvars import ContextVar
import math
import re
from time import perf_counter
from threading import Lock
from typing import Callable

from langchain_core.documents import Document
from observability.tracing import record, span


_TERMS = re.compile(r"[a-zA-Z][a-zA-Z0-9._-]*|\d+|[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    tokens = []
    for match in _TERMS.finditer(text.lower()):
        term = match.group()
        if "\u4e00" <= term[0] <= "\u9fff":
            tokens.extend(term[i:i + 2] for i in range(len(term) - 1))
            if len(term) == 1:
                tokens.append(term)
        else:
            tokens.append(term)
    return tokens


class BM25Index:
    def __init__(self, documents: list[Document]):
        self.documents = documents
        self.tokenized = [Counter(tokenize(doc.page_content)) for doc in documents]
        self.lengths = [sum(terms.values()) for terms in self.tokenized]
        self.average_length = sum(self.lengths) / len(self.lengths) if self.lengths else 1
        self.average_length = self.average_length or 1
        self.frequency = Counter(term for terms in self.tokenized for term in terms)
        self.postings: dict[str, set[int]] = {}
        for index, terms in enumerate(self.tokenized):
            for term in terms:
                self.postings.setdefault(term, set()).add(index)

    def search(self, query: str, limit: int) -> list[Document]:
        query_terms = set(tokenize(query))
        if not query_terms or not self.documents:
            return []
        scored = []
        candidate_ids = set().union(*(self.postings.get(term, set()) for term in query_terms))
        for index in candidate_ids:
            terms = self.tokenized[index]
            score = 0.0
            for term in query_terms & terms.keys():
                count = terms[term]
                idf = math.log(1 + (len(self.documents) - self.frequency[term] + 0.5)
                               / (self.frequency[term] + 0.5))
                score += idf * count * 2.5 / (count + 1.5 * (
                    0.25 + 0.75 * self.lengths[index] / self.average_length))
            if score:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [self.documents[index] for _, index in scored[:limit]]


def bm25_search(query: str, documents: list[Document], limit: int) -> list[Document]:
    return BM25Index(documents).search(query, limit)


def _doc_key(document: Document) -> tuple:
    metadata = document.metadata
    return (metadata.get("source"), metadata.get("page"), document.page_content)


def reciprocal_rank_fusion(vector_docs: list[Document], lexical_docs: list[Document],
                           limit: int, constant: int = 60, vector_weight: float = 2) -> list[Document]:
    scores: dict[tuple, float] = {}
    by_key: dict[tuple, Document] = {}
    for ranked, weight in ((vector_docs, vector_weight), (lexical_docs, 1.0)):
        for rank, document in enumerate(ranked, start=1):
            key = _doc_key(document)
            scores[key] = scores.get(key, 0) + weight / (constant + rank)
            by_key[key] = document
    return [by_key[key] for key in sorted(scores, key=scores.get, reverse=True)[:limit]]


class RetrievalPipeline:
    def __init__(self, vector_store, *, mode: str = "advanced",
                 rewriter: Callable[[str], str] | None = None, reranker=None,
                 candidate_k: int = 10, final_k: int = 3):
        if mode not in ("baseline", "advanced"):
            raise ValueError("RAG mode must be baseline or advanced")
        if candidate_k < final_k or final_k < 1:
            raise ValueError("candidate_k must be at least final_k >= 1")
        self.vector_store = vector_store
        self.mode = mode
        self.rewriter = rewriter
        self.reranker = reranker
        self.candidate_k = candidate_k
        self.final_k = final_k
        self._last_trace: ContextVar[dict | None] = ContextVar(
            f"rag_last_trace_{id(self)}", default=None
        )
        self._index_lock = Lock()
        self._lexical_index: BM25Index | None = None

    @property
    def last_trace(self) -> dict:
        return self._last_trace.get() or {}

    @last_trace.setter
    def last_trace(self, value: dict) -> None:
        self._last_trace.set(value)

    def _corpus(self) -> list[Document]:
        rows = self.vector_store.get(include=["documents", "metadatas"])
        return [Document(page_content=content, metadata=metadata or {})
                for content, metadata in zip(rows["documents"], rows["metadatas"])
                if content and content.strip()]

    def invalidate_lexical_index(self) -> None:
        """Call after modifying this vector collection in the current process."""
        with self._index_lock:
            self._lexical_index = None

    def _get_lexical_index(self) -> BM25Index:
        with self._index_lock:
            if self._lexical_index is None:
                self._lexical_index = BM25Index(self._corpus())
            return self._lexical_index

    def retrieve(self, query: str) -> list[Document]:
        started = perf_counter()
        record("rag.retrieval.start", mode=self.mode, query_chars=len(query))
        try:
            result, details = self._retrieve(query)
        except Exception as exc:
            record("rag.retrieval.end", mode=self.mode, status="error",
                   error_type=type(exc).__name__,
                   duration_ms=round((perf_counter() - started) * 1000, 3))
            raise
        self.last_trace = details
        record("rag.retrieval.end", mode=self.mode, status="ok", doc_count=len(result),
               sources=[str(doc.metadata.get("source", "")) for doc in result],
               candidate_count=details.get("candidate_count"),
               reranked=details.get("reranked"),
               rewrite_failed=details.get("rewrite_failed"),
               rerank_failed=details.get("rerank_failed"),
               vector_count=details.get("vector_count"),
               lexical_count=details.get("lexical_count"),
               duration_ms=round((perf_counter() - started) * 1000, 3))
        return result

    def _retrieve(self, query: str) -> tuple[list[Document], dict]:
        rewritten = query
        rewrite_failed = False
        if self.mode == "advanced" and self.rewriter:
            try:
                with span("rag.rewrite"):
                    rewritten = self.rewriter(query).strip() or query
            except Exception:
                rewrite_failed = True
        if self.mode == "baseline":
            with span("rag.vector_search", mode=self.mode):
                result = self.vector_store.similarity_search(query, k=self.final_k)
            details = {"original_query": query, "rewritten_query": query,
                       "mode": self.mode, "reranked": False, "rerank_failed": False,
                       "rewrite_failed": False, "candidate_count": len(result)}
            return result, details

        with span("rag.vector_search", mode=self.mode):
            vector_docs = self.vector_store.similarity_search(rewritten, k=self.candidate_k)
        with span("rag.keyword_search"):
            lexical_docs = self._get_lexical_index().search(rewritten, self.candidate_k)
        with span("rag.fusion"):
            candidates = reciprocal_rank_fusion(vector_docs, lexical_docs, self.candidate_k)
        reranked = False
        rerank_failed = False
        if self.reranker and candidates:
            try:
                with span("rag.rerank", candidate_count=len(candidates)):
                    scores = self.reranker.predict([(rewritten, doc.page_content) for doc in candidates])
                    if len(scores) != len(candidates):
                        raise ValueError("Reranker returned a wrong number of scores")
                    candidates = [doc for _, doc in sorted(zip(scores, candidates), key=lambda item: -float(item[0]))]
                    reranked = True
            except Exception:
                # Keep fused results available when an optional local model is absent.
                rerank_failed = True
        details = {"original_query": query, "rewritten_query": rewritten,
                   "mode": self.mode, "reranked": reranked, "rerank_failed": rerank_failed,
                   "rewrite_failed": rewrite_failed, "candidate_count": len(candidates),
                   "vector_count": len(vector_docs), "lexical_count": len(lexical_docs)}
        return candidates[:self.final_k], details
