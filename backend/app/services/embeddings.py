"""本地嵌入与重排序模型：只读取已下载到模型目录的文件，运行时从不联网下载。"""
import logging
import math
from pathlib import Path
from threading import Lock

import numpy as np


logger = logging.getLogger(__name__)
BATCH_SIZE = 16
RERANK_MAX_CHARS = 1000


class EmbeddingUnavailable(Exception):
    pass


class _LocalModel:
    KIND = "模型"

    def __init__(self, model_name, directory):
        self.model_name, self.directory = model_name, Path(directory)
        self._model, self._failure, self._lock = None, None, Lock()

    def _create(self):
        raise NotImplementedError

    def _load(self):
        with self._lock:
            if self._model is None and self._failure is None:
                if not self.directory.is_dir():
                    # 没下载模型时不要让 fastembed 去创建目录。
                    self._failure = "model directory missing"
                    return None
                try:
                    self._model = self._create()
                except Exception as error:
                    self._failure = type(error).__name__
                    logger.warning("本地%s不可用: model=%s error=%s", self.KIND, self.model_name, self._failure)
            return self._model

    def available(self):
        return self._load() is not None

    def _require(self):
        model = self._load()
        if model is None:
            raise EmbeddingUnavailable(self._failure or "unavailable")
        return model


class LocalEmbedder(_LocalModel):
    KIND = "嵌入模型"

    def __init__(self, model_name, directory):
        super().__init__(model_name, directory)
        # E5 models are trained with these prefixes; queries and passages are embedded differently.
        e5 = "e5" in model_name.lower()
        self.query_prefix, self.passage_prefix = ("query: ", "passage: ") if e5 else ("", "")

    def _create(self):
        from fastembed import TextEmbedding
        return TextEmbedding(self.model_name, cache_dir=str(self.directory), local_files_only=True)

    def _embed(self, texts):
        vectors = np.asarray(list(self._require().embed(texts, batch_size=BATCH_SIZE)), dtype=np.float32)
        return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)

    def passages(self, texts):
        return self._embed([self.passage_prefix + text for text in texts])

    def query(self, text):
        return self._embed([self.query_prefix + text])[0]


class LocalReranker(_LocalModel):
    """交叉编码器：把查询和候选原文放在一起打分，输出 0–1 的相关度。"""
    KIND = "重排序模型"

    def _create(self):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        return TextCrossEncoder(self.model_name, cache_dir=str(self.directory), local_files_only=True)

    def scores(self, query, texts):
        # bge-m3 一次可读 8192 个 token，整段长文在 CPU 上每组要数秒；只看开头部分打分，返回的原文不受影响。
        texts = [text[:RERANK_MAX_CHARS] for text in texts]
        logits = self._require().rerank(query, texts, batch_size=BATCH_SIZE)
        return [1 / (1 + math.exp(-float(logit))) for logit in logits]
