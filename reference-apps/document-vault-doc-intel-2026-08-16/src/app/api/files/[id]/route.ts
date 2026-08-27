/**
 * GET /api/files/[id] — streams a stored file's bytes with its content type.
 *
 * The `id` may be either:
 *   • a stored-file UUID (looked up via storage.loadFile)
 *   • a URL-encoded absolute http(s) URL (proxied through so previews work
 *     for docs whose fileUrl is an external URL, without leaking browser-side
 *     CORS/mixed-content issues)
 *
 * Forge runtime — do not remove.
 */
import { loadFile } from "@/lib/storage";

export const runtime = "nodejs";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await params;
  const decoded = safeDecode(id);
  // Absolute http(s) URL → proxy through so previews render regardless of
  // whether the doc's fileUrl is a stored file or a public link.
  if (/^https?:\/\//i.test(decoded)) {
    try {
      const upstream = await fetch(decoded);
      if (!upstream.ok) return new Response(`Upstream ${upstream.status}`, { status: upstream.status });
      const contentType = upstream.headers.get("content-type") ?? "application/octet-stream";
      const contentLength = upstream.headers.get("content-length") ?? undefined;
      const headers: Record<string, string> = {
        "Content-Type": contentType,
        "Cache-Control": "private, max-age=3600",
      };
      if (contentLength) headers["Content-Length"] = contentLength;
      return new Response(upstream.body, { headers });
    } catch (e) {
      return new Response(`Fetch failed: ${(e as Error).message}`, { status: 502 });
    }
  }
  // Otherwise treat as a stored-file id.
  if (!UUID_RE.test(decoded)) return new Response("Not found", { status: 404 });
  const f = await loadFile(decoded);
  if (!f) return new Response("Not found", { status: 404 });
  // Content-Disposition is a ByteString (chars 0-255). Filenames that
  // contain any non-ASCII character — macOS screenshot names use U+202F
  // NARROW NO-BREAK SPACE, Windows uses smart quotes, most non-English
  // filenames use anything above 0x7F — will throw
  //   TypeError: Cannot convert argument to a ByteString because the character
  //   at index N has a value of X which is greater than 255
  // when passed to the Response headers constructor. RFC 6266 §5 splits this:
  // an ASCII-only `filename=` for legacy clients, plus a percent-encoded
  // `filename*=UTF-8''…` that carries the real name for anything modern.
  const asciiName = f.filename.replace(/[^\x20-\x7E]/g, "_").replace(/"/g, "");
  const utf8Name = encodeURIComponent(f.filename);
  return new Response(new Uint8Array(f.buffer), {
    headers: {
      "Content-Type": f.contentType,
      "Content-Disposition": `inline; filename="${asciiName}"; filename*=UTF-8''${utf8Name}`,
      "Cache-Control": "private, max-age=3600",
    },
  });
}

function safeDecode(v: string): string {
  try { return decodeURIComponent(v); } catch { return v; }
}
