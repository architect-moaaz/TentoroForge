/**
 * The editor's calls — every mutation names its base revision and gets the
 * committed one back.
 *
 * Its own fetch rather than `@/lib/api`: the backend answers a refusal as
 * `{code, message, findings, current}` and the shared client flattens that to
 * a status text, which is exactly the wording (UX-004) the editor exists to
 * show.
 */
import type { ApplyResult, Finding, HistoryEntry, Op, PageDoc, PageListItem, Proposal, WidgetRef, WidgetSpec } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

export interface EditorFailure {
  status: number;
  code: string;
  message: string;
  current?: string;
  findings?: Finding[];
  expandsScope?: string[];
  line?: number | null;
}

export class EditorApiError extends Error {
  constructor(public failure: EditorFailure) {
    super(failure.message);
    this.name = "EditorApiError";
  }
}

export function failureOf(err: unknown): EditorFailure {
  if (err instanceof EditorApiError) return err.failure;
  if (err instanceof DOMException && err.name === "AbortError") return { status: 0, code: "cancelled", message: "Cancelled." };
  return { status: 0, code: "network", message: err instanceof Error ? err.message : "Lost the connection." };
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as Record<string, string> ?? {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  if (res.ok) return res.status === 204 ? (undefined as T) : res.json();
  let body: unknown = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  const detail = (body && typeof body === "object" && "detail" in body) ? (body as { detail: unknown }).detail : body;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>;
    throw new EditorApiError({
      status: res.status,
      code: String(d.code ?? "error"),
      message: String(d.message ?? d.msg ?? res.statusText),
      current: typeof d.current === "string" ? d.current : undefined,
      findings: Array.isArray(d.findings) ? d.findings as Finding[] : undefined,
      expandsScope: Array.isArray(d.expandsScope) ? d.expandsScope as string[] : undefined,
      line: typeof d.line === "number" ? d.line : undefined,
    });
  }
  const message = typeof detail === "string" ? detail : res.status === 401 ? "You are signed out — sign in again." : res.statusText;
  throw new EditorApiError({ status: res.status, code: res.status === 401 ? "unauthorized" : "error", message });
}

const post = <T>(path: string, body?: unknown, signal?: AbortSignal) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body), signal });

const base = (projectId: string) => `/api/projects/${projectId}/react-editor`;

export interface JitBundle {
  js: string;
  css: string;
  revision: string;
  vendorKey: string;
  ms: number;
  cached: boolean;
  data: "sample";
  warnings: string[];
}

export interface VendorBundle {
  key: string;
  js: string;
  specifiers: string[];
  ms: number;
  cached: boolean;
}

export const editorApi = {
  vendor: (projectId: string, opts: { fresh?: boolean } = {}, signal?: AbortSignal) =>
    call<VendorBundle>(`${base(projectId)}/vendor${opts.fresh ? "?fresh=true" : ""}`, { signal }),
  jit: (projectId: string, pageId: string, opts: { params?: Record<string, string>; search?: Record<string, string>; fresh?: boolean } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams();
    if (opts.params && Object.keys(opts.params).length) q.set("params", JSON.stringify(opts.params));
    if (opts.search && Object.keys(opts.search).length) q.set("search", JSON.stringify(opts.search));
    if (opts.fresh) q.set("fresh", "true");
    const qs = q.toString();
    return call<JitBundle>(`${base(projectId)}/pages/${pageId}/jit${qs ? `?${qs}` : ""}`, { signal });
  },
  pages: (projectId: string) => call<{ entryPage: string; pages: PageListItem[] }>(`${base(projectId)}/pages`),
  open: (projectId: string, pageId: string) => call<PageDoc>(`${base(projectId)}/pages/${pageId}`),
  apply: (projectId: string, pageId: string, baseRevision: string, ops: Op[], label: string) =>
    post<ApplyResult>(`${base(projectId)}/pages/${pageId}/apply`, { baseRevision, ops, label }),
  history: (projectId: string, pageId: string) => call<{ history: HistoryEntry[] }>(`${base(projectId)}/pages/${pageId}/history`),
  restore: (projectId: string, pageId: string, revision: string, expectedRevision: string) =>
    post<ApplyResult>(`${base(projectId)}/pages/${pageId}/restore`, { revision, expectedRevision }),
  check: (projectId: string, pageId: string) =>
    call<{ revision: string; findings: Finding[]; checked: boolean; reason?: string }>(`${base(projectId)}/pages/${pageId}/check`),
  propose: (projectId: string, pageId: string, body: {
    baseRevision: string; prompt: string; selection: { type: string; nodeIds: string[] };
    scope?: Record<string, unknown>; annotation?: string; breakpoint?: string; proposalId?: string;
    prior?: { question: string; choice: string } | null;
  }, signal?: AbortSignal) => post<Proposal>(`${base(projectId)}/pages/${pageId}/smith`, body, signal),
  applyProposal: (projectId: string, pageId: string, proposalId: string, baseRevision: string, allowScopeExpansion: boolean) =>
    post<ApplyResult & { proposal: Proposal; alreadyApplied?: boolean }>(
      `${base(projectId)}/pages/${pageId}/smith/${proposalId}/apply`, { baseRevision, allowScopeExpansion }),
  createWidget: (projectId: string, pageId: string, spec: WidgetSpec) =>
    post<{ widget: WidgetRef }>(`${base(projectId)}/pages/${pageId}/widgets`, { spec }),
  updateWidget: (projectId: string, widgetId: string, spec: WidgetSpec, pageRevision: string | null) =>
    call<{ widget: WidgetRef; renamed: { from: string; to: string; revision: string } | null }>(
      `${base(projectId)}/widgets/${widgetId}`, { method: "PATCH", body: JSON.stringify({ spec, pageRevision }) }),
  removeWidget: (projectId: string, widgetId: string) =>
    call<{ removed: boolean }>(`${base(projectId)}/widgets/${widgetId}`, { method: "DELETE" }),
  discardProposal: (projectId: string, pageId: string, proposalId: string) =>
    post<Proposal>(`${base(projectId)}/pages/${pageId}/smith/${proposalId}/discard`),
};
