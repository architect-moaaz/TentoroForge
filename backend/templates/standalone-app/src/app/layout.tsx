import "./globals.css";
import { EngineProvider } from "@tentoroforge/engine";
import { LiveRegion, SkipLink } from "@tentoroforge/library";
import { promises as fs } from "node:fs";
import path from "node:path";

async function loadJson<T>(rel: string): Promise<T | null> {
  try {
    const p = path.join(process.cwd(), rel);
    return JSON.parse(await fs.readFile(p, "utf8")) as T;
  } catch {
    return null;
  }
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const designSpec = await loadJson("src/contracts/design-spec.json");
  const navFlow = await loadJson("src/contracts/nav-flow.json");
  // The project's compiled design tokens — colors, type, shape, density,
  // elevation — written per app by the design pipeline. Passing them as
  // cssVarTokens is what makes this app's identity actually reach the
  // component library (CSS vars + TokensProvider context); without it every
  // app rendered the library defaults.
  const customTokens = await loadJson("src/theme/tokens.custom.json");
  return (
    // suppressHydrationWarning: browser extensions (Grammarly, ColorZilla, Scribe…)
    // inject attributes onto <html>/<body> before React hydrates; without this they
    // trip a benign hydration-mismatch warning. Scoped to these tags only.
    <html lang="__APP_LOCALE__" dir="__APP_DIR__" suppressHydrationWarning>
      <body suppressHydrationWarning>
        {/*
          Spec E Wave 2 accessibility spine — a SkipLink must be the first
          focusable element in the DOM so the first Tab press exposes it,
          and a single LiveRegion mount sits at the app root so
          announce()-driven SR feedback (workflow success/failure) is
          always available regardless of route. Both are library
          primitives; the SkipLink target is the <main id="main">
          landmark stamped by src/lib/schema-page.tsx.
        */}
        <SkipLink />
        <LiveRegion />
        <EngineProvider
          designSpec={designSpec ?? {}}
          navFlow={navFlow}
          cssVarTokens={customTokens ?? undefined}
          // globals.css already declares the shadcn vars in HSL-channel form
          // (this app's Tailwind reads `hsl(var(--x))`). Letting the provider
          // re-emit them as raw hex would produce `hsl(#2c8003)` → invalid →
          // black text. Tokens still flow to the component context above.
          semanticVars={false}
        >
          {children}
        </EngineProvider>
      </body>
    </html>
  );
}
