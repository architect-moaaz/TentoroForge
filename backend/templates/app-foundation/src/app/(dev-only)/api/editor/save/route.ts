// (dev-only) — excluded from production builds via next.config.ts webpack null-loader rule.
import { NextRequest, NextResponse } from "next/server";
import { Page, validateCrossRefs, type ValidationContext } from "@tentoroforge/schema";
import { writeFile, rename, readFile, mkdir } from "fs/promises";
import path from "path";
import { libraryRegistry } from "@/lib/library-registry";
import { tokens } from "@/theme/tokens.server";

async function loadValidationContext(): Promise<ValidationContext> {
  const entities = new Set<string>();
  const workflows = new Set<string>();
  const libraryNames = new Set(libraryRegistry.list().map((e: any) => e.name));
  const tokenSet = new Set<string>();
  for (const group of Object.values(tokens)) {
    for (const name of Object.keys(group as any)) tokenSet.add(name);
  }
  // Phase 2A: entities and workflows are read from a known JSON manifest if present
  // (foundation generation produces a registry.json; if missing, we degrade to "any name allowed").
  try {
    const manifest = JSON.parse(
      await readFile(path.resolve(process.cwd(), "registry.json"), "utf8")
    );
    for (const e of manifest.entities ?? []) entities.add(e.name ?? e);
    for (const w of manifest.workflows ?? []) workflows.add(w.name ?? w);
  } catch {
    // No manifest — skip cross-ref entity/workflow checks (still validates library + tokens)
  }
  return { entities, workflows, libraryNames, tokens: tokenSet };
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { path: schemaPath, schema } = body;

  // Handle _layouts/<name> paths — write to library's layouts directory.
  // In dev mode with workspace symlinks, require.resolve traverses the symlink to the real package.
  if (schemaPath?.startsWith("_layouts/")) {
    const name = (schemaPath as string).slice("_layouts/".length);
    // Use a hardcoded workspace-relative path for dev; documented limitation for production deploys.
    const libRoot = path.resolve(process.cwd(), "node_modules/@tentoroforge/library");
    const target = path.resolve(libRoot, "src/layouts", `${name}.json`);
    await mkdir(path.dirname(target), { recursive: true });
    const tmp = `${target}.tmp.${Date.now()}`;
    await writeFile(tmp, JSON.stringify(schema, null, 2), "utf8");
    await rename(tmp, target);
    return NextResponse.json({ ok: true, savedSchema: schema, suggestions: [], autoApplied: [] });
  }

  // 1. Zod parse
  const parse = Page.safeParse(schema);
  if (!parse.success) {
    return NextResponse.json(
      {
        ok: false,
        errors: parse.error.errors.map((e) => ({ path: e.path, message: e.message })),
      },
      { status: 422 }
    );
  }

  // 2. Cross-ref validate
  const ctx = await loadValidationContext();
  const xrefErrors = validateCrossRefs(parse.data, ctx);
  // Skip entity/workflow errors if their sets are empty (no manifest — manifest not yet generated)
  const blockingErrors = xrefErrors.filter((e) => {
    if (ctx.entities.size === 0 && e.message.includes("entity")) return false;
    if (ctx.workflows.size === 0 && e.message.includes("workflow")) return false;
    return true;
  });
  if (blockingErrors.length) {
    return NextResponse.json({ ok: false, errors: blockingErrors }, { status: 422 });
  }

  // 3. Atomic write: write to .tmp then rename to avoid partial-write corruption
  const target = path.resolve(process.cwd(), "src/schemas", `${schemaPath}.json`);
  const tmp = `${target}.tmp.${Date.now()}`;
  await writeFile(tmp, JSON.stringify(parse.data, null, 2), "utf8");
  await rename(tmp, target);

  // 4. LLM follow-up (stub in Phase 2A — calls FastAPI if FASTAPI_URL env is set, else skips).
  // Phase 2E replaces this stub with the real LLM-driven schema-followup agent.
  let followup: any = { suggestions: [], autoApplied: [] };
  try {
    const url = process.env.FASTAPI_URL
      ? `${process.env.FASTAPI_URL}/agents/schema-followup`
      : null;
    if (url) {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schemaPath, schema: parse.data }),
      });
      if (r.ok) followup = await r.json();
    }
  } catch {
    // Follow-up is best-effort — never block the save on a FastAPI failure
  }

  return NextResponse.json({
    ok: true,
    savedSchema: parse.data,
    suggestions: followup.suggestions ?? [],
    autoApplied: followup.autoApplied ?? [],
  });
}
