# RAG Upgrade and Agent Evaluation Implementation Plan

**Goal:** Preserve the existing vector baseline, add a configurable rewrite → hybrid retrieval → rerank pipeline, and make retrieval and Agent behavior measurable from a 50-case dataset.

**Architecture:** RAG retrieval becomes a separate injectable pipeline. It reads the existing Chroma index, merges vector and BM25 results with reciprocal rank fusion, and reranks a bounded candidate set with a lazily loaded local cross-encoder. The evaluator runs offline retrieval checks by default and opt-in live Agent checks, recording raw cases and aggregate metrics without storing reasoning traces.

**Tech Stack:** LangChain/Chroma, sentence-transformers CrossEncoder, Python stdlib BM25, pytest, JSON reports.

## Task 1: Hybrid RAG

- [x] Write failing tests for tokenization, lexical ranking, fusion, baseline selection, rewrite, rerank and fallback.
- [x] Implement the retrieval pipeline and connect `RagSummarizeService` while keeping the baseline selectable.
- [x] Run focused RAG tests.

## Task 2: Evaluation dataset and metrics

- [x] Create 50 representative labeled cases across tool calls, RAG, mixed tasks, reports, and non-IT questions.
- [x] Write failing tests for dataset validation, Recall@3/@5, tool selection, task-success proxy, latency and token accounting.
- [x] Implement offline retrieval and opt-in Agent runners with JSON reports.
- [x] Run focused evaluation tests.

## Task 3: Documentation and verification

- [x] Document config, commands, model-cache behavior and interpretation limits.
- [x] Run full regression suite and inspect diff after final fixes.
