/**
 * Run the runtime templates under plain `node`, unmodified.
 *
 * These files are written for Next.js: they import `@/db`, `drizzle-orm` and
 * per-app manifests that only exist inside a generated app, and every relative
 * import is extensionless. None of that resolves here, and this repo has no
 * bundler and no node_modules — which is why the older runtime tests inline a
 * copy of the code they check, and why those copies drift.
 *
 * Node's own module hooks close the gap with no build step: `resolve` supplies
 * the missing modules and adds the extension the templates omit, so the file
 * under test is the file that ships.
 */

import { registerHooks } from "node:module";
import { existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve as resolvePath } from "node:path";

export interface HarnessOptions {
  /** Bare specifier -> module source, compiled in place of the real thing. */
  stubs?: Record<string, string>;
  /** Bare or relative specifier -> an absolute file path to load instead. */
  redirect?: Record<string, string>;
}

/** Resolve an extensionless relative import to the file it means. */
function withExtension(specifier: string, parentURL: string | undefined): string | null {
  if (!specifier.startsWith(".") || !parentURL) return null;
  const base = resolvePath(dirname(fileURLToPath(parentURL)), specifier);
  for (const candidate of [`${base}.ts`, `${base}.mts`, `${base}/index.ts`]) {
    if (existsSync(candidate)) return pathToFileURL(candidate).href;
  }
  return null;
}

export function installHarness(opts: HarnessOptions = {}): void {
  const stubs = opts.stubs ?? {};
  const redirect = opts.redirect ?? {};

  registerHooks({
    resolve(specifier: string, context: any, nextResolve: any) {
      if (specifier in stubs) {
        return { url: `stub:${specifier}`, shortCircuit: true };
      }
      if (specifier in redirect) {
        return { url: pathToFileURL(resolvePath(redirect[specifier])).href, shortCircuit: true };
      }
      const withExt = withExtension(specifier, context?.parentURL);
      if (withExt) return { url: withExt, shortCircuit: true };
      return nextResolve(specifier, context);
    },
    load(url: string, context: any, nextLoad: any) {
      if (url.startsWith("stub:")) {
        return { format: "module", source: stubs[url.slice(5)], shortCircuit: true };
      }
      return nextLoad(url, context);
    },
  });
}

// ── Assertions ─────────────────────────────────────────────────────────────

let failures = 0;

export function ok(cond: unknown, name: string): void {
  if (cond) { console.log(`  ✓ ${name}`); return; }
  console.error(`  ✗ ${name}`); failures++;
}

export function eqJson(actual: unknown, expected: unknown, name: string): void {
  if (JSON.stringify(actual) === JSON.stringify(expected)) {
    console.log(`  ✓ ${name}`);
    return;
  }
  console.error(
    `  ✗ ${name}\n      expected: ${JSON.stringify(expected)}\n` +
    `      actual:   ${JSON.stringify(actual)}`,
  );
  failures++;
}

export async function throwsNamed(
  fn: () => Promise<unknown>,
  errorName: string,
  name: string,
): Promise<void> {
  try {
    await fn();
    console.error(`  ✗ ${name} (expected ${errorName})`);
    failures++;
  } catch (e: any) {
    if (e?.name === errorName) console.log(`  ✓ ${name}`);
    else { console.error(`  ✗ ${name} — got ${e?.name}: ${e?.message}`); failures++; }
  }
}

export function done(label: string): never {
  console.log(failures === 0 ? `\nAll ${label} tests passed.` : `\n${failures} failure(s).`);
  process.exit(failures === 0 ? 0 : 1);
}
