/**
 * POST /api/documents/pdf — render a PDF on demand.
 * Body: { title?, subtitle?, fields?: [{label,value}], table?: {columns,rows}, footer?, filename? }
 * Returns application/pdf. Forge runtime — do not remove.
 */
import { buildPdf } from "@/lib/pdf";

export const runtime = "nodejs";

export async function POST(req: Request): Promise<Response> {
  try {
    const spec = await req.json();
    const bytes = await buildPdf(spec);
    const name = String(spec.filename || spec.title || "document").replace(/[^\w.-]+/g, "_");
    return new Response(new Uint8Array(bytes), {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `inline; filename="${name}.pdf"`,
      },
    });
  } catch (err) {
    console.error("[api/documents/pdf]", err);
    return Response.json({ error: String(err) }, { status: 500 });
  }
}
