# 增量知识库更新实施计划

1. 在 `tests/test_knowledge_sync.py` 写同步器行为测试；先确认现有实现不能通过。覆盖新文件、原样重跑、局部改动、删除、重复 chunk 和失败保护。
2. 在 `rag/knowledge_sync.py` 实现来源规范化、稳定 chunk ID、Chroma 对账和统计；通过测试后做必要重构。
3. 让 `rag/vector_store.py` 的 `load_document()` 调用同步器，移除 `md5.text` 写入路径，保持命令行入口；让 RAG 进程可主动使 BM25 缓存失效。
4. 更新 README 和配置说明，说明旧索引迁移、嵌入次数、运行方式和当前 API 更新时缓存边界。
5. 运行针对性测试、完整测试、语法检查和 diff 检查，检查实际 Chroma 持久化能否完成一轮新建与局部更新。
