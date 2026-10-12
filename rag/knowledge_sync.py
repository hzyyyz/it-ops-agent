"""Reconcile local knowledge files with their chunk records in Chroma."""

from collections import defaultdict
from hashlib import md5, sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from filelock import FileLock
from langchain_core.documents import Document

from utils.file_handler import pdf_loader, txt_loader
from utils.logger_handler import logger


def _load_file(path: Path) -> list[Document]:
    if path.suffix.lower() == ".txt":
        return txt_loader(str(path))
    if path.suffix.lower() == ".pdf":
        return pdf_loader(str(path))
    raise ValueError(f"Unsupported knowledge file type: {path.suffix}")


class KnowledgeSync:
    def __init__(self, vector_store, splitter, data_dir: Path, project_root: Path, *,
                 load_file: Callable[[Path], list[Document]] = _load_file,
                 invalidate: Callable[[], None] | None = None,
                 allowed_types: tuple[str, ...] = ("txt", "pdf"),
                 lock_path: Path | None = None):
        self.vector_store = vector_store
        self.splitter = splitter
        self.data_dir = Path(data_dir).resolve()
        self.project_root = Path(project_root).resolve()
        self.load_file = load_file
        self.invalidate = invalidate or (lambda: None)
        self.allowed_suffixes = frozenset(f".{kind.lower().lstrip('.')}" for kind in allowed_types)
        self.lock_path = Path(lock_path or self.project_root / "chroma_db" / ".knowledge-sync.lock")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

    def _source_key(self, source: str) -> str | None:
        if not source:
            return None
        path = Path(source)
        if not path.is_absolute():
            path = self.project_root / path
        path = path.resolve()
        if path.parent == self.data_dir and path.suffix.lower() in self.allowed_suffixes:
            return path.relative_to(self.project_root).as_posix()
        # Legacy loaders stored absolute paths. A persisted index may move
        # between Windows and Linux, where Path cannot parse the other OS.
        for foreign in (PureWindowsPath(source), PurePosixPath(source)):
            if (foreign.is_absolute() and foreign.parent.name == self.data_dir.name
                    and foreign.suffix.lower() in self.allowed_suffixes):
                return (self.data_dir / foreign.name).relative_to(self.project_root).as_posix()
        return None

    def _chunks(self, path: Path, source: str) -> dict[str, Document]:
        documents = self.splitter.split_documents(self.load_file(path))
        occurrences: dict[tuple[str, str], int] = defaultdict(int)
        chunks = {}
        for doc in documents:
            if not doc.page_content.strip():
                continue
            digest = md5(doc.page_content.encode("utf-8")).hexdigest()
            page = str(doc.metadata.get("page", ""))
            key = (digest, page)
            ordinal = occurrences[key]
            occurrences[key] += 1
            identity = sha256(f"{source}\0{page}\0{digest}\0{ordinal}".encode("utf-8")).hexdigest()
            chunk_id = f"kb:{identity}"
            metadata = {**doc.metadata, "source": source, "chunk_md5": digest,
                        "chunk_occurrence": ordinal}
            chunks[chunk_id] = Document(page_content=doc.page_content, metadata=metadata)
        return chunks

    def run(self) -> dict[str, int]:
        """Add changed chunks, retain identical IDs, and remove stale local chunks."""
        with FileLock(str(self.lock_path), timeout=0):
            return self._run_locked()

    def _run_locked(self) -> dict[str, int]:
        if not self.data_dir.is_dir():
            raise FileNotFoundError(f"Knowledge directory does not exist: {self.data_dir}")
        rows = self.vector_store.get(include=["documents", "metadatas"])
        existing: dict[str, dict[str, str]] = defaultdict(dict)
        orphaned_managed_ids = []
        for chunk_id, content, metadata in zip(rows["ids"], rows["documents"], rows["metadatas"]):
            source = self._source_key((metadata or {}).get("source", ""))
            if source:
                existing[source][chunk_id] = content
            elif chunk_id.startswith("kb:"):
                orphaned_managed_ids.append(chunk_id)

        result = {"added": 0, "kept": 0, "deleted": 0, "failed": 0}
        current_sources = set()
        files = sorted(path for path in self.data_dir.iterdir()
                       if path.is_file() and not path.is_symlink()
                       and path.suffix.lower() in self.allowed_suffixes)
        for path in files:
            source = self._source_key(str(path))
            if source is None:
                result["failed"] += 1
                logger.error("[知识库同步] 拒绝越界文件：%s", path.name)
                continue
            current_sources.add(source)
            try:
                wanted = self._chunks(path, source)
                previous = existing.get(source, {})
                kept = {chunk_id for chunk_id, doc in wanted.items()
                        if chunk_id in previous and previous[chunk_id] == doc.page_content}
                to_add = {chunk_id: doc for chunk_id, doc in wanted.items() if chunk_id not in kept}
                to_delete = [chunk_id for chunk_id in previous if chunk_id not in kept]
                if to_add or to_delete:
                    try:
                        if to_add:
                            self.vector_store.add_documents(list(to_add.values()), ids=list(to_add))
                        if to_delete:
                            self.vector_store.delete(ids=to_delete)
                    finally:
                        # A vector operation may partially succeed before raising.
                        self.invalidate()
                result["added"] += len(to_add)
                result["kept"] += len(kept)
                result["deleted"] += len(to_delete)
            except Exception as exc:
                result["failed"] += 1
                logger.error("[知识库同步] %s 同步失败：%s", source, type(exc).__name__, exc_info=True)

        for source in existing.keys() - current_sources:
            try:
                ids = list(existing[source])
                try:
                    self.vector_store.delete(ids=ids)
                finally:
                    self.invalidate()
                result["deleted"] += len(ids)
            except Exception as exc:
                result["failed"] += 1
                logger.error("[知识库同步] %s 删除失败：%s", source, type(exc).__name__, exc_info=True)
        if orphaned_managed_ids:
            try:
                try:
                    self.vector_store.delete(ids=orphaned_managed_ids)
                finally:
                    self.invalidate()
                result["deleted"] += len(orphaned_managed_ids)
            except Exception as exc:
                result["failed"] += 1
                logger.error("[知识库同步] 清理无来源片段失败：%s", type(exc).__name__, exc_info=True)
        return result
