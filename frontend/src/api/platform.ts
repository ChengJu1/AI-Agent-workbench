import { jsonBody, requestJson } from "./http";
import { KIT_MANIFESTS, type KitCapability } from "../kits/manifests.ts";
export type Capability = "files" | "web" | "browser" | "tracking" | "code" | KitCapability;
export const capabilities: { id: Capability; name: string; description: string }[] = [
  ...KIT_MANIFESTS.map(kit => ({ id: kit.capability, name: kit.name, description: kit.description })),
  { id: "tracking", name: "记录与跟踪", description: "查看执行记录、提出只读跟踪方案。定期检查由你审阅启用；访问网站仍需对应权限。" },
  { id: "files", name: "文件解析", description: "读取当前会话上传的 PDF、DOCX 与文本文件，或你明确关联的单个本机文件，不扫描目录。" },
  { id: "web", name: "联网检索", description: "搜索公开网页、读取正文与来源。搜索词仅使用主题、关键词等非敏感信息。" },
  { id: "browser", name: "受控浏览器", description: "独立浏览器查看网站；填表、上传和点击均需确认。登录由你接手。" },
  { id: "code", name: "项目代码", description: "只读浏览、搜索和阅读你为此 Agent 绑定的本机项目目录，不能修改或执行代码；.env 和密钥文件不可见。" },
];
export type CodeProject = { id: string; name: string; root: string; git: boolean; available: boolean; file_count?: number; files_truncated?: boolean };
export const fetchCodeProjects = (agentId: string, signal?: AbortSignal) => requestJson<{projects: CodeProject[]}>(`/api/agents/${agentId}/code-projects`, { signal });
export const addCodeProject = (agentId: string, path: string) => requestJson<CodeProject>(`/api/agents/${agentId}/code-projects`, jsonBody({ path }));
export const removeCodeProject = (agentId: string, projectId: string) => requestJson(`/api/agents/${agentId}/code-projects/${projectId}`, { method: "DELETE" });
// kind: text is read with read_file; image / scanned_pdf go to the model as images inside a user message.
export type Attachment = { id: string; filename: string; byte_size: number; text_length: number; created_at: string; version: number; content_hash: string; linked_local: boolean; kind?: "text" | "image" | "scanned_pdf" };
export type FilePreview = Attachment & { text: string; next_offset: number | null };
export type BrowserSession = { id: string; url: string; manual_until: number;browser_name?:string;can_takeover?:boolean;provider?:string;tabs?:{index:number;current:boolean;title:string;url:string}[] };
export const fetchCapabilities = (agentId: string, signal?: AbortSignal) => requestJson<{capabilities: Capability[]}>(`/api/agents/${agentId}/capabilities`, { signal });
export const saveCapabilities = (agentId: string, selected: Capability[], signal?: AbortSignal) => requestJson<{capabilities: Capability[]}>(`/api/agents/${agentId}/capabilities`, { ...jsonBody({ capabilities: selected }), method: "PUT", signal });
export const fetchAttachments = (id: string, signal?: AbortSignal) => requestJson<Attachment[]>(`/api/conversations/${id}/files`, { signal });
export async function uploadAttachment(id: string, file: File, signal?: AbortSignal) {
  const body = new FormData(); body.append("file", file);
  return requestJson<Attachment>(`/api/conversations/${id}/files`, { method: "POST", body, signal });
}
export const previewAttachment = (id: string, file: string, signal?: AbortSignal) => requestJson<FilePreview>(`/api/conversations/${id}/files/${file}`, { signal });
export const fetchBrowsers = (id: string, signal?: AbortSignal) => requestJson<BrowserSession[]>(`/api/conversations/${id}/browser`, { signal });
export const openBrowser = (id: string, url: string, signal?: AbortSignal) => requestJson<{session_id: string;warning?:string;http_status?:number}>(`/api/conversations/${id}/browser`, { ...jsonBody({ url }), signal });
export const closeBrowser = (id: string, session: string, signal?: AbortSignal) => requestJson(`/api/conversations/${id}/browser/${session}`, { method: "DELETE", signal });
export const browserTakeover = (id: string, session: string, active: boolean, signal?: AbortSignal, durationSeconds=60) => requestJson(`/api/conversations/${id}/browser/${session}/takeover`, { ...jsonBody({active,duration_seconds:durationSeconds}), signal });
export const reloadBrowser=(id:string,session:string,signal?:AbortSignal)=>requestJson<{url:string;warning?:string}>(`/api/conversations/${id}/browser/${session}/reload`,{method:'POST',signal});
export type ResourceCheck = Attachment & {resource_state:string;message:string};
export const checkAttachment=(id:string,file:string,signal?:AbortSignal)=>requestJson<ResourceCheck>(`/api/conversations/${id}/files/${file}/check`,{signal});
export const attachmentVersions=(id:string,file:string,signal?:AbortSignal)=>requestJson<Attachment[]>(`/api/conversations/${id}/files/${file}/versions`,{signal});
export const previewAttachmentVersion=(id:string,file:string,version:number,signal?:AbortSignal)=>requestJson<FilePreview>(`/api/conversations/${id}/files/${file}?version=${version}`,{signal});
export const linkLocalFile=(id:string,path:string,file?:Attachment,signal?:AbortSignal)=>requestJson<Attachment>(`/api/conversations/${id}/local-files`,{...jsonBody({path,file_id:file?.id,expected_version:file?.version}),signal});
export async function replaceAttachment(id:string,current:Attachment,file:File,signal?:AbortSignal){const body=new FormData();body.append('file',file);body.append('expected_version',String(current.version));return requestJson<Attachment>(`/api/conversations/${id}/files/${current.id}`,{method:'PUT',body,signal});}
export const refreshLocalFile=(id:string,file:Attachment,signal?:AbortSignal)=>requestJson<Attachment>(`/api/conversations/${id}/files/${file.id}/refresh`,{...jsonBody({expected_version:file.version}),signal});
export type BrowserFrame={image:string;provider?:string;manual_refresh_only?:boolean;capture_paused?:boolean;interaction_warning?:string|null;url:string;browser_name:string;captured_at:number;viewport:{width:number;height:number};target:{label:string;kind:string;box:{x:number;y:number;width:number;height:number}|null}|null;plan_state:'none'|'current'|'stale'|'busy';plan_error?:string|null;manual_until:number;can_takeover:boolean;page_state?:'ready'|'empty'|'blank'|'loading'|'choose_tab'|'snapshot_unavailable';resource_warning?:string|null;resource_issues?:BrowserResourceIssue[];connection_review?:{pending_resources:number;pending_send:number};progress:{phase?:string;index?:number;total?:number;label?:string;kind?:string}};
export const fetchBrowserFrame=(id:string,session:string,action?:string,index=0,signal?:AbortSignal)=>requestJson<BrowserFrame>(`/api/conversations/${id}/browser/${session}/preview?operation_index=${index}${action?`&action_id=${encodeURIComponent(action)}`:''}`,{signal});
export const captureBrowserFrame=(id:string,session:string,action_id?:string,operation_index=0,signal?:AbortSignal)=>requestJson<BrowserFrame>(`/api/conversations/${id}/browser/${session}/preview-capture`,{...jsonBody({action_id,operation_index}),signal});
export const focusBrowserStep=(id:string,session:string,action_id:string,operation_index:number,signal?:AbortSignal)=>requestJson<BrowserFrame>(`/api/conversations/${id}/browser/${session}/preview-focus`,{...jsonBody({action_id,operation_index}),signal});
export type BrowserResourceIssue={host:string;path?:string;code?:string;kind?:string;method?:string;mime?:string;extension?:string;cache_policy?:string;error:string};
export type BrowserConnection={id:string;url:string;method:string;kind:string;host:string;expires_at:number};
export type BrowserConnectionView={page_url:string;revision:number;pending:BrowserConnection[];granted:Omit<BrowserConnection,'id'|'kind'>[]};
export const fetchBrowserConnections=(id:string,session:string,signal?:AbortSignal)=>requestJson<BrowserConnectionView>(`/api/conversations/${id}/browser/${session}/connections`,{signal});
export const allowBrowserConnections=(id:string,session:string,request_ids:string[],page_url:string,allow_data=false)=>requestJson<{message:string}>(`/api/conversations/${id}/browser/${session}/connections`,jsonBody({request_ids,page_url,allow_data}));
export const revokeBrowserConnections=(id:string,session:string)=>requestJson(`/api/conversations/${id}/browser/${session}/connections`,{method:'DELETE'});

export const inspectBrowser=(id:string,session:string,tab_index?:number)=>requestJson<{url:string;page_state:string;authentication_state:string;tabs:{index:number;current:boolean;title:string;url:string}[];element_count:number;text_length:number;diagnostics?:{ready_state?:string;body_characters?:number;frame_count?:number;failed_resources?:{host:string;status:string;error?:string}[]}}>(`/api/conversations/${id}/browser/${session}/inspect`,jsonBody({tab_index}));
