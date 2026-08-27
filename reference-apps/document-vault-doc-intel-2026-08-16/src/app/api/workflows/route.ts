/**
 * Workflow List API — serves workflow definitions from workflows/*.json.
 * GET /api/workflows → all workflows
 */
import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export async function GET() {
  try {
    const wfDir = path.join(process.cwd(), "workflows");
    const files = await fs.readdir(wfDir).catch(() => [] as string[]);
    const workflows = [];

    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      try {
        const content = await fs.readFile(path.join(wfDir, file), "utf-8");
        const wf = JSON.parse(content);
        workflows.push({
          id: wf.id,
          name: wf.name,
          description: wf.description,
          trigger: wf.definition?.trigger,
          nodeCount: wf.definition?.nodes?.length ?? 0,
          processVariableCount: wf.processVariables?.length ?? 0,
        });
      } catch { /* skip invalid files */ }
    }

    return NextResponse.json(workflows);
  } catch (error) {
    return NextResponse.json([], { status: 200 });
  }
}
