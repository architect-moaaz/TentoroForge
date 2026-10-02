/**
 * Embeddings — the vectors behind "find records that look like this".
 *
 * A Blueprint field `{type: "vector", embedding: {of: "photo"}}` is projected
 * to a pgvector column and listed in `embedding-columns.ts`. This module fills
 * that column whenever its source is written, on every write path (the Data
 * Engine's create/update and the workflow runtime's db_insert/db_update), and
 * embeds the query an `op: "similar"` source ranks by.
 *
 * The model runs in the embedding sidecar (sidecars/clip): CLIP puts images
 * and text in one space, so a photo can be found by another photo or by a
 * sentence describing it.
 *
 * Sidecar contract:
 *   POST {EMBEDDINGS_URL}/embed
 *   Authorization: Bearer {EMBEDDINGS_API_KEY}     (only when the key is set)
 *   body: {image_b64, mime_type} | {image_url} | {text}
 *   → {vector: number[], dimensions: number, model: string}
 *
 * A write never fails because an embedding could not be computed: the row is
 * the person's work and the vector is derived from it. The column stays null
 * and the row is simply not found by similarity until it is written again.
 * A SEARCH, by contrast, has nothing to show without its query vector, so
 * `embedQuery` throws with a sentence that says what is missing.
 */
import { db } from "@/db";
import { eq, getTableName } from "drizzle-orm";
import { embeddingColumnsFor, EMBEDDING_DIMENSIONS, type EmbeddingColumn } from "./embedding-columns";

export class EmbeddingUnavailable extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EmbeddingUnavailable";
  }
}

async function endpoint(): Promise<{ url: string; apiKey: string }> {
  const { getSecret } = await import("./integrations/resolver");
  const url = (await getSecret("embeddings", "EMBEDDINGS_URL")) || "";
  const apiKey = (await getSecret("embeddings", "EMBEDDINGS_API_KEY")) || "";
  return { url, apiKey };
}

type Body =
  | { image_b64: string; mime_type: string }
  | { image_url: string }
  | { text: string };

async function callSidecar(body: Body): Promise<number[]> {
  const { url, apiKey } = await endpoint();
  if (!url) {
    throw new EmbeddingUnavailable(
      "Image search is not connected — set EMBEDDINGS_URL to the embedding service "
      + "(sidecars/clip) in the environment or under Settings → Integrations.",
    );
  }
  const target = url.replace(/\/$/, "") + (url.endsWith("/embed") ? "" : "/embed");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const res = await fetch(target, { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new EmbeddingUnavailable(`The embedding service answered ${res.status}: ${text.slice(0, 200)}`);
  }
  const payload = await res.json();
  const vector = Array.isArray(payload?.vector) ? payload.vector.map(Number) : null;
  if (!vector || vector.length !== EMBEDDING_DIMENSIONS) {
    // A different model behind the same URL. Writing its vectors would make
    // every distance meaningless, so refuse by name rather than store them.
    throw new EmbeddingUnavailable(
      `The embedding service returned ${vector?.length ?? "no"} dimensions `
      + `(model ${payload?.model ?? "unknown"}); this app's columns hold ${EMBEDDING_DIMENSIONS}.`,
    );
  }
  return vector;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A stored-file id, a FileUpload descriptor, or an http(s) URL → an image body. */
async function imageBody(ref: unknown): Promise<Body | null> {
  let value: unknown = ref;
  if (typeof value === "string" && value.trim().startsWith("{")) {
    try { value = JSON.parse(value); } catch { /* a plain string after all */ }
  }
  if (value && typeof value === "object") value = (value as { id?: unknown; url?: unknown }).id ?? (value as { url?: unknown }).url;
  if (typeof value !== "string" || !value.trim()) return null;
  const s = value.trim();
  if (/^https?:\/\//i.test(s)) return { image_url: s };
  if (!UUID_RE.test(s)) return null;
  const { loadFileBase64 } = await import("./storage");
  const file = await loadFileBase64(s);
  if (!file || !String(file.mediaType).startsWith("image/")) return null;
  return { image_b64: file.base64, mime_type: file.mediaType };
}

export async function embedImage(ref: unknown): Promise<number[] | null> {
  const body = await imageBody(ref);
  return body ? await callSidecar(body) : null;
}

export async function embedText(text: string): Promise<number[] | null> {
  const t = String(text ?? "").trim();
  return t ? await callSidecar({ text: t }) : null;
}

/**
 * The query vector for an `op: "similar"` source. An image wins over text when
 * both are given — it is the more specific question. Throws EmbeddingUnavailable
 * when the service is not reachable; returns null when there is no query.
 */
export async function embedQuery(query: { image?: unknown; text?: unknown }): Promise<number[] | null> {
  if (query.image) {
    const v = await embedImage(query.image);
    if (v) return v;
  }
  if (typeof query.text === "string" && query.text.trim()) return await embedText(query.text);
  return null;
}

function sourceChanged(
  col: EmbeddingColumn,
  record: Record<string, any>,
  previous?: Record<string, any> | null,
  written?: string[],
): boolean {
  if (record[col.property] == null) return true;          // never embedded yet
  if (previous) return String(previous[col.of] ?? "") !== String(record[col.of] ?? "");
  if (written) return written.includes(col.of);
  return true;
}

/**
 * Fill the embedding columns of a row that was just written. On an update,
 * `previous` (the row before) or `written` (the keys the update set) says
 * whether the source changed, so an edit that did not touch it does not
 * re-embed it. Mutates and returns `record` with the new vectors set.
 */
export async function embedWrittenRow(
  table: any,
  record: Record<string, any> | null | undefined,
  previous?: Record<string, any> | null,
  written?: string[],
): Promise<Record<string, any> | null | undefined> {
  if (!record || record.id == null) return record;
  let cols: EmbeddingColumn[] = [];
  try { cols = embeddingColumnsFor(getTableName(table)); } catch { return record; }
  if (!cols.length) return record;
  const patch: Record<string, number[] | null> = {};
  for (const col of cols) {
    if (!(col.of in record) || !sourceChanged(col, record, previous, written)) continue;
    const value = record[col.of];
    try {
      const vector = value == null || value === ""
        ? null
        : col.source === "image" ? await embedImage(value) : await embedText(String(value));
      if (vector || record[col.property] != null) patch[col.property] = vector;
    } catch (err) {
      console.warn(`[embeddings] ${getTableName(table)}.${col.property} not embedded:`, (err as Error).message);
    }
  }
  if (!Object.keys(patch).length) return record;
  try {
    await (db as any).update(table).set(patch).where(eq(table.id, record.id));
    Object.assign(record, patch);
  } catch (err) {
    console.warn(`[embeddings] ${getTableName(table)} vector write failed:`, err);
  }
  return record;
}

/** Drop the vectors from a row on its way out: nobody reads 512 floats. */
export function stripEmbeddings<T extends Record<string, any>>(entityName: string, record: T): T {
  if (!record) return record;
  for (const col of embeddingColumnsFor(entityName)) delete (record as any)[col.property];
  return record;
}
