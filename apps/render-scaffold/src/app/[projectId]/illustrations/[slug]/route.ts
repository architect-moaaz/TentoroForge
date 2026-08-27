/**
 * Per-project illustration server route.
 *
 * Resolves /p/<projectId>/illustrations/<slug>.svg to
 * <output>/<projectId>/public/illustrations/<slug>.svg on disk and streams
 * it back with image/svg+xml content type. This is the scaffold-side
 * counterpart to the backend's matching FastAPI route in
 * backend/routers/output_projects.py — having it locally means the scaffold
 * can serve SVGs without a backend round-trip for fastest preview.
 *
 * The slug param arrives WITHOUT the .svg suffix because Next.js dynamic
 * segments stop at "/" only; ".svg" is part of the segment text. We strip
 * a trailing .svg defensively so both /illustrations/foo and
 * /illustrations/foo.svg resolve identically.
 */
import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";
import { resolveProject } from "@/lib/resolveProject";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ projectId: string; slug: string }> },
) {
  const { projectId, slug } = await params;
  const cleanSlug = slug.replace(/\.svg$/i, "");
  // Reject any traversal attempts before hitting the filesystem.
  if (cleanSlug.includes("/") || cleanSlug.includes("..") || cleanSlug.startsWith(".")) {
    return new NextResponse("invalid slug", { status: 400 });
  }
  try {
    const root = resolveProject(projectId);
    const svgPath = path.join(root, "public", "illustrations", `${cleanSlug}.svg`);
    const svg = await fs.readFile(svgPath, "utf8");
    return new NextResponse(svg, {
      headers: {
        "content-type": "image/svg+xml",
        "cache-control": "public, max-age=60",
      },
    });
  } catch {
    return new NextResponse("not found", { status: 404 });
  }
}
