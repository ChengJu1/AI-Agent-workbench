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

export async function request(path: string, options?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(API_BASE + path, options);
  } catch (error) {
    if (options?.signal?.aborted) throw error;
    throw new ApiError("无法连接后端，请先启动后端服务。");
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
