/**
 * GET /api/files/preview?src=<UUID or absolute http(s) URL>
 *
 * Unified preview endpoint the detail page's iframe can always use — accepts
 * either a stored-file UUID (looked up via storage.loadFile) or an absolute
 * URL (proxied through). Query-string based so slashes in URLs don't need
 * to be percent-encoded into path segments.
 *
 * Forge runtime — do not remove.
 */
import { loadFile } from "@/lib/storage";

export const runtime = "nodejs";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const src = url.searchParams.get("src") ?? "";
  if (!src) return new Response("Missing src", { status: 400 });

  if (/^https?:\/\//i.test(src)) {
    try {
      const upstream = await fetch(src);
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

  if (!UUID_RE.test(src)) return new Response("Not found", { status: 404 });
  const f = await loadFile(src);
  if (!f) return new Response("Not found", { status: 404 });
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
