import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { TestRibbon } from "@/components/TestRibbon";
// compileTokens converts the token groups into a flat CSS custom-property map
// (e.g. { "--token-primary-500": "#3b82f6" }) that is applied on <html>.
// This makes every token available as a CSS variable throughout the app,
// which the schema renderer relies on when it resolves TokenRef values.
import { compileTokens } from "@tentoroforge/renderer";
import { tokens } from "@/theme/tokens.server";
import type React from "react";

// THE APPLICATION ON A PHONE: the manifest that lets it be installed, the
// icon and title the home screen shows, and the colour the browser chrome
// takes. Paths carry the preview's prefix when there is one.
const BASE = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");

export const metadata: Metadata = {
  title: "__APP_NAME__",
  description: "__APP_DESCRIPTION__",
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

// Computed once at module load time (server bundle) — tokens are static.
const tokenCssVars = compileTokens(tokens) as React.CSSProperties;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="__APP_LOCALE__"
      dir="__APP_DIR__"
      style={tokenCssVars}
      suppressHydrationWarning
    >
      <body suppressHydrationWarning>
        <TestRibbon />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
