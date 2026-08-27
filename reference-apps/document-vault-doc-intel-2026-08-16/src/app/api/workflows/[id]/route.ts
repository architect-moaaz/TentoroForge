/**
 * Workflow Detail API — serves a single workflow definition.
 * GET /api/workflows/[id] → full workflow JSON with nodes, edges, processVariables
 */
import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const wfDir = path.join(process.cwd(), "workflows");
    const files = await fs.readdir(wfDir).catch(() => [] as string[]);

    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      try {
        const content = await fs.readFile(path.join(wfDir, file), "utf-8");
        const wf = JSON.parse(content);
        if (wf.id === id || file.replace(".json", "") === id) {
          return NextResponse.json(wf);
        }
      } catch { /* skip */ }
    }

    return NextResponse.json(
      { error: "Workflow not found" },
      { status: 404 },
    );
  } catch (error) {
    return NextResponse.json(
      { error: String(error) },
      { status: 500 },
    );
  }
}
