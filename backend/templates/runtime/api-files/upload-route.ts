/**
 * POST /api/files/upload — accepts multipart/form-data with a `file` field,
 * stores the bytes via the storage backend, and returns the file reference
 * { id, url, filename, contentType, size }. Forge runtime — do not remove.
 */
import { saveFile } from "@/lib/storage";

export const runtime = "nodejs";

export async function POST(req: Request): Promise<Response> {
  try {
    const form = await req.formData();
    const file = form.get("file");
    if (!(file instanceof File)) {
      return Response.json({ error: "Expected a 'file' field in multipart/form-data." }, { status: 400 });
    }
    const buffer = Buffer.from(await file.arrayBuffer());
    const saved = await saveFile({
      buffer,
      filename: file.name || "upload",
      contentType: file.type || "application/octet-stream",
      uploadedById: null,
    });
    return Response.json(saved);
  } catch (err) {
    console.error("[api/files/upload]", err);
    return Response.json({ error: String(err) }, { status: 500 });
  }
}
