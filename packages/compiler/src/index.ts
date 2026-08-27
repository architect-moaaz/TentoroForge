/**
 * Tentoro Forge IR Compiler
 *
 * compile(ir) → FileMap { [path: string]: string }
 *
 * Takes an AppIR, validates it, and produces a map of file paths to TSX file contents.
 * Deterministic: same IR always produces the same output.
 */

import type { AppIR, PageIR } from "@tentoroforge/ir";
import { validateIR, generateThemeCSS } from "@tentoroforge/ir";
import { EmitContext } from "./context.js";
import { emitNode } from "./emit.js";
import { assemblePageFile } from "./assemble.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FileMap {
  [path: string]: string;
}

export interface CompileOptions {
  /** Include data-ir-path attributes for UI editor integration */
  devMode?: boolean;
  /** Only compile specific pages (by $id) */
  pageIds?: string[];
}

export interface CompileResult {
  files: FileMap;
  errors: string[];
  warnings: string[];
}

// ---------------------------------------------------------------------------
// Page-level cache (for incremental recompilation)
// ---------------------------------------------------------------------------

const PAGE_CACHE = new Map<string, { hash: string; files: FileMap }>();

function hashPage(page: PageIR): string {
  // Simple JSON hash — fast enough for <100ms recompiles
  return simpleHash(JSON.stringify(page));
}

function simpleHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const ch = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + ch;
    hash |= 0;
  }
  return hash.toString(36);
}

/** Clear the compilation cache (for testing or after theme changes) */
export function clearCache(): void {
  PAGE_CACHE.clear();
}

// ---------------------------------------------------------------------------
// Main compile function
// ---------------------------------------------------------------------------

export function compile(ir: AppIR, options: CompileOptions = {}): CompileResult {
  const result: CompileResult = {
    files: {},
    errors: [],
    warnings: [],
  };

  // Phase 1: Validate
  const validationErrors = validateIR(ir);
  const criticalErrors = validationErrors.filter((e) => e.severity === "error");
  const warnings = validationErrors.filter((e) => e.severity === "warning");

  result.warnings = warnings.map((w) => `${w.path}: ${w.message}`);

  if (criticalErrors.length > 0) {
    result.errors = criticalErrors.map((e) => `${e.path}: ${e.message}`);
    return result;
  }

  // Phase 2-5: Compile each page
  const pagesToCompile = options.pageIds
    ? ir.pages.filter((p) => options.pageIds!.includes(p.$id))
    : ir.pages;

  for (const page of pagesToCompile) {
    try {
      // Check cache
      const pageHash = hashPage(page);
      const cacheKey = `${page.$id}:${pageHash}`;
      const cached = PAGE_CACHE.get(cacheKey);
      if (cached && !options.devMode) {
        Object.assign(result.files, cached.files);
        continue;
      }

      const { path, content } = compilePage(page, ir, options);
      result.files[path] = content;

      // Update cache
      PAGE_CACHE.set(cacheKey, { hash: pageHash, files: { [path]: content } });
    } catch (err) {
      result.errors.push(`Failed to compile page "${page.$id}": ${(err as Error).message}`);
    }
  }

  // Generate formatters utility if needed
  const allContent = Object.values(result.files).join("\n");
  if (allContent.includes("@/lib/formatters")) {
    result.files["lib/formatters.ts"] = generateFormattersFile();
  }

  // Generate globals.css with theme CSS variables
  result.files["app/globals.css"] = generateGlobalsCss(ir);

  // Generate layout.tsx with navigation shell
  result.files["app/layout.tsx"] = generateLayoutFile(ir);

  return result;
}

// ---------------------------------------------------------------------------
// Single page compilation
// ---------------------------------------------------------------------------

function compilePage(
  page: PageIR,
  ir: AppIR,
  options: CompileOptions,
): { path: string; content: string } {
  // Create emit context
  const ctx = new EmitContext({
    devMode: options.devMode,
    pageStateKeys: new Set(Object.keys(page.state || {})),
    dataSourceNames: new Set(Object.keys(ir.dataSources || {})),
  });

  // Emit the root node tree
  const jsx = emitNode(page.root, ctx);

  // Assemble the complete file
  const content = assemblePageFile(page, jsx, ctx, ir.dataSources || {});

  // Determine file path from route
  const routePath = page.route === "/" ? "/page" : page.route;
  const filePath = `app${routePath}/page.tsx`;

  return { path: filePath, content };
}

// ---------------------------------------------------------------------------
// Utility files
// ---------------------------------------------------------------------------

function generateFormattersFile(): string {
  return `/**
 * Formatters — utility functions for data display.
 * Auto-generated by Tentoro Forge compiler.
 */

export function formatRelativeDate(date: string | Date): string {
  if (!date) return "";
  const d = typeof date === "string" ? new Date(date) : date;
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return \`\${diffMins}m ago\`;
  if (diffHours < 24) return \`\${diffHours}h ago\`;
  if (diffDays < 7) return \`\${diffDays}d ago\`;
  return d.toLocaleDateString();
}

export function formatDate(date: string | Date, format?: string): string {
  if (!date) return "";
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString();
}

export function formatCurrency(value: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

export function formatPercent(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "percent", minimumFractionDigits: 0 }).format(value / 100);
}

export function capitalize(s: string): string {
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function toUpperCase(s: string): string {
  return s?.toUpperCase() ?? "";
}

export function toLowerCase(s: string): string {
  return s?.toLowerCase() ?? "";
}
`;
}

// ---------------------------------------------------------------------------
// globals.css generator — theme CSS variables + Tailwind setup
// ---------------------------------------------------------------------------

function generateGlobalsCss(ir: AppIR): string {
  const themeName = ir.app?.theme || "default";
  const themeCSS = generateThemeCSS(themeName);

  // Collect ALL color tokens as CSS variables
  const customColors = ir.tokens?.color || {};
  const customVars: string[] = [];
  for (const [key, value] of Object.entries(customColors)) {
    if (value) customVars.push(`    --color-${key}: ${value};`);
  }

  // Spacing tokens
  const spacing = ir.tokens?.spacing || {};
  for (const [key, value] of Object.entries(spacing)) {
    if (value) customVars.push(`    --spacing-${key}: ${value};`);
  }

  // Radius tokens
  const radius = ir.tokens?.radius || {};
  for (const [key, value] of Object.entries(radius)) {
    if (value) customVars.push(`    --radius-${key}: ${value};`);
  }

  // Layout tokens from userContext
  const uc = (ir.userContext || {}) as Record<string, unknown>;
  if (uc.navigation) customVars.push(`    --nav-style: ${uc.navigation};`);
  if (uc.fontFamily) customVars.push(`    --font-sans: "${uc.fontFamily}", system-ui, sans-serif;`);

  const customBlock = customVars.length > 0
    ? `\n    /* Design tokens */\n${customVars.join("\n")}\n`
    : "";

  return `@import "tailwindcss";

${themeCSS.replace(":root {", `:root {${customBlock}`)}

@layer base {
  * {
    @apply border-border;
  }
  body {
    @apply bg-background text-foreground;
    font-family: var(--font-sans, "Inter", system-ui, -apple-system, sans-serif);
  }
}
`;
}

// ---------------------------------------------------------------------------
// Token helpers — resolve all values from IR tokens, never hardcode
// ---------------------------------------------------------------------------

interface LayoutTokens {
  sidebarWidth: string;
  topbarHeight: string;
  maxContentWidth: string;
  navSpacing: string;
  navItemPadding: string;
  navItemGap: string;
  navItemRadius: string;
  navFontSize: string;
  iconSize: string;
  brandingFontSize: string;
  sectionPadding: string;
  navBg: string;
  navBgDark: string;
  navText: string;
  navTextDark: string;
  navTextMuted: string;
  navTextMutedDark: string;
  navActiveBg: string;
  navActiveBgDark: string;
  navActiveText: string;
  navActiveTextDark: string;
  navHoverBg: string;
  navHoverBgDark: string;
  navBorder: string;
  navBorderDark: string;
  homeRoute: string;
}

function resolveLayoutTokens(ir: AppIR): LayoutTokens {
  const colors = ir.tokens?.color || {};
  const spacing = ir.tokens?.spacing || {};
  const radius = ir.tokens?.radius || {};
  const uc = (ir.userContext || {}) as Record<string, unknown>;

  // Resolve spacing from tokens with sensible defaults from the token system
  const sp = (key: string, fallback: string) => (spacing as Record<string, string>)[key] || fallback;
  const rad = (key: string, fallback: string) => (radius as Record<string, string>)[key] || fallback;
  const col = (key: string, fallback: string) => (colors as Record<string, string>)[key] || fallback;

  // Find home route from navigation
  const homeRoute = ir.navigation?.items?.[0]?.route || "/dashboard";

  return {
    sidebarWidth: (uc.sidebarWidth as string) || "16rem",
    topbarHeight: (uc.topbarHeight as string) || "3.5rem",
    maxContentWidth: (uc.maxContentWidth as string) || "80rem",
    navSpacing: sp("md", "1rem"),
    navItemPadding: `${sp("sm", "0.5rem")} ${sp("md", "0.75rem")}`,
    navItemGap: sp("sm", "0.75rem"),
    navItemRadius: rad("md", "0.375rem"),
    navFontSize: "0.875rem",
    iconSize: "1rem",
    brandingFontSize: "1.125rem",
    sectionPadding: `${sp("lg", "1.25rem")} ${sp("md", "1rem")}`,
    navBg: "hsl(var(--background))",
    navBgDark: col("secondary", "#1e293b"),
    navText: "hsl(var(--foreground))",
    navTextDark: "#f8fafc",
    navTextMuted: "hsl(var(--muted-foreground))",
    navTextMutedDark: "#94a3b8",
    navActiveBg: `${col("primary", "hsl(var(--primary))")}1a`,
    navActiveBgDark: "rgba(255,255,255,0.1)",
    navActiveText: col("primary", "hsl(var(--primary))"),
    navActiveTextDark: "#ffffff",
    navHoverBg: "hsl(var(--muted))",
    navHoverBgDark: "rgba(255,255,255,0.05)",
    navBorder: "hsl(var(--border))",
    navBorderDark: "rgba(255,255,255,0.1)",
    homeRoute,
  };
}

// ---------------------------------------------------------------------------
// layout.tsx generator
// ---------------------------------------------------------------------------

function generateLayoutFile(ir: AppIR): string {
  const appName = ir.app?.name || "App";
  const uc = (ir.userContext || {}) as Record<string, unknown>;
  const navStyle = (uc.navigation as string) || "sidebar";
  const isSidebar = navStyle === "sidebar" || navStyle === "sidebar-dark";
  const navComponent = isSidebar ? "SidebarNav" : "TopNav";
  const navFile = isSidebar ? "sidebar-nav" : "top-nav";

  return `import type { Metadata } from "next";
import "./globals.css";
import { ${navComponent} } from "./${navFile}";

export const metadata: Metadata = {
  title: "${appName}",
  description: "${appName} application",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        ${isSidebar ? `<div className="flex min-h-screen">
          <${navComponent} />
          <main className="flex-1 overflow-auto">
            {children}
          </main>
        </div>` : `<${navComponent} />
        <main style={{ maxWidth: "var(--max-content-width, 80rem)", margin: "0 auto", padding: "var(--spacing-lg, 1.5rem) var(--spacing-md, 1rem)" }}>
          {children}
        </main>`}
      </body>
    </html>
  );
}
`;
}

// ---------------------------------------------------------------------------
// Sidebar navigation component — all styling from tokens
// ---------------------------------------------------------------------------

function generateSidebarNav(ir: AppIR): string {
  const t = resolveLayoutTokens(ir);
  const appName = ir.app?.name || "App";
  const navItems = ir.navigation?.items || [];
  const uc = (ir.userContext || {}) as Record<string, unknown>;
  const isDark = (uc.navigation as string) === "sidebar-dark";

  const iconNames = new Set<string>();
  for (const item of navItems) iconNames.add(kebabToPascal(item.icon || "file"));
  iconNames.add("LogOut");
  const iconImports = Array.from(iconNames).sort().join(", ");

  const navItemsJsx = navItems.map((item) => {
    const icon = kebabToPascal(item.icon || "file");
    return `        <Link
          href="${item.route}"
          className="nav-item"
          style={pathname === "${item.route}" ? activeStyle : inactiveStyle}
          onMouseEnter={(e) => { if (pathname !== "${item.route}") Object.assign(e.currentTarget.style, hoverStyle); }}
          onMouseLeave={(e) => { if (pathname !== "${item.route}") Object.assign(e.currentTarget.style, inactiveStyle); }}
        >
          <${icon} style={{ width: "${t.iconSize}", height: "${t.iconSize}" }} />
          ${item.label}
        </Link>`;
  }).join("\n");

  return `"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ${iconImports} } from "lucide-react";

const sidebarStyle: React.CSSProperties = {
  width: "${t.sidebarWidth}",
  flexShrink: 0,
  background: "${isDark ? t.navBgDark : t.navBg}",
  color: "${isDark ? t.navTextDark : t.navText}",
  display: "flex",
  flexDirection: "column",
  minHeight: "100vh",
  ${isDark ? "" : `borderRight: "1px solid ${t.navBorder}",`}
};

const brandStyle: React.CSSProperties = {
  padding: "${t.sectionPadding}",
  borderBottom: "1px solid ${isDark ? t.navBorderDark : t.navBorder}",
  fontSize: "${t.brandingFontSize}",
  fontWeight: 600,
};

const navStyle: React.CSSProperties = {
  flex: 1,
  padding: "${t.navSpacing}",
  display: "flex",
  flexDirection: "column",
  gap: "0.25rem",
};

const itemBase: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "${t.navItemGap}",
  padding: "${t.navItemPadding}",
  borderRadius: "${t.navItemRadius}",
  fontSize: "${t.navFontSize}",
  transition: "background 150ms, color 150ms",
  textDecoration: "none",
  cursor: "pointer",
};

const activeStyle: React.CSSProperties = {
  ...itemBase,
  background: "${isDark ? t.navActiveBgDark : t.navActiveBg}",
  color: "${isDark ? t.navActiveTextDark : t.navActiveText}",
  fontWeight: 500,
};

const inactiveStyle: React.CSSProperties = {
  ...itemBase,
  color: "${isDark ? t.navTextMutedDark : t.navTextMuted}",
};

const hoverStyle: React.CSSProperties = {
  ...itemBase,
  background: "${isDark ? t.navHoverBgDark : t.navHoverBg}",
  color: "${isDark ? t.navActiveTextDark : t.navText}",
};

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <aside style={sidebarStyle}>
      <div style={brandStyle}>${appName}</div>
      <nav style={navStyle}>
${navItemsJsx}
      </nav>
      <div style={{ padding: "${t.navSpacing}", borderTop: "1px solid ${isDark ? t.navBorderDark : t.navBorder}" }}>
        <button style={inactiveStyle} className="w-full">
          <LogOut style={{ width: "${t.iconSize}", height: "${t.iconSize}" }} />
          Sign Out
        </button>
      </div>
    </aside>
  );
}
`;
}

// ---------------------------------------------------------------------------
// Top navigation component — all styling from tokens
// ---------------------------------------------------------------------------

function generateTopNav(ir: AppIR): string {
  const t = resolveLayoutTokens(ir);
  const appName = ir.app?.name || "App";
  const navItems = ir.navigation?.items || [];

  const iconNames = new Set<string>();
  for (const item of navItems) iconNames.add(kebabToPascal(item.icon || "file"));
  iconNames.add("LogOut");
  const iconImports = Array.from(iconNames).sort().join(", ");

  const navItemsJsx = navItems.map((item) => {
    const icon = kebabToPascal(item.icon || "file");
    return `        <Link
          href="${item.route}"
          className="nav-item"
          style={pathname === "${item.route}" ? activeStyle : inactiveStyle}
          onMouseEnter={(e) => { if (pathname !== "${item.route}") Object.assign(e.currentTarget.style, hoverStyle); }}
          onMouseLeave={(e) => { if (pathname !== "${item.route}") Object.assign(e.currentTarget.style, inactiveStyle); }}
        >
          <${icon} style={{ width: "${t.iconSize}", height: "${t.iconSize}" }} />
          ${item.label}
        </Link>`;
  }).join("\n");

  return `"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ${iconImports} } from "lucide-react";

const headerStyle: React.CSSProperties = {
  borderBottom: "1px solid ${t.navBorder}",
  background: "${t.navBg}",
};

const innerStyle: React.CSSProperties = {
  maxWidth: "${t.maxContentWidth}",
  margin: "0 auto",
  padding: "0 ${t.navSpacing}",
  display: "flex",
  alignItems: "center",
  height: "${t.topbarHeight}",
  gap: "${t.navSpacing}",
};

const itemBase: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "0.5rem",
  padding: "${t.navItemPadding}",
  borderRadius: "${t.navItemRadius}",
  fontSize: "${t.navFontSize}",
  transition: "background 150ms, color 150ms",
  textDecoration: "none",
};

const activeStyle: React.CSSProperties = {
  ...itemBase,
  background: "${t.navActiveBg}",
  color: "${t.navActiveText}",
  fontWeight: 500,
};

const inactiveStyle: React.CSSProperties = {
  ...itemBase,
  color: "${t.navTextMuted}",
};

const hoverStyle: React.CSSProperties = {
  ...itemBase,
  background: "${t.navHoverBg}",
  color: "${t.navText}",
};

export function TopNav() {
  const pathname = usePathname();

  return (
    <header style={headerStyle}>
      <div style={innerStyle}>
        <Link href="${t.homeRoute}" style={{ fontSize: "${t.brandingFontSize}", fontWeight: 600, textDecoration: "none", color: "inherit" }}>${appName}</Link>
        <nav style={{ display: "flex", alignItems: "center", gap: "0.25rem", flex: 1 }}>
${navItemsJsx}
        </nav>
        <button style={inactiveStyle}>
          <LogOut style={{ width: "${t.iconSize}", height: "${t.iconSize}" }} />
          Sign Out
        </button>
      </div>
    </header>
  );
}
`;
}

function kebabToPascal(s: string): string {
  return s.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join("");
}

// ---------------------------------------------------------------------------
// Extended compile — includes nav components
// ---------------------------------------------------------------------------

/** Compile with navigation components included */
export function compileWithNav(ir: AppIR, options: CompileOptions = {}): CompileResult {
  const result = compile(ir, options);
  if (result.errors.length > 0) return result;

  const navStyle = (ir as any).userContext?.navigation || "sidebar";
  const isSidebar = navStyle === "sidebar" || navStyle === "sidebar-dark";

  if (isSidebar) {
    result.files["app/sidebar-nav.tsx"] = generateSidebarNav(ir);
  } else {
    result.files["app/top-nav.tsx"] = generateTopNav(ir);
  }

  return result;
}

// Re-exports
export { EmitContext } from "./context.js";
export { emitNode } from "./emit.js";
export { assemblePageFile } from "./assemble.js";
export { emitBinding, emitStateBinding, emitExpression, emitJSXContent } from "./bindings.js";
export { emitAction, emitActionHandler } from "./actions.js";
