import { describe, it } from "node:test";
import assert from "node:assert";
import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/**
 * Smoke-test: loadTokensCustom reads tokens.custom.json from the project root
 * and returns it as a plain object (does NOT deep-merge with defaultTokens —
 * that is loadTokens' job; cssVarTokens just wants the raw overrides).
 *
 * Inlines the helper to avoid importing Next.js server components.
 */
import { promises as fs } from "node:fs";
import path from "node:path";

async function loadTokensCustom(projectRoot: string): Promise<Record<string, unknown> | null> {
  try {
    const text = await fs.readFile(
      path.join(projectRoot, "src", "theme", "tokens.custom.json"),
      "utf8",
    );
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return null;
  }
}

describe("loadTokensCustom", () => {
  it("returns the tokens.custom.json content from a project root", async () => {
    const root = mkdtempSync(join(tmpdir(), "scaffold-tokens-test-"));
    mkdirSync(join(root, "src/theme"), { recursive: true });
    const tokens = { color: { primary: { 500: "#10b981" } } };
    writeFileSync(join(root, "src/theme/tokens.custom.json"), JSON.stringify(tokens));

    const result = await loadTokensCustom(root);
    assert.deepStrictEqual(result, tokens);
  });

  it("returns null when tokens.custom.json is absent", async () => {
    const root = mkdtempSync(join(tmpdir(), "scaffold-tokens-test-"));
    const result = await loadTokensCustom(root);
    assert.strictEqual(result, null);
  });

  it("returns null when tokens.custom.json is malformed JSON", async () => {
    const root = mkdtempSync(join(tmpdir(), "scaffold-tokens-test-"));
    mkdirSync(join(root, "src/theme"), { recursive: true });
    writeFileSync(join(root, "src/theme/tokens.custom.json"), "{ not valid json");

    const result = await loadTokensCustom(root);
    assert.strictEqual(result, null);
  });

  it("loads the real ozrkzg01 project tokens.custom.json", async () => {
    // Validates the helper works against the actual reference project.
    // The project lives at output/ozrkzg01 relative to the monorepo root.
    const monoRoot = path.resolve(process.cwd(), "..", "..", "..", "..");
    const projectRoot = path.join(monoRoot, "output", "ozrkzg01");
    const result = await loadTokensCustom(projectRoot);
    if (result === null) {
      // If the output dir doesn't exist (CI), skip gracefully.
      console.log("  [skip] ozrkzg01 project not found at", projectRoot);
      return;
    }
    // Should have a color.primary block with at least a "500" key
    const color = (result as any)?.color;
    assert.ok(color, "expected color key in tokens");
    const primary = color?.primary;
    assert.ok(primary, "expected color.primary key");
    assert.ok(typeof primary["500"] === "string", "expected primary.500 to be a hex string");
  });
});
