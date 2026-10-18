"""校验上传内容，组织文档分段、版本替换及检索。"""
import hashlib
from pathlib import PurePosixPath

from app.errors import ServiceError
from app.services.document_indexing import INDEXING_VERSION, index_document, search_expression


MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
ALLOWED_EXTENSIONS = {".md", ".markdown", ".txt"}


class KnowledgeService:
    def __init__(self, store):
        self.store = store

    def require_base(self, base_id):
        base = self.store.get_base(base_id)
        if base is None:
            raise ServiceError("知识库不存在。", 404)
        return base

    def require_document(self, base_id, document_id):
        self.require_base(base_id)
        document = self.store.get_document(base_id, document_id)
        if document is None:
            raise ServiceError("文档不存在。", 404)
        return document

    def ingest(self, base_id, filename, raw):
        self.require_base(base_id)
        filename = (filename or "").strip()
        if (not filename or len(filename) > 200 or "/" in filename or "\\" in filename
                or any(ord(char) < 32 or ord(char) == 127 for char in filename)):
            raise ServiceError("文件名不正确，请使用不含路径的文件名。", 422)
        if PurePosixPath(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ServiceError("目前支持 Markdown 和 TXT 文档。", 415)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ServiceError("单个文档不能超过 2 MB。", 413)
        try:
            content = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError as error:
            raise ServiceError("无法读取文档，请使用 UTF-8 编码的文本文件。", 422) from error
        if not content.strip():
            raise ServiceError("文档内容为空。", 422)
        if any(ord(char) < 32 and char not in "\n\t" for char in content):
            raise ServiceError("文档包含非文本内容，请上传 UTF-8 文本文件。", 422)
        index = index_document(content, filename)
        saved = self.store.save_document(
            base_id, filename, content, hashlib.sha256(raw).hexdigest(), len(raw), index.chunks,
            INDEXING_VERSION, index.strategy,
        )
        if saved is None:
            raise ServiceError("知识库不存在。", 404)
        return {
            "document": self.require_document(base_id, saved["id"]),
            "created": saved["created"], "unchanged": saved["unchanged"],
        }

    def reindex_outdated(self):
        updated = 0
        for document in self.store.outdated_documents(INDEXING_VERSION):
            index = index_document(document["content"], document["filename"])
            updated += self.store.reindex_document(
                document["id"], document["content_hash"], index.chunks, INDEXING_VERSION, index.strategy,
            )
        return updated

    def delete_base(self, base_id):
        if not self.store.delete_base(base_id):
            raise ServiceError("知识库不存在。", 404)

    def delete_document(self, base_id, document_id):
        self.require_base(base_id)
        if not self.store.delete_document(base_id, document_id):
            raise ServiceError("文档不存在。", 404)

    def search(self, base_id, query, limit):
        self.require_base(base_id)
        return {"query": query, "method": "keyword", **self.store.search(
            base_id, search_expression(query), limit
        )}
