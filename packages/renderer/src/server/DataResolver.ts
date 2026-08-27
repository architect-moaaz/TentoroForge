import type { Page } from "@tentoroforge/schema";

export type DataEngine = {
  run: (source: any, ctx?: { request?: Request; user?: any }) => Promise<unknown>;
};

export async function resolveDataSources(
  page: Page,
  engine: DataEngine,
  ctx: { request?: Request; user?: any }
): Promise<Record<string, unknown>> {
  const sources = page.dataSources ?? [];
  const entries = await Promise.all(
    sources.map(async (s) => [s.name, await engine.run(s, ctx)] as const)
  );
  return Object.fromEntries(entries);
}
