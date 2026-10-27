"""校验上传内容，组织文档分段、版本替换及检索。"""
import hashlib
import logging
from pathlib import PurePosixPath
from threading import Lock, Thread

from app.errors import ServiceError
from app.services.embeddings import EmbeddingUnavailable
from app.services.retrieval_postprocessing import relevance_window
from app.platform.files import SCANNED_PDF, parse_document
from app.services.document_indexing import INDEXING_VERSION, index_document, search_expression


MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
# PDF/DOCX 在沙箱中提取文字后按纯文本保存和切分。
CONVERTED_EXTENSIONS = {".pdf", ".docx"}
# 检索结果直接进入模型上下文（不转存），整次返回的原文总量有上限。
MAX_RESULT_CHARS = 10000
MAX_READ_LINES = 200
MAX_READ_CHARS = 6000
VECTOR_BATCH = 64
LOW_RELEVANCE_NOTICE = ("这些片段与问题的相关度很低，知识库里可能没有答案。"
                        "请先核对片段是否真的回答了问题；没有回答时说明未找到相关资料，不要据此作答，也不要引用这些片段。")

logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(self, store, embedder=None, reranker=None):
        self.store, self.embedder, self.reranker = store, embedder, reranker
        self._indexing, self._pending, self._guard = False, False, Lock()

    def query_vector(self, query):
        """返回 (查询向量, 状态)；模型不可用时向量为 None，检索退回纯关键词。"""
        if self.embedder is None:
            return None, "disabled"
        try:
            return self.embedder.query(query), "ok"
        except EmbeddingUnavailable:
            return None, "unavailable"

    def query_reranker(self, query):
        """返回 (重排序函数, 状态)；模型不可用时不重排序。"""
        if self.reranker is None:
            return None, "disabled"
        if not self.reranker.available():
            return None, "unavailable"
        return (lambda groups: self.reranker.scores(
            query, [relevance_window(query, group["section"], group["content"]) for group in groups])), "ok"

    def index_vectors(self):
        """为还没有向量的片段生成向量，返回新写入的数量。"""
        if self.embedder is None or not self.embedder.available():
            return 0
        written = 0
        while chunks := self.store.chunks_without_vectors(self.embedder.model_name, VECTOR_BATCH):
            vectors = self.embedder.passages([f"{chunk['section']}\n{chunk['content']}" for chunk in chunks])
            self.store.save_vectors(self.embedder.model_name, [chunk["id"] for chunk in chunks], vectors)
            written += len(chunks)
        return written

    def schedule_vectors(self):
        """在后台补齐向量；运行中再次调用会在本次结束后再补一轮。"""
        if self.embedder is None:
            return
        with self._guard:
            if self._indexing:
                self._pending = True
                return
            self._indexing = True
        Thread(target=self._vector_worker, name="knowledge-vectors", daemon=True).start()

    def _vector_worker(self):
        while True:
            try:
                written = self.index_vectors()
                if written:
                    logger.info("知识库向量已补齐: chunks=%s", written)
            except Exception:
                logger.exception("知识库向量生成失败")
            with self._guard:
                if not self._pending:
                    self._indexing = False
                    return
                self._pending = False

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

    def require_document_version(self, base_id, document_id, version):
        document = self.store.get_document_version(base_id, document_id, version)
        if document is None:
            raise ServiceError("该版本的完整原文尚未存档，可继续查看当轮引用片段。", 404)
        return document

    def ingest(self, base_id, filename, raw):
        self.require_base(base_id)
        filename = (filename or "").strip()
        if (not filename or len(filename) > 200 or "/" in filename or "\\" in filename
                or any(ord(char) < 32 or ord(char) == 127 for char in filename)):
            raise ServiceError("文件名不正确，请使用不含路径的文件名。", 422)
        suffix = PurePosixPath(filename).suffix.lower()
        if suffix not in TEXT_EXTENSIONS | CONVERTED_EXTENSIONS:
            raise ServiceError("目前支持 Markdown、TXT、PDF 和 DOCX 文档。", 415)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ServiceError("单个文档不能超过 2 MB。", 413)
        if not raw:
            raise ServiceError("文档内容为空。", 422)
        if suffix in CONVERTED_EXTENSIONS:
            text = parse_document(suffix, raw, complete=True)
            if text.startswith(SCANNED_PDF):
                raise ServiceError("这是扫描版 PDF，没有可检索的文字。请先做 OCR，或上传含文字层的版本。", 422)
            # 提取结果里的分页符等控制字符换成换行，其余不可见字符去掉。
            text = "".join("\n" if char in "\f\v" else char for char in text
                           if ord(char) >= 32 or char in "\n\t\f\v\r")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise ServiceError("无法读取文档，请使用 UTF-8 编码的文本文件。", 422) from error
        content = text.replace("\r\n", "\n").replace("\r", "\n")
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
        self.schedule_vectors()
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

    def read(self, base_id, document_id, start_line=1, end_line=None):
        """当前版本中的一段原文；返回准确的字符区间，供引用核对。"""
        self.require_base(base_id)
        document = self.store.get_document_content(base_id, document_id)
        if document is None:
            raise ServiceError("文档不存在。document_id 请使用本知识库 search_knowledge 结果中的值。", 404)
        text = document["content"]
        starts = [0] + [index + 1 for index, char in enumerate(text) if char == "\n"]
        total = len(starts) if not text.endswith("\n") else len(starts) - 1
        if start_line > total:
            raise ServiceError(f"起始行超出文档长度（共 {total} 行）。", 422)
        end = min(end_line or start_line + MAX_READ_LINES - 1, start_line + MAX_READ_LINES - 1, total)
        if end < start_line:
            raise ServiceError("结束行不能小于起始行。", 422)
        start_offset = starts[start_line - 1]
        end_offset = starts[end] - 1 if end < len(starts) else len(text)
        if end_offset - start_offset > MAX_READ_CHARS:
            # 按字数截到最后一个完整行；单行过长时直接截断该行。
            cut = text.rfind("\n", start_offset, start_offset + MAX_READ_CHARS)
            end_offset = cut if cut > start_offset else start_offset + MAX_READ_CHARS
            end = text.count("\n", 0, end_offset - 1) + 1
        return {"document_id": document["id"], "document_version": document["version"], "filename": document["filename"],
                "start_line": start_line, "end_line": end, "total_lines": total,
                "start_offset": start_offset, "end_offset": end_offset, "content": text[start_offset:end_offset],
                "next_start_line": end + 1 if end < total else None}

    def search(self, base_id, query, limit):
        self.require_base(base_id)
        vector, status = self.query_vector(query)
        model = self.embedder.model_name if vector is not None else None
        rerank, rerank_status = self.query_reranker(query)
        result = self.store.search(base_id, search_expression(query), limit, vector, model, rerank)
        result["diagnostics"]["vector_status"], result["diagnostics"]["rerank_status"] = status, rerank_status
        kept, total = [], 0
        for match in result["matches"]:
            if kept and total + len(match["content"]) > MAX_RESULT_CHARS:
                break
            kept.append(match)
            total += len(match["content"])
        result["diagnostics"]["omitted_for_length"] = len(result["matches"]) - len(kept)
        notice = LOW_RELEVANCE_NOTICE if kept and result["diagnostics"].get("low_relevance") else None
        return {"query": query, "method": "hybrid" if vector is not None else "keyword", "notice": notice,
                **result, "matches": kept}
