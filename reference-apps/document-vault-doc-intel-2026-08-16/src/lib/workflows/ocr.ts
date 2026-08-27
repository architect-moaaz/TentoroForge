/**
 * PaddleOCR sidecar handler for the workflow runtime — action type
 * ``ocr_document``. First-class OCR primitive for banking / healthcare /
 * document-intelligence apps that need on-prem OCR with bounding boxes and
 * an audit trail (no cloud LLM round-trip).
 *
 * Sidecar contract (documented once here, checked into the sidecar README):
 *
 *   POST {PADDLEOCR_URL}/ocr
 *   Authorization: Bearer {PADDLEOCR_API_KEY}   (only when the key is set)
 *   Content-Type: application/json
 *   Body — one of:
 *     { file_url: string, pages?: number[], language?: string }
 *     { file_b64: string, mime_type: string, filename?: string,
 *       pages?: number[], language?: string }
 *
 *   200 OK
 *   { text: string,
 *     pageCount: number,
 *     confidence: number,           // 0..1, mean across blocks
 *     blocks: [{ text, bbox: [x, y, w, h], confidence, page }] }
 *
 * Auto-fallback: when the resolved input is an http(s) URL the handler
 * sends ``{file_url}`` (sidecar fetches it — right for co-located stores
 * behind the same network). Otherwise it loads the bytes via the
 * shared file loader (same registration ai_extract uses) and sends
 * ``{file_b64}``. Either path works with any PaddleOCR wrapper that
 * follows the contract above.
 *
 * Config contract (canonical, aliases accepted for editor↔generator parity):
 *   ocrFileRef       — the file to OCR. String URL / stored-file id /
 *                      FileUpload descriptor / {{binding}}.
 *   ocrPages         — optional list of 1-indexed page numbers to OCR.
 *                      Omit for "all pages". Number or [numbers] accepted.
 *   ocrLanguage      — optional ISO 639-1 code (e.g. "en", "zh", "ar").
 *                      PaddleOCR uses this to pick the right recognition
 *                      model. Sidecar's default when absent.
 *
 * Output written to ctx.variables (so downstream db_insert can bind them):
 *   text, blocks, pageCount, confidence — top-level for `{{text}}` etc.
 *   Also returned under `data` so the generic contract-output mapping
 *   picks it up when no explicit field is named.
 */
import { registerActionHandler } from "./engine";
import { getStoredFile, type FileDescriptor } from "./ai";
import type { NodeConfig, WorkflowExecutionContext } from "./types";

type Cfg = Record<string, any>;

// ── variable resolution (same shape as ai.ts uses) ─────────────────────
// Kept local so ocr.ts is drop-in without depending on ai.ts's private
// helpers. Nested-path aware; a lone `{{token}}` returns the RAW value
// (may be a descriptor object).

const SINGLE_TOKEN = /^\s*\{\{\s*([\w.[\]]+)\s*\}\}\s*$/;

function getPath(obj: any, pathStr: string): unknown {
  return String(pathStr)
    .replace(/\[(\w+)\]/g, ".$1")
    .split(".")
    .filter(Boolean)
    .reduce((acc: any, k) => (acc == null ? acc : acc[k]), obj);
}

function resolveValue(ref: unknown, vars: Record<string, unknown>): unknown {
  if (typeof ref !== "string") return ref;
  const single = ref.match(SINGLE_TOKEN);
  if (single) {
    const v = getPath(vars, single[1]);
    return v === undefined ? "" : v;
  }
  if (ref.includes("{{")) {
    return ref.replace(/\{\{\s*([\w.[\]]+)\s*\}\}/g, (_m, k) => {
      const v = getPath(vars, k);
      return v == null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
    });
  }
  if (Object.prototype.hasOwnProperty.call(vars, ref)) return vars[ref];
  return ref;
}

// ── file → sidecar body shape ──────────────────────────────────────────
// A resolved ocrFileRef can be:
//   (a) An http(s) URL string  → send {file_url} (sidecar fetches).
//   (b) A stored-file id       → load via getStoredFile, send {file_b64}.
//   (c) A FileUpload descriptor {id, ...} → same as (b) via desc.id.
//   (d) A raw descriptor {base64, mediaType, filename} → send {file_b64}.

type SidecarBody =
  | { file_url: string; pages?: number[]; language?: string }
  | { file_b64: string; mime_type: string; filename?: string; pages?: number[]; language?: string };

async function resolveDescriptor(ref: unknown): Promise<FileDescriptor | null> {
  if (ref == null || ref === "") return null;
  // Raw descriptor object — e.g. from ai.ts's __forgeFile wrapper.
  if (typeof ref === "object") {
    const desc: any = (ref as any).__forgeFile ?? ref;
    if (desc && typeof desc === "object") {
      const base64 = desc.base64 ?? desc.data;
      const mediaType = desc.mediaType ?? desc.media_type ?? desc.contentType;
      if (typeof base64 === "string" && typeof mediaType === "string") {
        return { base64, mediaType, filename: desc.filename };
      }
      if (typeof desc.id === "string") {
        return await getStoredFile(desc.id);
      }
    }
    return null;
  }
  // String id (or JSON-encoded id / descriptor).
  if (typeof ref === "string") {
    const s = ref.trim();
    if (s.startsWith("{") || s.startsWith("[")) {
      try {
        return await resolveDescriptor(JSON.parse(s));
      } catch {
        /* fall through */
      }
    }
    return await getStoredFile(s);
  }
  return null;
}

function isHttpUrl(ref: unknown): ref is string {
  if (typeof ref !== "string") return false;
  const s = ref.trim();
  return /^https?:\/\//i.test(s);
}

function normalizePages(raw: unknown): number[] | undefined {
  if (raw == null || raw === "") return undefined;
  const arr = Array.isArray(raw) ? raw : [raw];
  const out: number[] = [];
  for (const v of arr) {
    const n = typeof v === "number" ? v : Number(String(v).trim());
    if (Number.isFinite(n) && n > 0 && Number.isInteger(n)) out.push(n);
  }
  return out.length ? out : undefined;
}

// ── the handler ────────────────────────────────────────────────────────

export async function ocrDocument(
  config: NodeConfig,
  ctx: WorkflowExecutionContext,
): Promise<Record<string, unknown>> {
  const c = config as Cfg;
  const vars = (ctx.variables ?? {}) as Record<string, unknown>;

  // Credentials via getSecret — admin can override env from the /settings/
  // integrations UI without restart. URL is required; API key optional.
  const { getSecret } = await import("@/lib/integrations/resolver");
  const url = (await getSecret("paddleocr", "PADDLEOCR_URL")) || "";
  const apiKey = (await getSecret("paddleocr", "PADDLEOCR_API_KEY")) || "";

  const emptyResult: Record<string, unknown> = {
    text: "",
    blocks: [] as unknown[],
    pageCount: 0,
    confidence: 0,
    data: null,
    output: "",
  };

  if (!url) {
    const isProd =
      process.env.NODE_ENV === "production" || process.env.FORGE_OCR_STRICT === "1";
    if (isProd) {
      throw new Error(
        "OCR not configured — set PADDLEOCR_URL (via env or /settings/integrations)",
      );
    }
    console.log(
      "[workflow] No PADDLEOCR_URL — ocr_document returns empty result (dev)",
    );
    return emptyResult;
  }

  const fileRefRaw = c.ocrFileRef ?? c.aiFileRef ?? c.file ?? "{{input}}";
  const fileRef = resolveValue(fileRefRaw, vars);
  const pages = normalizePages(resolveValue(c.ocrPages, vars));
  const language = (() => {
    const v = resolveValue(c.ocrLanguage ?? c.language, vars);
    return typeof v === "string" && v ? v : undefined;
  })();

  let body: SidecarBody;
  if (isHttpUrl(fileRef)) {
    // Sidecar fetches — right when the store is co-located.
    body = { file_url: fileRef };
  } else {
    // Fallback: load bytes here and send them along.
    const desc = await resolveDescriptor(fileRef);
    if (!desc || !desc.base64) {
      // No file to OCR — return empty rather than 500 the workflow.
      console.warn("[workflow] ocr_document: could not resolve file", fileRefRaw);
      return emptyResult;
    }
    body = {
      file_b64: desc.base64,
      mime_type: desc.mediaType || "application/octet-stream",
      filename: desc.filename,
    };
  }
  if (pages) body.pages = pages;
  if (language) body.language = language;

  // Endpoint — accept URLs with or without a trailing /ocr so the operator
  // can point at the sidecar root and we append, or at a full endpoint.
  const endpoint = url.replace(/\/$/, "") + (url.endsWith("/ocr") ? "" : "/ocr");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

  let payload: any;
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`sidecar ${res.status}: ${text.slice(0, 200)}`);
    }
    payload = await res.json();
  } catch (err) {
    console.warn("[workflow] ocr_document sidecar call failed:", err);
    return emptyResult;
  }

  const text = typeof payload?.text === "string" ? payload.text : "";
  const blocks = Array.isArray(payload?.blocks) ? payload.blocks : [];
  const pageCount =
    typeof payload?.pageCount === "number"
      ? payload.pageCount
      : typeof payload?.page_count === "number"
        ? payload.page_count
        : 0;
  const confidence =
    typeof payload?.confidence === "number" ? payload.confidence : 0;

  // Expose top-level vars so a downstream db_insert can bind directly
  // (values: { ocr_text: "{{text}}", block_count: "{{blocks.length}}" }).
  const reserved = new Set(["input", "user", "trigger", "now"]);
  const varsOut = ctx.variables as Record<string, unknown>;
  if (!reserved.has("text")) varsOut.text = text;
  if (!reserved.has("blocks")) varsOut.blocks = blocks;
  if (!reserved.has("pageCount")) varsOut.pageCount = pageCount;
  if (!reserved.has("confidence")) varsOut.confidence = confidence;

  return {
    text,
    blocks,
    pageCount,
    confidence,
    data: { text, blocks, pageCount, confidence },
    output: text,
  };
}

export function registerOcrActions(): void {
  registerActionHandler("ocr_document", ocrDocument as any);
}
