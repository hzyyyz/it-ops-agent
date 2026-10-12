# Agent observability implementation plan

Goal: correlate one API request with Agent, model, tool, and RAG execution through a trace ID, without retaining prompt, answer, tool arguments/results, or chain-of-thought.

Design: a context-local trace scope writes allowlisted metadata events as JSON Lines to `logs/traces.jsonl`. Chat HTTP and SSE expose the same trace ID. Model/tool middleware and RAG stages record durations, counts, token usage where available, and exception class names. A missing trace scope is a no-op, so offline scripts remain unaffected. No new unauthenticated trace-reading API is added.

1. Add failing tests for request correlation, SSE completion/error, privacy, structured spans, and model/tool/RAG events.
2. Implement the trace recorder, API integration, middleware and RAG instrumentation.
3. Document event schema, log location, limits, and run focused plus full regression tests.
