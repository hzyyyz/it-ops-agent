from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_document_catalog_reconciles_file_metadata_and_deletion(tmp_path):
    from backend.database import Base
    from backend.models import DocumentRecord
    from backend.services.metadata_catalog import DocumentCatalog

    engine = create_engine(f"sqlite:///{tmp_path / 'catalog.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        catalog = DocumentCatalog(db)
        catalog.reconcile([{"name": "guide.txt", "size_bytes": 5,
                            "updated_at": "2026-10-11T12:00:00+00:00"}], indexed=True)
        assert db.get(DocumentRecord, "guide.txt").index_status == "ready"
        catalog.reconcile([{"name": "guide.txt", "size_bytes": 7,
                            "updated_at": "2026-10-12T12:00:00+00:00"}], indexed=False)
        assert db.get(DocumentRecord, "guide.txt").index_status == "pending"
        catalog.reconcile([], indexed=True)
        assert db.get(DocumentRecord, "guide.txt") is None


def test_evaluation_summary_is_persisted_without_answers(tmp_path):
    from backend.database import Base
    from backend.models import EvaluationResult
    from backend.services.metadata_catalog import EvaluationCatalog
    import json

    engine = create_engine(f"sqlite:///{tmp_path / 'eval.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run_id = EvaluationCatalog(db).save({
            "mode": "agent", "dataset": "tests/eval_dataset.json", "model_name": "deepseek",
            "dataset_fingerprint": "dataset-hash", "index_fingerprint": "index-hash",
            "agent_summary": {"task_success_proxy_rate": 0.8},
            "retrieval_summary": {}, "agent_results": [{"answer": "private content"}],
        })
        row = db.get(EvaluationResult, run_id)
        assert row.mode == "agent"
        assert json.loads(row.summary_json)["agent_summary"]["task_success_proxy_rate"] == 0.8
        assert json.loads(row.summary_json)["index_fingerprint"] == "index-hash"
        assert "private content" not in row.summary_json


def test_runner_can_persist_a_completed_report(monkeypatch, tmp_path):
    from backend.database import Base
    from backend import database
    from backend.models import EvaluationResult
    from evaluation import runner

    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "get_engine", lambda: engine)
    run_id = runner.save_report_to_db({
        "mode": "retrieval", "dataset": "tests/eval_dataset.json",
        "retrieval_summary": {"rag_recall_at_3": 0.7}, "agent_summary": {},
    })
    with Session(engine) as db:
        assert db.get(EvaluationResult, run_id) is not None
