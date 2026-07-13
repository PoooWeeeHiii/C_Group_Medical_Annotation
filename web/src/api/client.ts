const TOKEN_KEY = "label_platform_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(extra: HeadersInit = {}): HeadersInit {
  const headers: Record<string, string> = { ...(extra as Record<string, string>) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function parseResponse<T>(response: Response, path: string): Promise<T> {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) setToken("");
    const detail =
      typeof (data as { detail?: unknown }).detail === "string"
        ? (data as { detail: string }).detail
        : JSON.stringify((data as { detail?: unknown }).detail || {});
    throw new Error(detail || `${path} 请求失败：${response.status}`);
  }
  return data as T;
}

export async function apiGet<T = unknown>(path: string): Promise<T> {
  const response = await fetch(path, { headers: authHeaders() });
  return parseResponse<T>(response, path);
}

export async function apiPost<T = unknown>(
  path: string,
  payload?: unknown,
  options: { timeoutMs?: number } = {},
): Promise<T> {
  const controller = new AbortController();
  const timer =
    options.timeoutMs && options.timeoutMs > 0
      ? window.setTimeout(() => controller.abort(), options.timeoutMs)
      : null;
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload ?? {}),
      signal: controller.signal,
    });
    return parseResponse<T>(response, path);
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}

export async function apiPut<T = unknown>(path: string, payload?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload ?? {}),
  });
  return parseResponse<T>(response, path);
}

export async function apiDelete<T = unknown>(path: string): Promise<T> {
  const response = await fetch(path, {
    method: "DELETE",
    headers: authHeaders(),
  });
  return parseResponse<T>(response, path);
}

export async function apiUploadForm<T = unknown>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  return parseResponse<T>(response, path);
}
