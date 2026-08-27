// (dev-only) — excluded from production builds via next.config.ts webpack null-loader rule.
import { NextRequest, NextResponse } from "next/server";
import { readFile } from "fs/promises";
import path from "path";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const schemaPath = url.searchParams.get("path");
  if (!schemaPath) return NextResponse.json({ error: "missing path" }, { status: 400 });

  // Handle _layouts/<name> paths — load directly from the library's exported layouts map
  if (schemaPath.startsWith("_layouts/")) {
    const name = schemaPath.slice("_layouts/".length);
    const { layouts } = await import("@tentoroforge/library");
    const tpl = (layouts as Record<string, unknown>)[name];
    if (!tpl) return NextResponse.json({ error: "layout not found" }, { status: 404 });
    return NextResponse.json({ schema: tpl });
  }

  const target = path.resolve(process.cwd(), "src/schemas", `${schemaPath}.json`);
  try {
    const text = await readFile(target, "utf8");
    return NextResponse.json({ schema: JSON.parse(text) });
  } catch {
    return NextResponse.json({ error: "schema not found" }, { status: 404 });
  }
}
