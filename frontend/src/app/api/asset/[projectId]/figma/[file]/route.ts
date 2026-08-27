import { NextRequest, NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";
import { resolveProject } from "@/lib/resolveProject";

/**
 * Serve per-project Figma assets from output/<projectId>/public/figma/<file>.
 *
 * Schema Image / Icon nodes carry `src="/api/asset/<id>/figma/<hash>.svg"` —
 * the editor canvas renders them via this route so SVGs extracted by the
 * deterministic Figma mapper actually appear in the editor preview, not
 * just in the scaffold's standalone render.
 *
 * Mirrors apps/render-scaffold/src/app/api/asset/[projectId]/figma/[file]/route.ts
 * — keep the two in sync.
 */
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ projectId: string; file: string }> },
): Promise<NextResponse> {
  const { projectId, file } = await params;

  let projectRoot: string;
  try {
    projectRoot = resolveProject(projectId);
  } catch {
    return new NextResponse("Not found", { status: 404 });
  }

  if (!file || file.includes("/") || file.includes("..") || file.startsWith(".")) {
    return new NextResponse("Not found", { status: 404 });
  }

  const assetPath = path.join(projectRoot, "public", "figma", file);

  let data: Buffer;
  try {
    data = await fs.readFile(assetPath);
  } catch {
    return new NextResponse("Not found", { status: 404 });
  }

  const ext = path.extname(file).toLowerCase();
  const contentType =
    ext === ".svg"
      ? "image/svg+xml"
      : ext === ".png"
        ? "image/png"
        : ext === ".jpg" || ext === ".jpeg"
          ? "image/jpeg"
          : ext === ".webp"
            ? "image/webp"
            : "application/octet-stream";

  return new NextResponse(data, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=86400, immutable",
    },
  });
}
