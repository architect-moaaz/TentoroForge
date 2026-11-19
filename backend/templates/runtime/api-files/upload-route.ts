/**
 * POST /api/files/upload — accepts multipart/form-data with a `file` field,
 * stores the bytes via the storage backend, and returns the file reference
 * { id, url, filename, contentType, size }. Forge runtime — do not remove.
 */
import { saveFile } from "@/lib/storage";

export const runtime = "nodejs";

/**
 * WHAT MAY BE UPLOADED. A file is served back under the type it was uploaded
 * with, so an uploaded web page or script was one click from running inside
 * another person's signed-in session. Only the kinds an application takes as
 * a document or a picture are kept: photos, PDFs, plain text, office files, and audio, video and zip archives (kept and
 * downloaded, never served as a page: see download-route.ts). A file is at most MAX_BYTES.
 * Pages, scripts, SVG (it can carry script) and programs are refused by their
 * declared type AND by their file name, whichever disagrees.
 */
const ALLOWED_TYPE =
  /^(image\/(png|jpe?g|gif|webp|avif|heic|heif)|application\/pdf|(audio|video)\/[a-z0-9.+-]+|text\/(plain|csv)|application\/(zip|x-zip-compressed|msword|vnd\.ms-(excel|powerpoint)|vnd\.openxmlformats-officedocument\.[a-z.]+|octet-stream))$/i;
const BLOCKED_NAME = /\.(html?|xhtml|svg|svgz|xml|js|mjs|cjs|jsx|tsx?|php\d?|phtml|asp|aspx|jsp|exe|dll|bat|cmd|sh|ps1|vbs|jar|py|rb|pl|swf|apk|msi)$/i;
const MAX_BYTES = 15 * 1024 * 1024;

export async function POST(req: Request): Promise<Response> {
  try {
    const form = await req.formData();
    const file = form.get("file");
    if (!(file instanceof File)) {
      return Response.json({ error: "Expected a 'file' field in multipart/form-data." }, { status: 400 });
    }
    const name = file.name || "upload";
    const type = (file.type || "application/octet-stream").toLowerCase();
    if (BLOCKED_NAME.test(name) || !ALLOWED_TYPE.test(type)) {
      return Response.json({ error: "That kind of file is not allowed. Use a photo (PNG, JPG, WebP), a PDF or an office document." }, { status: 415 });
    }
    if (file.size > MAX_BYTES) {
      return Response.json({ error: "That file is too large. The limit is 15 MB." }, { status: 413 });
    }
    const buffer = Buffer.from(await file.arrayBuffer());
    const saved = await saveFile({
      buffer,
      filename: name,
      contentType: type,
      uploadedById: null,
    });
    return Response.json(saved);
  } catch (err) {
    console.error("[api/files/upload]", err);
    return Response.json({ error: "That file could not be saved. Try again." }, { status: 500 });
  }
}
