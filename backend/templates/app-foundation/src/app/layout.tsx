import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
// compileTokens converts the token groups into a flat CSS custom-property map
// (e.g. { "--token-primary-500": "#3b82f6" }) that is applied on <html>.
// This makes every token available as a CSS variable throughout the app,
// which the schema renderer relies on when it resolves TokenRef values.
import { compileTokens } from "@tentoroforge/renderer";
import { tokens } from "@/theme/tokens.server";
import type React from "react";

export const metadata: Metadata = {
  title: "__APP_NAME__",
  description: "__APP_DESCRIPTION__",
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
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
