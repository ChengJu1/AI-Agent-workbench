import type {
  DocumentUploadResult, KnowledgeBaseInfo, KnowledgeChunkPage,
  KnowledgeDocumentInfo, KnowledgeDocumentVersion, KnowledgeSearchResult,
  RetrievalReport, RetrievalSuite,
} from "../types";
import { jsonBody, request, requestJson } from "./http";

const basePath = (id: string) => `/api/knowledge-bases/${encodeURIComponent(id)}`;

export function fetchKnowledgeBases(signal?: AbortSignal) {
  return requestJson<KnowledgeBaseInfo[]>("/api/knowledge-bases", { signal });
}

const agentKnowledgePath = (id: string) => `/api/agents/${encodeURIComponent(id)}/knowledge-bases`;

export function fetchAgentKnowledgeBases(agentId: string, signal?: AbortSignal) {
  return requestJson<KnowledgeBaseInfo[]>(agentKnowledgePath(agentId), { signal });
}

export function bindAgentKnowledgeBases(agentId: string, ids: string[], signal?: AbortSignal) {
  return requestJson<KnowledgeBaseInfo[]>(agentKnowledgePath(agentId), {
    ...jsonBody({ knowledge_base_ids: ids }), method: "PUT", signal,
  });
}

export function createKnowledgeBase(name: string, description: string, signal?: AbortSignal) {
  return requestJson<KnowledgeBaseInfo>("/api/knowledge-bases", {
    ...jsonBody({ name, description }), signal,
  });
}

export async function deleteKnowledgeBase(id: string, signal?: AbortSignal) {
  await request(basePath(id), { method: "DELETE", signal });
}

export function fetchKnowledgeDocuments(id: string, signal?: AbortSignal) {
  return requestJson<KnowledgeDocumentInfo[]>(`${basePath(id)}/documents`, { signal });
}

export function fetchDocumentVersion(source: { knowledge_base_id: string; document_id: string; document_version: number }, signal?: AbortSignal) {
  return requestJson<KnowledgeDocumentVersion>(
    `${basePath(source.knowledge_base_id)}/documents/${encodeURIComponent(source.document_id)}/versions/${source.document_version}`, { signal },
  );
}

export function uploadKnowledgeDocument(id: string, file: File, signal?: AbortSignal) {
  const body = new FormData();
  body.append("file", file);
  return requestJson<DocumentUploadResult>(`${basePath(id)}/documents`, { method: "POST", body, signal });
}

export async function deleteKnowledgeDocument(id: string, documentId: string, signal?: AbortSignal) {
  await request(`${basePath(id)}/documents/${encodeURIComponent(documentId)}`, { method: "DELETE", signal });
}

export function fetchKnowledgeChunks(id: string, documentId: string, offset = 0, signal?: AbortSignal) {
  return requestJson<KnowledgeChunkPage>(
    `${basePath(id)}/documents/${encodeURIComponent(documentId)}/chunks?offset=${offset}&limit=20`, { signal },
  );
}

export function searchKnowledge(id: string, query: string, signal?: AbortSignal) {
  return requestJson<KnowledgeSearchResult>(`${basePath(id)}/search`, {
    ...jsonBody({ query, limit: 5 }), signal,
  });
}

export function fetchEvaluationSuite(signal?: AbortSignal) {
  return requestJson<RetrievalSuite>("/api/knowledge-evaluations/sample-suite", { signal });
}

export function evaluateKnowledge(id: string, suite: RetrievalSuite, signal?: AbortSignal) {
  return requestJson<RetrievalReport>(`/api/knowledge-evaluations/${encodeURIComponent(id)}/run`, {
    ...jsonBody(suite), signal,
  });
}
