"""Small MySQL catalog for local knowledge files and evaluation summaries."""

from datetime import datetime, timezone
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import DocumentRecord, EvaluationResult
from backend.models.session import utcnow


class DocumentCatalog:
    def __init__(self, db: Session):
        self.db = db

    def reconcile(self, documents: list[dict], *, indexed: bool) -> None:
        names = {document["name"] for document in documents}
        try:
            for row in self.db.scalars(select(DocumentRecord)).all():
                if row.name not in names:
                    self.db.delete(row)
            for document in documents:
                row = self.db.get(DocumentRecord, document["name"])
                if row is None:
                    row = DocumentRecord(name=document["name"])
                    self.db.add(row)
                stamp = datetime.fromisoformat(document["updated_at"])
                if stamp.tzinfo:
                    stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
                row.size_bytes = document["size_bytes"]
                row.updated_at = stamp
                row.index_status = "ready" if indexed else "pending"
                row.indexed_at = utcnow() if indexed else None
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise


class EvaluationCatalog:
    def __init__(self, db: Session):
        self.db = db

    def save(self, report: dict) -> str:
        summary = {key: report.get(key) for key in (
            "mode", "dataset", "dataset_fingerprint", "index_fingerprint",
            "model_name", "rag_mode", "rewrite_enabled",
            "selected_case_count", "retrieval_summary", "agent_summary", "estimated_usd",
        )}
        row = EvaluationResult(mode=report["mode"], dataset=report["dataset"],
                               model_name=report.get("model_name"),
                               summary_json=json.dumps(summary, ensure_ascii=False))
        try:
            self.db.add(row)
            self.db.commit()
            return row.id
        except Exception:
            self.db.rollback()
            raise
