import { NextResponse } from "next/server";
import { readdir } from "fs/promises";
import path from "path";
import { layouts as libraryLayouts } from "@tentoroforge/library";

async function walk(dir: string, base: string, out: string[]): Promise<void> {
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) await walk(full, base, out);
    else if (entry.name.endsWith(".json")) {
      const rel = path.relative(base, full);
      out.push(rel.replace(/\.json$/, "").split(path.sep).join("/"));
    }
  }
}

export async function GET() {
  const root = path.resolve(process.cwd(), "src/schemas");
  const paths: string[] = [];
  try {
    await walk(root, root, paths);
  } catch {
    // src/schemas may not exist yet — return only layouts
  }
  paths.sort();

  // Append _layouts/* entries derived from the library's exported layouts map
  const layoutPaths = Object.keys(libraryLayouts).map((name) => `_layouts/${name}`);

  return NextResponse.json({ paths: [...paths, ...layoutPaths] });
}
