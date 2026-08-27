import type { Page } from "@tentoroforge/schema";
import type { TokenGroups } from "@tentoroforge/library";
import type { SaveResult, LoadResult } from "./types";

/**
 * URL strategy:
 *   The editor calls endpoints like `pages`, `load`, `save`, `theme`,
 *   `suggest`. The full URL is `${baseUrl}/${endpoint}`.
 *
 *   - Embedded inside a generated app:  baseUrl = "/api/editor"
 *     resolves to /api/editor/pages, etc. (the app-foundation (dev-only) route)
 *   - Embedded in the control plane:    baseUrl = "/api/projects/<short_id>"
 *     resolves to /api/projects/<id>/pages, etc. (output_projects router)
 *   - Standalone tests:                 baseUrl = "" (relative)
 *
 *   Trailing slashes on baseUrl are stripped to avoid double-slashes.
 */
function joinUrl(baseUrl: string, endpoint: string, query = ""): string {
  const base = baseUrl.replace(/\/+$/, "");
  return `${base}/${endpoint}${query}`;
}

export async function saveSchema(path: string, schema: Page, baseUrl = ""): Promise<SaveResult> {
  const r = await fetch(joinUrl(baseUrl, "save"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, schema }),
  });
  if (r.status === 200) {
    const body = await r.json();
    return { ok: true, savedSchema: body.savedSchema, suggestions: body.suggestions ?? [], autoApplied: body.autoApplied };
  }
  if (r.status === 422) {
    const body = await r.json();
    return { ok: false, errors: body.errors ?? [], httpStatus: 422 };
  }
  let errors: any[] = [];
  try { errors = (await r.json()).errors ?? []; } catch {}
  return { ok: false, errors, httpStatus: r.status };
}

export async function loadSchema(path: string, baseUrl = ""): Promise<LoadResult> {
  const r = await fetch(joinUrl(baseUrl, "load", `?path=${encodeURIComponent(path)}`), {
    method: "GET",
    headers: { "Accept": "application/json" },
  });
  if (!r.ok) throw new Error(`loadSchema: ${r.status}`);
  return r.json();
}

export async function listPages(baseUrl = ""): Promise<{ paths: string[] }> {
  const r = await fetch(joinUrl(baseUrl, "pages"), {
    headers: { Accept: "application/json" },
  });
  if (!r.ok) throw new Error(`listPages: ${r.status}`);
  return r.json();
}

export type SchemaListEntry = {
  route: string;
  slug: string;
  page_type: string;
  entity: string | null;
  id: string;
};

/**
 * Flat schema listing with route metadata. Each entry corresponds to one
 * schema JSON under src/schemas/, with route/slug derived from either an
 * explicit `route` field on the schema or the file path. Returns null if
 * the endpoint is not available (e.g. older backend) so callers can fall
 * back to the legacy tree-style `listPages` listing.
 */
export async function listSchemas(
  baseUrl = "",
): Promise<SchemaListEntry[] | null> {
  try {
    const r = await fetch(joinUrl(baseUrl, "schema-list"), {
      headers: { Accept: "application/json" },
    });
    if (!r.ok) return null;
    const body = await r.json();
    return Array.isArray(body) ? body : null;
  } catch {
    return null;
  }
}

export async function getTheme(baseUrl = ""): Promise<{ tokens: TokenGroups; source: "default" | "custom" }> {
  const r = await fetch(joinUrl(baseUrl, "theme"), { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`getTheme: ${r.status}`);
  return r.json();
}

export async function saveTheme(tokens: TokenGroups, baseUrl = ""): Promise<{ ok: boolean }> {
  const r = await fetch(joinUrl(baseUrl, "theme"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tokens }),
  });
  if (!r.ok) throw new Error(`saveTheme: ${r.status}`);
  return r.json();
}

/**
 * Fetch the project's compiled globals.css so the editor canvas can mount the
 * same stylesheet the generated app uses (HSL design tokens, base styles,
 * shadcn-style component primitives). Returns "" if missing or unreachable —
 * the editor degrades to its built-in defaults rather than throwing.
 */
export async function getProjectCss(baseUrl = ""): Promise<string> {
  try {
    const r = await fetch(joinUrl(baseUrl, "css"), { headers: { Accept: "application/json" } });
    if (!r.ok) return "";
    const body = await r.json();
    return typeof body?.css === "string" ? body.css : "";
  } catch {
    return "";
  }
}

export async function getSuggestions(
  schema: Page,
  mode: "ambient",
  baseUrl = ""
): Promise<{ suggestions: any[] }> {
  const r = await fetch(joinUrl(baseUrl, "suggest"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, schema }),
  });
  if (!r.ok) throw new Error(`getSuggestions: ${r.status}`);
  return r.json();
}

export async function regenerateSection(
  prompt: string,
  subtree: any,
  baseUrl = ""
): Promise<{ subtree: any }> {
  const r = await fetch(joinUrl(baseUrl, "suggest"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "regenerate", prompt, subtree }),
  });
  if (!r.ok) throw new Error(`regenerateSection: ${r.status}`);
  return r.json();
}

// ---------------------------------------------------------------------------
// Figma extraction API (Phase 3) — uses an absolute path, not the relative
// editor-API base, since Figma extraction lives at a fixed dev-only route in
// the generated app.
// ---------------------------------------------------------------------------

export async function extractFromFigma(
  args: { fileKey: string; nodeId: string },
  baseUrl = ""
): Promise<{ schema: any; error?: string }> {
  // Figma route is at /api/figma/extract regardless of baseUrl scheme.
  const base = baseUrl.replace(/\/+$/, "");
  const r = await fetch(`${base}/api/figma/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!r.ok) throw new Error(`extractFromFigma: ${r.status}`);
  return r.json();
}

/**
 * Parse a Figma design URL and extract { fileKey, nodeId }.
 * Returns null if the URL is not a recognised Figma design URL.
 *
 * Supports formats:
 *   https://www.figma.com/design/<fileKey>/<name>?node-id=<nodeId>
 *   https://www.figma.com/file/<fileKey>/<name>?node-id=<nodeId>
 *
 * nodeId hyphens are converted to colons per Figma API convention.
 */
export function parseFigmaUrl(url: string): { fileKey: string; nodeId: string } | null {
  const m = url.match(/figma\.com\/(?:design|file)\/([^/]+)\/[^?]*\?.*node-id=([^&]+)/);
  if (!m) return null;
  return { fileKey: m[1], nodeId: m[2].replace(/-/g, ":") };
}
