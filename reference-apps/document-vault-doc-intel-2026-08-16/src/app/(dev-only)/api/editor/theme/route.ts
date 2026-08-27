import { NextRequest, NextResponse } from "next/server";
import { defaultTokens } from "@tentoroforge/library";
import { writeFile, readFile, mkdir } from "fs/promises";
import path from "path";

const CUSTOM_PATH = path.resolve(process.cwd(), "src/theme/tokens.custom.json");

export async function GET() {
  try {
    const text = await readFile(CUSTOM_PATH, "utf8");
    const custom = JSON.parse(text);
    const merged = mergeTokens(defaultTokens as any, custom);
    return NextResponse.json({ tokens: merged, source: "custom" });
  } catch {
    return NextResponse.json({ tokens: defaultTokens, source: "default" });
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const tokens = body.tokens;
  if (!tokens || typeof tokens !== "object") {
    return NextResponse.json({ ok: false, error: "tokens required" }, { status: 422 });
  }
  await mkdir(path.dirname(CUSTOM_PATH), { recursive: true });
  const tmp = `${CUSTOM_PATH}.tmp.${Date.now()}`;
  await writeFile(tmp, JSON.stringify(tokens, null, 2), "utf8");
  const { rename } = await import("fs/promises");
  await rename(tmp, CUSTOM_PATH);
  return NextResponse.json({ ok: true });
}

function mergeTokens(a: any, b: any): any {
  const out: any = {};
  for (const group of new Set([...Object.keys(a), ...Object.keys(b)])) {
    out[group] = { ...(a[group] ?? {}), ...(b[group] ?? {}) };
  }
  return out;
}
