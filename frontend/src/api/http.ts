// 统一处理 HTTP 状态、网络异常与取消请求；不在页面里重复判断错误。
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** Absolute URL for plain links (downloads) that do not go through requestJson. */
export const apiUrl = (path: string) => `${API_BASE}${path}`;

export class ApiError extends Error {
  status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// Cookies are sent only once this workbench is known to use an access token; otherwise requests stay exactly as before.
const AUTH_FLAG = "workbenchAuth";
const remembered = () => { try { return localStorage.getItem(AUTH_FLAG) === "1"; } catch { return false; } };
const remember = () => { try { localStorage.setItem(AUTH_FLAG, "1"); } catch { /* Private mode: the cookie still works this session. */ } };
let withCookie = remembered();
let unlocking: Promise<boolean> | null = null;

/** Asks once for the access token and trades it for an HttpOnly session cookie. */
function unlock(): Promise<boolean> {
  unlocking ??= (async () => {
    const token = window.prompt("这个工作台设置了访问令牌，请输入：")?.trim();
    if (!token) return false;
    const response = await fetch(API_BASE + "/api/session", {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
    }).catch(() => null);
    if (!response?.ok) { window.alert("访问令牌不正确。"); return false; }
    withCookie = true;
    remember();
    return true;
  })().finally(() => { unlocking = null; });
  return unlocking;
}

export async function request(path: string, options?: RequestInit, attempt = 0): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(API_BASE + path, withCookie ? { credentials: "include", ...options } : options);
  } catch (error) {
    if (options?.signal?.aborted) throw error;
    throw new ApiError("无法连接后端，请先启动后端服务。");
  }
  if (response.status === 401 && attempt < 2) {
    const data = await response.clone().json().catch(() => null);
    if (data?.error_code === "AUTH_REQUIRED") {
      // First try the cookie from an earlier session, then ask for the token.
      if (!withCookie) { withCookie = true; const retried = await request(path, options, attempt + 1); if (retried.ok) remember(); return retried; }
      if (await unlock()) return request(path, options, 2);
    }
  }
  if (!response.ok) {
    let message = "后端服务暂时不可用，请稍后重试。";
    if (response.status === 422) message = "请求参数不正确，请检查输入内容。";
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      // 非 JSON 错误页使用上述默认说明。
    }
    throw new ApiError(message, response.status);
  }
  return response;
}

export async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await request(path, options);
  return response.json();
}

export function jsonBody(value: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  };
}
