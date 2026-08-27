// frontend/src/lib/fidelity-client.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

export interface CritiquePatch {
  op: "add" | "replace" | "remove" | "move";
  path: string;
  value?: unknown;
  from?: string;
}

export interface CritiqueIssue {
  severity: "high" | "medium" | "low";
  axis: string;
  nodeIdHint: string | null;
  issue: string;
  suggestion: string;
  patchOp?: CritiquePatch | null;
}

export interface Critique {
  scores: Record<string, number>;
  compositeScore: number;
  pass: boolean;
  topIssues: CritiqueIssue[];
  strengths: string[];
  designerApprovalRecommended: boolean;
}

export async function scorePage(
  shortId: string,
  pageRoute: string,
  pagePath: string,
  context: { domain: string; appName: string; description: string; tone: string },
): Promise<Critique> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;

  const params = new URLSearchParams({
    page_route: pageRoute,
    page_path: pagePath,
    domain: context.domain,
    app_name: context.appName,
    description: context.description,
    tone: context.tone,
  });

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(
    `${API_BASE}/api/_debug/score-page/${shortId}?${params}`,
    {
      method: "POST",
      headers,
      credentials: "include",
    },
  );

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const message =
      body.error?.message || body.detail || body.message || res.statusText;
    throw new Error(message);
  }

  return res.json() as Promise<Critique>;
}

export interface PageLogEntry {
  iterations: Array<{
    iteration: number;
    score: number;
    issues?: any[];
    patch_summary?: string[];
    pass: boolean;
    manual_run?: boolean;
  }>;
  final_score: number;
  final_iteration: number;
  exit_status?: string;
  failed_fidelity?: boolean;
  wall_clock_ms?: number;
  cost_usd?: number;
  flags?: Record<string, any>;
}

export type FidelityLog = Record<string, PageLogEntry>;

export async function fetchFidelityLog(shortId: string): Promise<FidelityLog | null> {
  try {
    const r = await fetch(`${API_BASE}/api/_debug/fidelity-log/${shortId}`);
    if (!r.ok) return null;
    return (await r.json()) as FidelityLog;
  } catch {
    return null;
  }
}
