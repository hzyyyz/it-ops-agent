"""Local knowledge management API used by the simple web UI."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.metadata_catalog import DocumentCatalog
from backend.services.knowledge_service import (
    KnowledgeIndexError, KnowledgeInputError, KnowledgeService, KnowledgeTooLargeError,
)
from utils.config_handler import chroma_conf
from utils.path_tool import get_abs_path


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def get_knowledge_service() -> KnowledgeService:
    def sync():
        from agent.tools.agent_tools import rag

        return rag.sync_knowledge()

    return KnowledgeService(Path(get_abs_path(chroma_conf["data_path"])), sync)


Service = Annotated[KnowledgeService, Depends(get_knowledge_service)]


def get_document_catalog(db: Annotated[Session, Depends(get_db)]) -> DocumentCatalog:
    return DocumentCatalog(db)


Catalog = Annotated[DocumentCatalog, Depends(get_document_catalog)]


def _record_documents(service: KnowledgeService, catalog: DocumentCatalog, *, indexed: bool) -> None:
    catalog.reconcile(service.list_documents(), indexed=indexed)


def _raise_http(exc: Exception):
    if isinstance(exc, KnowledgeTooLargeError):
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    if isinstance(exc, KnowledgeInputError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, KnowledgeIndexError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise exc


@router.get("")
def list_documents(service: Service):
    return service.list_documents()


@router.post("/upload")
async def upload_multipart(service: Service, catalog: Catalog, file: UploadFile = File(...)):
    content = await file.read(service.max_bytes + 1)
    try:
        result = await run_in_threadpool(service.upload, file.filename or "", content)
    except (KnowledgeInputError, KnowledgeIndexError) as exc:
        if isinstance(exc, KnowledgeIndexError):
            await run_in_threadpool(_record_documents, service, catalog, indexed=False)
        _raise_http(exc)
    await run_in_threadpool(_record_documents, service, catalog, indexed=True)
    return result


@router.put("/{name}")
async def upload_document(name: str, request: Request, service: Service, catalog: Catalog):
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > service.max_bytes:
            raise HTTPException(status_code=413, detail="文件超过大小限制。")
        chunks.append(chunk)
    try:
        result = await run_in_threadpool(service.upload, name, b"".join(chunks))
    except (KnowledgeInputError, KnowledgeIndexError) as exc:
        if isinstance(exc, KnowledgeIndexError):
            await run_in_threadpool(_record_documents, service, catalog, indexed=False)
        _raise_http(exc)
    await run_in_threadpool(_record_documents, service, catalog, indexed=True)
    return result


@router.delete("/{name}", status_code=204)
def delete_document(name: str, service: Service, catalog: Catalog):
    try:
        service.delete(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文档不存在。") from exc
    except (KnowledgeInputError, KnowledgeIndexError) as exc:
        if isinstance(exc, KnowledgeIndexError):
            _record_documents(service, catalog, indexed=False)
        _raise_http(exc)
    _record_documents(service, catalog, indexed=True)
    return Response(status_code=204)


@router.post("/sync")
def synchronize_documents(service: Service, catalog: Catalog):
    try:
        result = service.synchronize()
    except KnowledgeIndexError as exc:
        _record_documents(service, catalog, indexed=False)
        _raise_http(exc)
    _record_documents(service, catalog, indexed=True)
    return result
