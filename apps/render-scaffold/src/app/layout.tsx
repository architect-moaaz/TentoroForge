import type { Metadata } from "next";
import "./globals.css";
import type React from "react";

export const metadata: Metadata = {
  title: "Tentoroforge Render Scaffold",
  description: "Headless schema render target",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning style={{ fontFamily: "var(--font-body, system-ui, sans-serif)" }}>{children}</body>
    </html>
  );
}
