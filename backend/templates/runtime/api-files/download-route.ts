/**
 * GET /api/files/[id] — streams a stored file's bytes with its content type.
 * Forge runtime — do not remove.
 */
import { loadFile } from "@/lib/storage";

export const runtime = "nodejs";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await params;
  const f = await loadFile(id);
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
  // A FILE IS NEVER ALLOWED TO RUN AS A PAGE. Only a picture or a PDF is shown
  // inline; anything else downloads. `nosniff` stops a browser re-deciding the
  // type from the bytes, and the sandbox policy stops even an inline file from
  // running script in this origin.
  const inlineOk = /^(image\/(png|jpe?g|gif|webp|avif|heic|heif)|application\/pdf)$/i.test(f.contentType);
  return new Response(new Uint8Array(f.buffer), {
    headers: {
      "Content-Type": inlineOk ? f.contentType : "application/octet-stream",
      "Content-Disposition": `${inlineOk ? "inline" : "attachment"}; filename="${asciiName}"; filename*=UTF-8''${utf8Name}`,
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'",
      "Cache-Control": "private, max-age=3600",
    },
  });
}
