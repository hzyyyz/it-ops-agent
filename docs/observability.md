# Agent 可观测性

每个 FastAPI 请求生成一个随机 `trace_id`。响应头 `X-Trace-Id` 返回该值；`POST /api/chat` 的 JSON 和 `POST /api/chat/stream` 的 `done` / `error` 事件也包含它。新会话的 `session_id` 在数据库保存后才写入后续事件。

事件以 JSON Lines 形式追加到 `logs/traces.jsonl`。可通过 `AGENT_TRACE_FILE` 指定其他路径。Docker Compose 已把 API 容器的 `/app/logs` 映射到项目的 `logs/`。文件写入失败时会输出错误类型警告，但不阻断聊天。

在 PowerShell 中按一次请求查看事件：

```powershell
$traceId = '<响应中的 trace_id>'
Get-Content logs/traces.jsonl | ConvertFrom-Json | Where-Object trace_id -eq $traceId |
    Select-Object timestamp,event,session_id,status,duration_ms,tool_name,doc_count,input_tokens,output_tokens
```

典型事件顺序如下：

```text
request.start → chat.start → agent.start
model.start → model.end
tool.start → rag.retrieval.start → rag.rewrite.start/end
rag.vector_search.start/end → rag.keyword_search.start/end
rag.fusion.start/end → rag.rerank.start/end → rag.retrieval.end
rag.answer.start → rag.answer.usage → rag.answer.end → tool.result → tool.end
model.start → model.end → agent.first_token → agent.end
chat.saved → chat.end → request.response → request.end
```

实际事件取决于请求：非 RAG 问题不会有检索事件；无本地重排模型时 `rag.rerank.end` 的状态为 `error`，最终检索事件标记 `rerank_failed=true` 并继续使用融合排序。流式响应的 `request.end` 表示响应头已返回，完整耗时应看 `chat.stream.end`。每个事件有 UTC 时间、`trace_id` 和可用时的 `session_id`；耗时单位为毫秒。

追踪只保存节点名、工具名、工具结果类型与长度、RAG 文档来源与数量、token、耗时、状态和异常类名。绝不写入 Chain of Thought、用户问题、改写后的查询、文档正文、工具参数或结果正文、模型回答、API Key。绝对文档路径会缩为 `data/` 下的相对路径或文件名。旧的普通日志也已停止打印模型消息与工具参数。

`model.end` 统计 Agent 直接调用的 token；RAG 内部改写与总结分别记录在 `rag.rewrite.usage` 和 `rag.answer.usage`。这些是模型返回的用量，不包含 Embedding 和本地重排计算。当前实现是单 API 进程的本地 JSONL 追踪；MCP 内部没有独立 span，能看到工具调用的耗时和成败。生产环境若使用多个 API worker，应把事件送入统一日志采集系统。

设备健康报告走独立 LangGraph 时，可看到 `report.route`、`report.resolve_identity`、`report.resolve_month`、`report.lookup_asset`、`report.collect_status`、`report.generate`、`report.reset` 等事件；缺少台账时改为 `report.missing_record`，不调用模型。模型返回 token 元数据时会记录 `report.model.usage`，不记录台账或报告正文。
