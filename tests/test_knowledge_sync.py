from pathlib import Path

from langchain_core.documents import Document
from filelock import FileLock, Timeout
import pytest


class FakeStore:
    def __init__(self):
        self.rows = {}
        self.added = []
        self.deleted = []
        self.fail_add = False
        self.fail_delete = False

    def get(self, **kwargs):
        return {"ids": list(self.rows),
                "documents": [doc.page_content for doc in self.rows.values()],
                "metadatas": [doc.metadata for doc in self.rows.values()]}

    def add_documents(self, documents, ids):
        if self.fail_add:
            raise RuntimeError("embedding failed")
        self.added.extend(ids)
        self.rows.update(zip(ids, documents))

    def delete(self, ids):
        if self.fail_delete:
            raise RuntimeError("delete failed")
        self.deleted.extend(ids)
        for chunk_id in ids:
            self.rows.pop(chunk_id)


class LineSplitter:
    def split_documents(self, documents):
        return [Document(page_content=line, metadata=doc.metadata.copy())
                for doc in documents for line in doc.page_content.splitlines() if line]


def make_sync(tmp_path, store, invalidate=lambda: None):
    from rag.knowledge_sync import KnowledgeSync

    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return KnowledgeSync(store, LineSplitter(), data, tmp_path, invalidate=invalidate), data


def test_unchanged_chunks_are_not_reembedded(tmp_path):
    store = FakeStore()
    sync, data = make_sync(tmp_path, store)
    (data / "guide.txt").write_text("Redis OOM\n检查内存\n", encoding="utf-8")

    first = sync.run()
    assert first["added"] == 2
    assert first["kept"] == 0
    assert len(store.added) == 2
    second = sync.run()
    assert second["added"] == 0
    assert second["kept"] == 2
    assert second["deleted"] == 0
    assert len(store.added) == 2
    assert {doc.metadata["source"] for doc in store.rows.values()} == {"data/guide.txt"}


def test_symlink_outside_knowledge_is_not_indexed(tmp_path):
    store = FakeStore()
    sync, data = make_sync(tmp_path, store)
    outside = tmp_path / "private.txt"
    outside.write_text("private content", encoding="utf-8")
    try:
        (data / "linked.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable")
    assert sync.run() == {"added": 0, "kept": 0, "deleted": 0, "failed": 0}
    assert store.rows == {}


def test_orphaned_managed_chunk_is_removed(tmp_path):
    store = FakeStore()
    sync, _ = make_sync(tmp_path, store)
    store.rows["kb:orphan"] = Document(page_content="private content", metadata={"source": None})
    assert sync.run()["deleted"] == 1
    assert store.rows == {}


def test_modified_file_only_embeds_new_chunk_and_deletes_stale_chunk(tmp_path):
    store = FakeStore()
    invalidations = []
    sync, data = make_sync(tmp_path, store, invalidate=lambda: invalidations.append(1))
    file = data / "guide.txt"
    file.write_text("保留段落\n旧段落\n", encoding="utf-8")
    sync.run()
    old_ids = set(store.rows)

    file.write_text("新增段落\n保留段落\n", encoding="utf-8")
    result = sync.run()
    assert result == {"added": 1, "kept": 1, "deleted": 1, "failed": 0}
    assert len(store.added) == 3
    assert len(old_ids & set(store.rows)) == 1
    assert {doc.page_content for doc in store.rows.values()} == {"新增段落", "保留段落"}
    assert len(invalidations) == 2


def test_deleted_source_is_removed_without_touching_other_collection_content(tmp_path):
    store = FakeStore()
    sync, data = make_sync(tmp_path, store)
    file = data / "guide.txt"
    file.write_text("历史段落", encoding="utf-8")
    sync.run()
    store.rows["other"] = Document(page_content="外部内容", metadata={"source": "uploads/other.txt"})

    file.unlink()
    result = sync.run()
    assert result["deleted"] == 1
    assert set(store.rows) == {"other"}


def test_duplicate_chunks_have_distinct_stable_ids(tmp_path):
    store = FakeStore()
    sync, data = make_sync(tmp_path, store)
    file = data / "guide.txt"
    file.write_text("重复段落\n重复段落", encoding="utf-8")
    sync.run()
    assert len(store.rows) == 2
    assert len(set(store.rows)) == 2
    assert sync.run()["added"] == 0


def test_configured_file_types_limit_sync_scope(tmp_path):
    from rag.knowledge_sync import KnowledgeSync

    store = FakeStore()
    data = tmp_path / "data"
    data.mkdir()
    (data / "guide.txt").write_text("保留内容", encoding="utf-8")
    (data / "notes.pdf").write_bytes(b"not a valid PDF")
    sync = KnowledgeSync(store, LineSplitter(), data, tmp_path, allowed_types=("txt",))
    assert sync.run()["added"] == 1
    assert sync.run()["failed"] == 0


def test_legacy_chunks_migrate_once(tmp_path):
    store = FakeStore()
    sync, data = make_sync(tmp_path, store)
    file = data / "guide.txt"
    file.write_text("新的正文", encoding="utf-8")
    store.rows["legacy-id"] = Document(page_content="过时正文", metadata={"source": str(file)})

    result = sync.run()
    assert result["added"] == 1
    assert result["deleted"] == 1
    assert "legacy-id" not in store.rows
    assert sync.run()["added"] == 0


@pytest.mark.parametrize("legacy_source", [
    r"F:\PythonProject\Agent项目\data\guide.txt",
    "/app/data/guide.txt",
])
def test_legacy_source_from_another_os_is_reconciled(tmp_path, legacy_source):
    store = FakeStore()
    sync, data = make_sync(tmp_path, store)
    (data / "guide.txt").write_text("新正文", encoding="utf-8")
    store.rows["legacy-id"] = Document(page_content="旧正文", metadata={"source": legacy_source})
    result = sync.run()
    assert result["deleted"] == 1
    assert "legacy-id" not in store.rows


def test_second_sync_cannot_enter_while_index_lock_is_held(tmp_path):
    store = FakeStore()
    sync, data = make_sync(tmp_path, store)
    (data / "guide.txt").write_text("正文", encoding="utf-8")
    with FileLock(str(sync.lock_path), timeout=0):
        with pytest.raises(Timeout):
            sync.run()
    assert store.rows == {}


def test_failed_embedding_keeps_previous_chunks_for_retry(tmp_path):
    store = FakeStore()
    sync, data = make_sync(tmp_path, store)
    file = data / "guide.txt"
    file.write_text("旧正文", encoding="utf-8")
    sync.run()
    old_rows = store.rows.copy()
    file.write_text("新正文", encoding="utf-8")
    store.fail_add = True

    result = sync.run()
    assert result["failed"] == 1
    assert store.rows == old_rows
    store.fail_add = False
    assert sync.run()["added"] == 1


def test_failed_loader_keeps_previous_chunks(tmp_path):
    from rag.knowledge_sync import KnowledgeSync

    store = FakeStore()
    sync, data = make_sync(tmp_path, store)
    file = data / "guide.txt"
    file.write_text("旧正文", encoding="utf-8")
    sync.run()
    old_rows = store.rows.copy()

    def broken_loader(path):
        raise OSError("cannot read")

    broken = KnowledgeSync(store, LineSplitter(), data, tmp_path, load_file=broken_loader)
    assert broken.run()["failed"] == 1
    assert store.rows == old_rows


def test_partial_update_invalidates_cached_lexical_index_and_can_retry(tmp_path):
    store = FakeStore()
    invalidations = []
    sync, data = make_sync(tmp_path, store, invalidate=lambda: invalidations.append(1))
    file = data / "guide.txt"
    file.write_text("旧正文", encoding="utf-8")
    sync.run()
    file.write_text("新正文", encoding="utf-8")
    store.fail_delete = True

    assert sync.run()["failed"] == 1
    assert {doc.page_content for doc in store.rows.values()} == {"旧正文", "新正文"}
    assert len(invalidations) == 2
    store.fail_delete = False
    assert sync.run()["deleted"] == 1
    assert {doc.page_content for doc in store.rows.values()} == {"新正文"}


def test_vector_service_load_document_uses_incremental_sync(tmp_path):
    from rag.vector_store import VectorStoreService

    store = FakeStore()
    data = tmp_path / "data"
    data.mkdir()
    (data / "guide.txt").write_text("Redis OOM", encoding="utf-8")
    service = object.__new__(VectorStoreService)
    service.vector_store = store
    service.splitter = LineSplitter()
    assert service.load_document(data_dir=data, project_root=tmp_path)["added"] == 1
    assert service.load_document(data_dir=data, project_root=tmp_path)["added"] == 0


def test_real_chroma_persists_incremental_changes(tmp_path):
    from hashlib import md5
    from langchain_chroma import Chroma
    from langchain_core.embeddings import Embeddings

    class LocalEmbeddings(Embeddings):
        def embed_documents(self, texts):
            return [[float(byte) / 255 for byte in md5(text.encode()).digest()]
                    for text in texts]

        def embed_query(self, text):
            return self.embed_documents([text])[0]

    data = tmp_path / "data"
    data.mkdir()
    file = data / "guide.txt"
    file.write_text("保留内容\n过期内容", encoding="utf-8")
    db_path = str(tmp_path / "chroma")
    store = Chroma(collection_name="incremental_test", embedding_function=LocalEmbeddings(),
                   persist_directory=db_path)
    from rag.knowledge_sync import KnowledgeSync

    sync = KnowledgeSync(store, LineSplitter(), data, tmp_path)
    assert sync.run()["added"] == 2
    kept_id = next(chunk_id for chunk_id, doc in zip(store.get()["ids"], store.get()["documents"])
                   if doc == "保留内容")
    file.write_text("新增内容\n保留内容", encoding="utf-8")
    assert sync.run() == {"added": 1, "kept": 1, "deleted": 1, "failed": 0}
    reopened = Chroma(collection_name="incremental_test", embedding_function=LocalEmbeddings(),
                      persist_directory=db_path)
    rows = reopened.get()
    assert set(rows["documents"]) == {"新增内容", "保留内容"}
    assert kept_id in rows["ids"]
