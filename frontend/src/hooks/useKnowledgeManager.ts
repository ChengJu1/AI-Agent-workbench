import { useEffect, useRef, useState } from "react";
import {
  createKnowledgeBase, deleteKnowledgeBase, deleteKnowledgeDocument, fetchKnowledgeBases,
  evaluateKnowledge, fetchKnowledgeChunks, fetchKnowledgeDocuments, searchKnowledge, uploadKnowledgeDocument,
} from "../api/knowledge";
import { validateKnowledgeFile } from "../lib/knowledge";
import type {
  KnowledgeBaseInfo, KnowledgeChunkPage, KnowledgeDocumentInfo, KnowledgeSearchResult, RetrievalSuite,
} from "../types";

type UploadState = { name: string; status: "waiting" | "uploading" | "ready" | "failed"; message: string };
const errorText = (error: unknown) => error instanceof Error ? error.message : "操作失败，请重试。";

export function useKnowledgeManager() {
  const [bases, setBases] = useState<KnowledgeBaseInfo[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [documents, setDocuments] = useState<KnowledgeDocumentInfo[]>([]);
  const [loadingBases, setLoadingBases] = useState(true);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [operation, setOperation] = useState("");
  const [error, setError] = useState("");
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [searchResult, setSearchResult] = useState<KnowledgeSearchResult | null>(null);
  const [preview, setPreview] = useState<{ document: KnowledgeDocumentInfo; page: KnowledgeChunkPage } | null>(null);
  const running = useRef(false);
  const mounted = useRef(true);
  const active = useRef<AbortController | null>(null);
  const busy = loadingBases || loadingDocuments || Boolean(operation);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void fetchKnowledgeBases(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setBases(result);
      setSelectedId(result[0]?.id ?? "");
    }).catch((error) => {
      if (!controller.signal.aborted) setError(errorText(error));
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingBases(false);
    });
    return () => { mounted.current = false; controller.abort(); active.current?.abort(); };
  }, []);

  useEffect(() => {
    setDocuments([]);
    setPreview(null);
    setSearchResult(null);
    setUploads([]);
    if (!selectedId) { setLoadingDocuments(false); return; }
    const controller = new AbortController();
    setLoadingDocuments(true);
    void fetchKnowledgeDocuments(selectedId, controller.signal).then((result) => {
      if (!controller.signal.aborted) setDocuments(result);
    }).catch((error) => {
      if (!controller.signal.aborted) setError(errorText(error));
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingDocuments(false);
    });
    return () => controller.abort();
  }, [selectedId]);

  async function run<T>(name: string, action: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
    if (running.current || busy) return;
    running.current = true;
    const controller = new AbortController();
    active.current = controller;
    setOperation(name);
    setError("");
    try {
      return await action(controller.signal);
    } catch (error) {
      if (!controller.signal.aborted) setError(errorText(error));
    } finally {
      running.current = false;
      if (mounted.current) setOperation("");
    }
  }

  async function refresh(signal: AbortSignal) {
    const [nextBases, nextDocuments] = await Promise.all([
      fetchKnowledgeBases(signal), fetchKnowledgeDocuments(selectedId, signal),
    ]);
    if (signal.aborted) return;
    setBases(nextBases);
    setDocuments(nextDocuments);
  }

  function selectBase(id: string) {
    if (busy || running.current) return;
    setError("");
    setSelectedId(id);
  }

  function createBase(name: string, description: string) {
    return run("creating", async (signal) => {
      const result = await createKnowledgeBase(name.trim(), description.trim(), signal);
      if (signal.aborted) return;
      setBases((current) => [...current, result]);
      setSelectedId(result.id);
      return true;
    });
  }

  function removeBase(id: string) {
    return run("deleting", async (signal) => {
      await deleteKnowledgeBase(id, signal);
      if (signal.aborted) return;
      const remaining = bases.filter((base) => base.id !== id);
      setBases(remaining);
      setSelectedId(remaining[0]?.id ?? "");
      return true;
    });
  }

  function uploadFiles(files: File[]) {
    if (!selectedId || !files.length) return;
    return run("uploading", async (signal) => {
      setPreview(null);
      setSearchResult(null);
      setUploads(files.map((file) => ({ name: file.name, status: "waiting", message: "等待上传" })));
      function update(index: number, status: UploadState["status"], message: string) {
        if (!signal.aborted) setUploads((current) => current.map((item, position) => position === index
          ? { ...item, status, message } : item));
      }
      for (const [index, file] of files.entries()) {
        if (signal.aborted) return;
        update(index, "uploading", "正在解析、分段并建立索引…");
        try {
          validateKnowledgeFile(file);
          const result = await uploadKnowledgeDocument(selectedId, file, signal);
          update(index, "ready", result.unchanged ? "内容未变化，保留现有版本"
            : `${result.created ? "已入库" : "已更新"} · v${result.document.version} · ${result.document.chunk_count} 个片段`);
        } catch (error) {
          if (signal.aborted) return;
          update(index, "failed", errorText(error));
        }
      }
      await refresh(signal);
    });
  }

  function removeDocument(id: string) {
    return run("deleting", async (signal) => {
      await deleteKnowledgeDocument(selectedId, id, signal);
      await refresh(signal);
      if (signal.aborted) return;
      setPreview(null);
      setSearchResult(null);
      setUploads([]);
      return true;
    });
  }

  function search(query: string) {
    if (!selectedId || !query.trim()) return;
    return run("searching", async (signal) => {
      setSearchResult(null);
      const result = await searchKnowledge(selectedId, query.trim(), signal);
      if (signal.aborted) return;
      setPreview(null);
      setSearchResult(result);
    });
  }

  function previewDocument(document: KnowledgeDocumentInfo) {
    return run("previewing", async (signal) => {
      const page = await fetchKnowledgeChunks(selectedId, document.id, 0, signal);
      if (signal.aborted) return;
      setSearchResult(null);
      setPreview({ document, page });
    });
  }

  function moreChunks() {
    if (!preview) return;
    return run("previewing", async (signal) => {
      const page = await fetchKnowledgeChunks(selectedId, preview.document.id, preview.page.items.length, signal);
      if (signal.aborted) return;
      setPreview({ document: preview.document, page: { ...page, items: [...preview.page.items, ...page.items] } });
    });
  }

  function evaluate(suite: RetrievalSuite) {
    if (!selectedId) return Promise.resolve(undefined);
    return run("evaluating", (signal) => evaluateKnowledge(selectedId, suite, signal));
  }

  return {
    bases, selectedId, selectedBase: bases.find((base) => base.id === selectedId), documents,
    busy, operation, loadingBases, loadingDocuments, error, uploads, searchResult, preview,
    selectBase, createBase, removeBase, uploadFiles, removeDocument, search, previewDocument, moreChunks,
    evaluate,
  };
}
