/**
 * File storage — pluggable backend for uploaded files (CVs, documents, images).
 *
 * Backend selection (automatic, in priority order):
 *   • Vercel Blob — when BLOB_READ_WRITE_TOKEN is set (auto-injected on
 *     Vercel-deployed apps). Uses @vercel/blob (optional dep).
 *   • S3 / object storage — when FORGE_S3_BUCKET (or AWS_S3_BUCKET) is set AND
 *     the optional `@aws-sdk/client-s3` dependency is installed.
 *   • Local disk (default) — bytes under FORGE_UPLOAD_DIR (default ./data/uploads).
 *
 * File METADATA always lives in the `forge_files` DB table; the bytes live in the
 * selected backend. A file is addressed by its row id and served from /api/files/[id].
 */
import { promises as fs } from "fs";
import path from "path";
import { randomUUID } from "crypto";
import { db } from "@/db";
import { forgeFiles } from "@/db/schema/_forge_files";
import { eq } from "drizzle-orm";
import { setFileLoader } from "@/lib/workflows/ai";
import { getSecret } from "@/lib/integrations/resolver";

export interface StoredFile {
  id: string;
  filename: string;
  contentType: string;
  size: number;
  backend: string;
  url: string;
}

// UPLOAD_DIR stays module-scope — it's a filesystem path, never a secret,
// and belongs alongside PORT/NODE_ENV, not in the integrations table.
const UPLOAD_DIR = process.env.FORGE_UPLOAD_DIR || path.join(process.cwd(), "data", "uploads");

// S3 config resolved lazily per operation so admins can change bucket /
// region / credentials from the /settings/integrations UI without a
// restart. The overhead is one DB roundtrip per file operation — fine
// for uploads (which are already expensive).
interface S3Config { bucket: string; region: string; prefix: string; }
async function loadS3Config(): Promise<S3Config> {
  const bucket = (await getSecret("s3", "FORGE_S3_BUCKET"))
    || process.env.AWS_S3_BUCKET || "";
  const region = (await getSecret("s3", "FORGE_S3_REGION"))
    || process.env.AWS_REGION || "us-east-1";
  const prefix = (await getSecret("s3", "FORGE_S3_PREFIX")) || "uploads/";
  return { bucket, region, prefix };
}

function extFor(filename: string, contentType: string): string {
  const fromName = path.extname(filename || "");
  if (fromName) return fromName;
  if (contentType.includes("pdf")) return ".pdf";
  if (contentType === "image/png") return ".png";
  if (contentType === "image/jpeg") return ".jpg";
  return "";
}

// ── S3 backend (optional) ─────────────────────────────────────────────────
// Cache is keyed on (bucket, region) — if the admin changes region from the
// UI, a new client is instantiated on the next operation. Bucket empty →
// S3 disabled → local-disk fallback.
let _s3: { mod: any; client: any; bucket: string; region: string; prefix: string } | null = null;
async function s3Client(): Promise<typeof _s3> {
  const cfg = await loadS3Config();
  if (!cfg.bucket) return null;
  if (_s3 && _s3.bucket === cfg.bucket && _s3.region === cfg.region && _s3.prefix === cfg.prefix) {
    return _s3;
  }
  try {
    // webpackIgnore: keep this a TRUE runtime-optional import. Without it the
    // bundler tries to resolve @aws-sdk/client-s3 at build time and fails the
    // whole route with "Module not found" when the (optional) dep isn't installed.
    const mod: any = await import(/* webpackIgnore: true */ "@aws-sdk/client-s3");
    _s3 = { mod, client: new mod.S3Client({ region: cfg.region }), bucket: cfg.bucket, region: cfg.region, prefix: cfg.prefix };
  } catch {
    console.warn("[storage] FORGE_S3_BUCKET set but @aws-sdk/client-s3 not installed — falling back to local disk");
    _s3 = null;
  }
  return _s3;
}

// ── Vercel Blob backend (optional) ────────────────────────────────
// Selected when BLOB_READ_WRITE_TOKEN is set — auto-injected on
// Vercel-deployed apps by the platform's deploy pipeline. Local dev
// and non-Vercel hosts fall through to S3 / local disk.
async function _blobPut(key: string, buffer: Buffer, contentType: string): Promise<string> {
  const token = process.env.BLOB_READ_WRITE_TOKEN;
  if (!token) throw new Error("BLOB_READ_WRITE_TOKEN unset");
  const mod: any = await import(/* webpackIgnore: true */ "@vercel/blob");
  const res = await mod.put(key, buffer, {
    access: "public",
    token,
    contentType,
    addRandomSuffix: false,
  });
  return res.url as string;
}

async function _blobGet(key: string): Promise<Buffer> {
  const token = process.env.BLOB_READ_WRITE_TOKEN;
  if (!token) throw new Error("BLOB_READ_WRITE_TOKEN unset");
  const mod: any = await import(/* webpackIgnore: true */ "@vercel/blob");
  // The stored `storageKey` for the blob backend is the full URL — a
  // Vercel Blob URL is a public direct link, so we fetch it as-is.
  const r = await fetch(key);
  if (!r.ok) throw new Error(`vercel blob fetch failed: ${r.status}`);
  const ab = await r.arrayBuffer();
  return Buffer.from(ab);
}

async function putBytes(key: string, buffer: Buffer, contentType: string): Promise<"blob" | "s3" | "local"> {
  // Vercel Blob wins when the token is present — that's the marker for
  // "we're on Vercel and files should live in Vercel Blob".
  if (process.env.BLOB_READ_WRITE_TOKEN) {
    try {
      const url = await _blobPut(key, buffer, contentType);
      // Stash the returned URL as the storageKey — see getBytes.
      // We can't mutate the caller's `key` so return via a side channel
      // — the saveFile wrapper below reads _lastBlobUrl.
      _lastBlobUrl = url;
      return "blob";
    } catch (err) {
      console.warn("[storage] Vercel Blob put failed, falling back:", err);
    }
  }
  const s3 = await s3Client();
  if (s3) {
    await s3.client.send(new s3.mod.PutObjectCommand({ Bucket: s3.bucket, Key: s3.prefix + key, Body: buffer, ContentType: contentType }));
    return "s3";
  }
  // Serverless read-only filesystem — Vercel Lambda and AWS Lambda both set
  // markers we can detect. Falling back to disk here produces
  // `ENOENT: mkdir '/var/task/data'` on the very first upload because Lambda's
  // cwd is read-only. Fail with an ACTIONABLE error naming the two working
  // configurations (Vercel Blob token, or S3 bucket) instead.
  if (process.env.VERCEL === "1" || process.env.LAMBDA_TASK_ROOT || process.env.AWS_LAMBDA_FUNCTION_NAME) {
    throw new Error(
      "File storage not configured for serverless. Set BLOB_READ_WRITE_TOKEN " +
      "(Vercel Blob — auto-injected when you add a Blob store in the Vercel " +
      "dashboard) OR set FORGE_S3_BUCKET + AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY. " +
      "Local disk storage does not work on Lambda's read-only filesystem."
    );
  }
  const abs = path.join(UPLOAD_DIR, key);
  await fs.mkdir(path.dirname(abs), { recursive: true });
  await fs.writeFile(abs, buffer);
  return "local";
}

// Side channel — populated by putBytes when the blob backend fires.
// Not module-safe across concurrent uploads on serverless, but each
// Vercel invocation runs in isolation so this is fine in practice.
let _lastBlobUrl: string | null = null;

async function getBytes(backend: string, key: string): Promise<Buffer> {
  if (backend === "blob") return _blobGet(key);
  if (backend === "s3") {
    const s3 = await s3Client();
    if (!s3) throw new Error("[storage] file stored in s3 but S3 backend unavailable");
    const res = await s3.client.send(new s3.mod.GetObjectCommand({ Bucket: s3.bucket, Key: s3.prefix + key }));
    const chunks: Buffer[] = [];
    for await (const c of res.Body as any) chunks.push(Buffer.from(c));
    return Buffer.concat(chunks);
  }
  return fs.readFile(path.join(UPLOAD_DIR, key));
}

// ── public API ─────────────────────────────────────────────────────────────

export async function saveFile(input: {
  buffer: Buffer;
  filename: string;
  contentType: string;
  uploadedById?: string | null;
}): Promise<StoredFile> {
  const id = randomUUID();
  const key = id + extFor(input.filename, input.contentType);
  _lastBlobUrl = null;
  const backend = await putBytes(key, input.buffer, input.contentType);
  // For the blob backend, storageKey holds the returned Vercel URL so
  // getBytes can fetch it directly. Other backends store the on-disk
  // relative key.
  const storageKey = backend === "blob" && _lastBlobUrl ? _lastBlobUrl : key;
  const size = input.buffer.length;
  await (db as any)
    .insert(forgeFiles)
    .values({
      id,
      filename: input.filename || "file",
      contentType: input.contentType || "application/octet-stream",
      size,
      backend,
      storageKey,
      uploadedById: input.uploadedById ?? null,
    });
  return { id, filename: input.filename, contentType: input.contentType, size, backend, url: `/api/files/${id}` };
}

async function metaFor(id: string): Promise<{ filename: string; contentType: string; backend: string; storageKey: string } | null> {
  const rows = await (db as any).select().from(forgeFiles).where(eq(forgeFiles.id, id)).limit(1);
  const row = Array.isArray(rows) ? rows[0] : rows;
  return row ? { filename: row.filename, contentType: row.contentType, backend: row.backend, storageKey: row.storageKey } : null;
}

export async function loadFile(id: string): Promise<{ buffer: Buffer; contentType: string; filename: string } | null> {
  const meta = await metaFor(id);
  if (!meta) return null;
  const buffer = await getBytes(meta.backend, meta.storageKey);
  return { buffer, contentType: meta.contentType, filename: meta.filename };
}

/** Base64 + media type for handing a stored file to an LLM as a document block. */
export async function loadFileBase64(id: string): Promise<{ base64: string; mediaType: string; filename: string } | null> {
  const f = await loadFile(id);
  if (!f) return null;
  return { base64: f.buffer.toString("base64"), mediaType: f.contentType, filename: f.filename };
}

/** Wire ai_extract's file loader to storage (called once at boot). */
export function registerFileStorage(): void {
  setFileLoader(async (ref: string) => {
    try {
      return await loadFileBase64(ref);
    } catch (err) {
      console.warn("[storage] loadFileBase64 failed for", ref, err);
      return null;
    }
  });
}
