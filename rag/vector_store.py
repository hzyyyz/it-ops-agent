"""Chroma setup and the local knowledge-base synchronization entry point."""

from pathlib import Path

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

from model.factory import embed_model
from rag.knowledge_sync import KnowledgeSync
from utils.config_handler import chroma_conf
from utils.path_tool import get_abs_path, get_project_root


class VectorStoreService:
    def __init__(self):
        self.vector_store = Chroma(
            collection_name=chroma_conf["collection_name"],
            embedding_function=embed_model,
            persist_directory=chroma_conf["persist_directory"],
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf["chunk_size"],
            chunk_overlap=chroma_conf["chunk_overlap"],
            separators=chroma_conf["separators"],
            length_function=len,
        )

    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": chroma_conf["k"]})

    def load_document(self, *, data_dir: Path | None = None,
                      project_root: Path | None = None, invalidate=None) -> dict[str, int]:
        """Reconcile local txt/pdf files; return added/kept/deleted/failed counts."""
        sync = KnowledgeSync(
            self.vector_store, self.splitter,
            data_dir or Path(get_abs_path(chroma_conf["data_path"])),
            project_root or Path(get_project_root()),
            invalidate=invalidate,
            allowed_types=tuple(chroma_conf["allow_knowledge_file_type"]),
            lock_path=(Path(project_root or get_project_root()) / chroma_conf["persist_directory"]
                       / ".knowledge-sync.lock"),
        )
        return sync.run()


if __name__ == "__main__":
    summary = VectorStoreService().load_document()
    print(f"知识库同步完成：新增 {summary['added']}，保留 {summary['kept']}，"
          f"删除 {summary['deleted']}，失败 {summary['failed']}")
    if summary["failed"]:
        raise SystemExit(1)
