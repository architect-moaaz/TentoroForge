"use client";
import { useQuery } from "@tanstack/react-query";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

/**
 * Fetch a JSON file from the project output directory.
 * Uses the no-auth debug endpoint so the canvas works without JWT plumbing.
 * Backend: GET /api/_debug/project-file/{short_id}/{file_path:path}
 * For .json files the endpoint returns the parsed JSON directly.
 */
async function fetchProjectFile<T>(projectId: string, filePath: string): Promise<T | null> {
  try {
    const r = await fetch(`${API}/api/_debug/project-file/${projectId}/${filePath}`);
    if (!r.ok) return null;
    return r.json() as Promise<T>;
  } catch {
    return null;
  }
}

async function fetchDebugJson<T>(url: string): Promise<T | null> {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return r.json() as Promise<T>;
  } catch {
    return null;
  }
}

interface Artifacts {
  schema: any;
  designSpec: any;
  /** Project's canonical color/typography/spacing tokens — separate from
   *  designSpec.tokens so library's TokensProvider keeps its expected shape. */
  cssVarTokens: Record<string, unknown> | null;
  navFlow: any;
  previewData: Record<string, unknown>;
  isLoading: boolean;
}

export function useArtifacts(projectId: string, pagePath: string): Artifacts {
  // Load nav-flow FIRST — it carries the authoritative schemaFile path for
  // each page, which may differ from the page id (e.g. id="leave-requests-new"
  // but the file is at src/schemas/leave-requests/new.json under folder
  // layout). Falling back to `${pagePath}.json` preserves the legacy
  // behaviour for projects without a nav-flow.
  const navFlowQ = useQuery({
    queryKey: ["nav-flow", projectId],
    queryFn: () =>
      fetchProjectFile(projectId, "src/contracts/nav-flow.json"),
    enabled: !!projectId,
  });

  const schemaQ = useQuery({
    queryKey: ["schema", projectId, pagePath, (navFlowQ.data as any)?.version],
    queryFn: () => {
      // Special-case the synthetic 'shell' page — it represents the project's
      // app shell schema (header / nav / sidebar / footer) and isn't listed
      // in nav-flow.pages because it's not a navigable route.
      if (pagePath === "shell") {
        return fetchProjectFile(projectId, "src/schemas/shell.json");
      }
      const nf = navFlowQ.data as { pages?: Array<{ id?: string; schemaFile?: string }> } | null;
      const page = nf?.pages?.find((p) => p.id === pagePath);
      const filePath = page?.schemaFile ?? `src/schemas/${pagePath}.json`;
      return fetchProjectFile(projectId, filePath);
    },
    // Wait until nav-flow is loaded (or definitively absent) so we never
    // race with the legacy fallback.
    enabled: !!projectId && !!pagePath && !navFlowQ.isLoading,
  });

  const designSpecQ = useQuery({
    queryKey: ["design-spec", projectId],
    queryFn: () =>
      fetchProjectFile(projectId, "src/contracts/design-spec.json"),
    enabled: !!projectId,
  });

  // The canonical color/spacing/radius/typography tokens live in tokens.custom.json.
  // design-spec.json only carries `tokens.surface` (gradient + shadow). Merge them
  // so EngineProvider's CSS-var injector sees the full token tree.
  const tokensCustomQ = useQuery({
    queryKey: ["tokens-custom", projectId],
    queryFn: () =>
      fetchProjectFile<Record<string, unknown>>(projectId, "src/theme/tokens.custom.json"),
    enabled: !!projectId,
  });

  const previewDataQ = useQuery({
    queryKey: ["preview-data", projectId],
    queryFn: () =>
      fetchDebugJson<Record<string, unknown>>(
        `${API}/api/_debug/preview-data/${projectId}`
      ).then((d) => d ?? {}),
    enabled: !!projectId,
  });

  return {
    schema: schemaQ.data ?? null,
    designSpec: designSpecQ.data ?? null,
    cssVarTokens: (tokensCustomQ.data as Record<string, unknown> | null) ?? null,
    navFlow: navFlowQ.data ?? null,
    previewData: (previewDataQ.data as Record<string, unknown>) ?? {},
    isLoading: schemaQ.isLoading,
  };
}
