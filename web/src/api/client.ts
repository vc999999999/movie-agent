export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => (typeof d === "object" && d !== null && "msg" in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d))).join("; ")
          : `请求失败 (${status})`;
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;
  const response = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });
  const data: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data === "object" && data !== null && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

export function encodeSeg(value: string): string {
  return encodeURIComponent(value);
}

export function outputUrl(projectId: string, filename: string): string {
  return `/api/projects/${encodeSeg(projectId)}/outputs/${encodeSeg(filename)}`;
}
