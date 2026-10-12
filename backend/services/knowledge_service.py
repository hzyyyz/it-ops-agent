"""Local single-user knowledge file management."""

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import tempfile
from typing import Callable


class KnowledgeInputError(ValueError):
    pass


class KnowledgeTooLargeError(KnowledgeInputError):
    pass


class KnowledgeIndexError(RuntimeError):
    pass


class KnowledgeService:
    def __init__(self, data_dir: Path, sync: Callable[[], dict[str, int]], *,
                 max_bytes: int = 10 * 1024 * 1024):
        self.data_dir = Path(data_dir).resolve()
        self.sync = sync
        self.max_bytes = max_bytes

    def _path(self, name: str) -> Path:
        if (not name or len(name) > 128 or name in (".", "..")
                or name != name.strip() or name.startswith(".")
                or any(char in name for char in '/\\<>:"|?*')
                or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", name)
                or any(ord(char) < 32 for char in name)
                or Path(name).suffix.lower() not in (".txt", ".pdf")):
            raise KnowledgeInputError("只支持 data 目录顶层的 .txt 或 .pdf 文件，文件名不能包含路径。")
        return self.data_dir / name

    @staticmethod
    def _summary(path: Path) -> dict:
        stat = path.stat()
        return {"name": path.name, "size_bytes": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}

    def list_documents(self) -> list[dict]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return [self._summary(path) for path in sorted(self.data_dir.iterdir())
                if path.is_file() and not path.is_symlink() and path.suffix.lower() in (".txt", ".pdf")]

    def _sync(self) -> dict[str, int]:
        try:
            result = self.sync()
        except Exception as exc:
            raise KnowledgeIndexError("知识库索引更新失败，请检查服务日志后重试同步。") from exc
        if result.get("failed", 0):
            raise KnowledgeIndexError("有文档未能完成索引，请检查服务日志后重试同步。")
        return result

    def upload(self, name: str, content: bytes) -> dict:
        path = self._path(name)
        if not content:
            raise KnowledgeInputError("文件不能为空。")
        if len(content) > self.max_bytes:
            raise KnowledgeTooLargeError("文件超过大小限制。")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.data_dir, prefix=".upload-", suffix=".tmp",
                                             delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(content)
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        self._sync()
        return self._summary(path)

    def delete(self, name: str) -> None:
        path = self._path(name)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(name)
        path.unlink()
        self._sync()

    def synchronize(self) -> dict[str, int]:
        return self._sync()
