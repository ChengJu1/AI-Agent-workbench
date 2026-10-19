import { jsonBody, request, requestJson } from "./http";
export type Capability = "files" | "web" | "browser";
export const capabilities: { id: Capability; name: string; description: string }[] = [
  { id: "files", name: "文件解析", description: "读取当前会话上传的 PDF、DOCX 与文本文件，不扫描本机目录。" },
  { id: "web", name: "联网检索", description: "搜索公开网页、读取正文与来源。搜索词仅使用职位、技能等非敏感信息。" },
  { id: "browser", name: "受控浏览器", description: "独立浏览器查看网站；填表、上传和点击均需确认。登录由你接手。" },
];
export type Attachment = { id: string; filename: string; byte_size: number; text_length: number; created_at: string };
export type FilePreview = Attachment & { text: string; next_offset: number | null };
export type BrowserSession = { id: string; url: string; manual_until: number };
export const fetchCapabilities = (agentId: string, signal?: AbortSignal) => requestJson<{capabilities: Capability[]}>(`/api/agents/${agentId}/capabilities`, { signal });
export const saveCapabilities = (agentId: string, selected: Capability[], signal?: AbortSignal) => requestJson<{capabilities: Capability[]}>(`/api/agents/${agentId}/capabilities`, { ...jsonBody({ capabilities: selected }), method: "PUT", signal });
export const fetchAttachments = (id: string, signal?: AbortSignal) => requestJson<Attachment[]>(`/api/conversations/${id}/files`, { signal });
export async function uploadAttachment(id: string, file: File, signal?: AbortSignal) {
  const body = new FormData(); body.append("file", file);
  return requestJson<Attachment>(`/api/conversations/${id}/files`, { method: "POST", body, signal });
}
export const previewAttachment = (id: string, file: string, signal?: AbortSignal) => requestJson<FilePreview>(`/api/conversations/${id}/files/${file}`, { signal });
export const fetchBrowsers = (id: string, signal?: AbortSignal) => requestJson<BrowserSession[]>(`/api/conversations/${id}/browser`, { signal });
export const openBrowser = (id: string, url: string, signal?: AbortSignal) => requestJson<{session_id: string}>(`/api/conversations/${id}/browser`, { ...jsonBody({ url }), signal });
export async function browserScreenshot(id: string, session: string, signal?: AbortSignal) {
  const result = await request(`/api/conversations/${id}/browser/${session}/screenshot`, { signal });
  return URL.createObjectURL(await result.blob());
}
export const closeBrowser = (id: string, session: string, signal?: AbortSignal) => requestJson(`/api/conversations/${id}/browser/${session}`, { method: "DELETE", signal });
export const browserTakeover = (id: string, session: string, active: boolean, signal?: AbortSignal) => requestJson(`/api/conversations/${id}/browser/${session}/takeover`, { ...jsonBody({active}), signal });
