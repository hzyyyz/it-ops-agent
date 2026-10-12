# 增量知识库更新

将 `.txt` 或 `.pdf` 文件放在 `data/` 顶层，然后从项目根目录执行：

```bash
python -m rag.vector_store
```

命令扫描当前目录，与 Chroma 中同来源的 chunk 对账。每个 chunk 用来源、内容 MD5、PDF 页码和重复出现序号生成稳定 ID。未变的 chunk 保留原向量；新增或修改的 chunk 才计算 Embedding；旧内容及已删除文件的 chunk 会被移除。命令输出 `新增 / 保留 / 删除 / 失败` 四项计数；有文件失败时退出码为 1。写入新 chunk 失败时不会主动删除旧 chunk；若写入成功后删除失败，新旧 chunk 可能暂时并存，修复问题后重跑命令会收敛到正确状态。空文件会清掉它以前的 chunk。

首次从旧版索引迁移时，由于原记录没有稳定 chunk ID，同来源旧记录会被替换，可能重新嵌入一次。迁移时也能识别旧版记录中 Windows 或 Linux 的绝对来源路径。旧 `md5.text` 文件不再读取，也不需要手动清空 Chroma。知识库内容不同于 `data/external/records.csv` 员工台账；同步器只处理 `data/` 顶层的 txt/pdf 文件。

BM25 词法索引缓存在 API 进程中。若在终端运行同步命令，完成后重启 API，保证词法检索马上使用新内容；同进程调用 `RagSummarizeService.sync_knowledge()` 时会自动清缓存，包括部分写入失败的情况。当前没有上传 API 或多进程热更新通知，因此每个 API 进程都需要重启。同步过程会对 Chroma 目录中的 `.knowledge-sync.lock` 加跨进程锁；已有同步运行时，第二个命令立即报锁冲突，不会并发写入。

本地验证：

```bash
python -m pytest tests/test_knowledge_sync.py tests/test_rag_retrieval.py -q
```
