"""Lazy, offline cross-encoder reranker for hybrid RAG candidates."""

import os


class LocalCrossEncoder:
    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("RAG_RERANKER_MODEL", "BAAI/bge-reranker-base")
        self._model = None
        self._unavailable = False

    def predict(self, pairs: list[tuple[str, str]]):
        if not pairs:
            return []
        if self._unavailable:
            raise RuntimeError("Reranker model is not cached locally")
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                from model.factory import _resolve_local_model_path
                self._model = CrossEncoder(_resolve_local_model_path(self.model_name),
                                           local_files_only=True)
            except Exception:
                self._unavailable = True
                raise
        return self._model.predict(pairs)
