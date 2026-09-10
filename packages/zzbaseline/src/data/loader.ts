import type { DataSource } from "../types";
import { interpolateString } from "./interpolate";

export async function fetchDataSources(
  sources: DataSource[] | undefined,
  apiBaseUrl: string,
): Promise<Record<string, unknown>> {
  const out: Record<string, unknown> = {};
  if (!sources || sources.length === 0) return out;

  for (const s of sources) {
    const rawPath = s.source ? interpolateString(s.source, out) : null;
    if (!rawPath) { out[s.name] = null; continue; }

    const path = String(rawPath);
    const url = path.startsWith("http")
      ? path
      : apiBaseUrl
        ? `${apiBaseUrl.replace(/\/$/, "")}${path}`
        : path;

    try {
      const resp = await fetch(url);
      if (!resp.ok) { out[s.name] = null; continue; }
      let payload = await resp.json();
      // Unwrap the list API's pagination envelope { data, total, page, limit }
      // down to its array, so list-bound consumers (e.g. Select optionsFrom,
      // which needs a bare array) receive the rows rather than the envelope.
      if (
        payload && typeof payload === "object" && !Array.isArray(payload) &&
        Array.isArray((payload as { data?: unknown }).data)
      ) {
        payload = (payload as { data: unknown[] }).data;
      }
      out[s.name] = payload;
    } catch {
      out[s.name] = null;
    }

    // For get-op sources, lift the record's top-level OBJECT keys to root.
    // Mirrors today's SchemaRendererWrapper FK-lift logic — keeps `{{employee.name}}`
    // bindings working without forcing every binding to use the parent prefix.
    if (s.op === "get" && out[s.name] && typeof out[s.name] === "object" && !Array.isArray(out[s.name])) {
      const record = out[s.name] as Record<string, unknown>;
      for (const [k, v] of Object.entries(record)) {
        if (v && typeof v === "object" && !Array.isArray(v) && !(k in out)) {
          out[k] = v;
        }
      }
    }
  }

  return out;
}
