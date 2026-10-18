"""知识库管理、文档上传、分段预览与本地关键词检索。"""
from fastapi import APIRouter, Depends, Query, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_services
from app.models.knowledge import (
    CreateKnowledgeBaseRequest, DocumentUploadResult, KnowledgeBaseInfo,
    KnowledgeChunkPage, KnowledgeDocumentInfo, KnowledgeSearchResult, SearchKnowledgeRequest,
)
from app.services.knowledge_service import MAX_DOCUMENT_BYTES


router = APIRouter(prefix="/api/knowledge-bases")


@router.get("", response_model=list[KnowledgeBaseInfo])
def list_bases(services=Depends(get_services)):
    return services.knowledge.store.list_bases()


@router.post("", response_model=KnowledgeBaseInfo, status_code=201)
def create_base(request: CreateKnowledgeBaseRequest, services=Depends(get_services)):
    return services.knowledge.store.create_base(request.name, request.description)


@router.get("/{base_id}", response_model=KnowledgeBaseInfo)
def get_base(base_id: str, services=Depends(get_services)):
    return services.knowledge.require_base(base_id)


@router.delete("/{base_id}", status_code=204)
def delete_base(base_id: str, services=Depends(get_services)):
    services.knowledge.delete_base(base_id)


@router.get("/{base_id}/documents", response_model=list[KnowledgeDocumentInfo])
def list_documents(base_id: str, services=Depends(get_services)):
    services.knowledge.require_base(base_id)
    return services.knowledge.store.list_documents(base_id)


@router.post("/{base_id}/documents", response_model=DocumentUploadResult)
async def upload_document(base_id: str, file: UploadFile, response: Response,
                          services=Depends(get_services)):
    try:
        raw = await file.read(MAX_DOCUMENT_BYTES + 1)
        result = await run_in_threadpool(services.knowledge.ingest, base_id, file.filename, raw)
        response.status_code = 201 if result["created"] else 200
        return result
    finally:
        await file.close()


@router.delete("/{base_id}/documents/{document_id}", status_code=204)
def delete_document(base_id: str, document_id: str, services=Depends(get_services)):
    services.knowledge.delete_document(base_id, document_id)


@router.get("/{base_id}/documents/{document_id}/chunks", response_model=KnowledgeChunkPage)
def get_chunks(base_id: str, document_id: str, offset: int = Query(default=0, ge=0, le=1000000),
               limit: int = Query(default=20, ge=1, le=100), services=Depends(get_services)):
    services.knowledge.require_document(base_id, document_id)
    return services.knowledge.store.get_chunks(document_id, offset, limit)


@router.post("/{base_id}/search", response_model=KnowledgeSearchResult)
def search(base_id: str, request: SearchKnowledgeRequest, services=Depends(get_services)):
    return services.knowledge.search(base_id, request.query, request.limit)
