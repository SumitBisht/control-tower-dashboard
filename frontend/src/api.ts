// Thin fetch wrapper. Kept framework-free so it can be reused by the future React Native app.
const BASE = import.meta.env.VITE_API_URL ?? "/api";
const TOKEN_KEY = "ct_token";

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function errorText(body: any, status: number): string {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => e.msg?.replace(/^Value error, /, "")).join("; ");
  return `Request failed (${status})`;
}

export async function api<T = any>(path: string, opts: { method?: string; json?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const t = tokenStore.get();
  if (t) headers.Authorization = `Bearer ${t}`;
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) body = opts.form;
  let res: Response;
  try {
    res = await fetch(BASE + path, { method: opts.method ?? "GET", headers, body });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection and try again.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && t) {
      tokenStore.clear();
      window.dispatchEvent(new Event("ct-logout"));
    }
    throw new ApiError(res.status, errorText(data, res.status));
  }
  return data as T;
}

/** Authenticated file download (the bearer token cannot be sent via a plain <a href>). */
export async function download(path: string, fallbackName: string): Promise<void> {
  const t = tokenStore.get();
  let res: Response;
  try {
    res = await fetch(BASE + path, { headers: t ? { Authorization: `Bearer ${t}` } : {} });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection and try again.");
  }
  if (!res.ok) throw new ApiError(res.status, errorText(await res.json().catch(() => null), res.status));
  const m = /filename="?([^";]+)"?/.exec(res.headers.get("Content-Disposition") ?? "");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = m?.[1] ?? fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export interface ReportRow {
  id: string; reportNo: string; reportDate: string | null; spvName: string; projectName: string; manufacturer: string;
  conclusion: string | null; models: string[]; containers: number; modules: number; capacityMwp: number;
  failedContainers: number; loadingFrom: string; loadingTo: string; hasSource: boolean; sourceFileName?: string;
}

export type Role = "viewer" | "uploader" | "admin";
export interface User { id: string; email: string; name: string; role: Role; status: "pending" | "active" | "disabled"; createdAt?: string }
export interface LogEntry { ts: string; level: "INFO" | "WARNING" | "ERROR"; code: string; message: string }
export interface Upload {
  id: string; fileName: string; fileSize: number; uploadedBy: string; uploadedAt: string; status: string;
  summary: Record<string, any> | null; counts: Record<string, number>; logs?: LogEntry[];
}
export interface WidgetSetting { key: string; title: string; kind: string; visible: boolean; columns: Record<string, boolean>; columnLabels: Record<string, string> }
