import "./globals.css";
import type { Metadata, Viewport } from "next";
import { EngineProvider } from "@tentoroforge/engine";
import { LiveRegion, SkipLink } from "@tentoroforge/library";
import { Providers } from "./providers";
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

// THE APPLICATION ON A PHONE: the manifest that lets it be installed, the
// icon and title the home screen shows, and the colour the browser chrome
// takes. This overlay's layout is the one an app ships — the foundation's,
// which carried these, is replaced by it — so without them here no built app
// could be installed (m1dck85j on forge-v3, 2026-10-12). Paths carry the
// preview's prefix when there is one.
const BASE = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");

export const metadata: Metadata = {
  title: "__APP_NAME__",
  manifest: `${BASE}/manifest.webmanifest`,
  appleWebApp: { capable: true, title: "__APP_NAME__", statusBarStyle: "default" },
  icons: { icon: `${BASE}/icons/icon-192.png`, apple: `${BASE}/icons/apple-touch-icon.png` },
};

export const viewport: Viewport = {
  themeColor: "__THEME_COLOR__",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

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
          {/* The Toaster every `useWorkflow` success and failure is said
              through, the session, the query client and the browser crash
              reporter. This layout replaced app-foundation's without it, so
              every toast since was called into nothing. */}
          <Providers>{children}</Providers>
        </EngineProvider>
      </body>
    </html>
  );
}
