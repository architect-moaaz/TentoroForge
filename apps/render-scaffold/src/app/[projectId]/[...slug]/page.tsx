import { notFound } from "next/navigation";
// Import the Zod schema values explicitly. `Page` is both a const (Zod union)
// and a type alias in @tentoroforge/schema — when imported as `{ Page }` the
// bundler may resolve only the type (undefined at runtime). Using PageV1 /
// PageV2 directly avoids this name collision.
import { PageV1, PageV2 } from "@tentoroforge/schema";
import { z } from "zod";
import { compileTokens } from "@tentoroforge/renderer";
import type React from "react";
import { promises as fs } from "node:fs";
import path from "node:path";
import { SchemaRendererWrapper } from "@/components/SchemaRendererWrapper";
import { ShellWrapper } from "@/components/ShellWrapper";
import { PreviewShell } from "@/components/PreviewShell";
import { loadSchema } from "@/lib/loadSchema";
import { loadTokens } from "@/lib/loadTokens";
import { resolveProject } from "@/lib/resolveProject";
import { A11yTreeEmbed } from "@/components/A11yTreeEmbed";
import { buildA11yTree } from "@/lib/a11yTree";

/**
 * Fetch fixture data for all entities in the project from the backend's
 * preview-data endpoint. Returns an empty object on any error so the page
 * still renders (with literal {{...}} placeholders as a degraded fallback).
 */
async function loadPreviewData(projectId: string): Promise<Record<string, unknown>> {
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
  try {
    const r = await fetch(`${apiBase}/api/_debug/preview-data/${projectId}`, {
      cache: "no-store",
    });
    if (!r.ok) return {};
    return (await r.json()) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/**
 * Load nav-flow.json from src/contracts/. Returns null when absent so the
 * scaffold's in-page navigation falls back to direct href resolution without
 * NavFlowContext (same behaviour as before nav-flow was added).
 */
async function loadNavFlow(projectRoot: string): Promise<unknown | null> {
  try {
    const text = await fs.readFile(
      path.join(projectRoot, "src", "contracts", "nav-flow.json"),
      "utf8",
    );
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/**
 * Load the raw tokens.custom.json for a project. Returns null when absent so
 * callers can decide whether to pass it along (null → EngineProvider falls
 * back to walking designSpec.tokens itself, preserving existing behaviour for
 * older projects that pre-date the custom token file).
 *
 * Kept separate from loadTokens() because loadTokens() deep-merges against
 * defaultTokens, which is what compileTokens needs for CSS-var compilation.
 * EngineProvider's cssVarTokens prop wants the raw project overrides tree so
 * it can derive both full CSS vars AND shadcn semantic vars using only the
 * project's brand palette.
 */
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

/**
 * Load the design register string from design-spec.json.
 * Falls back to "default" if the file is absent or malformed.
 */
async function loadRegister(projectRoot: string): Promise<string> {
  try {
    const text = await fs.readFile(
      path.join(projectRoot, "src", "contracts", "design-spec.json"),
      "utf8",
    );
    const spec = JSON.parse(text);
    return spec.register || "default";
  } catch {
    return "default";
  }
}

/**
 * Load the project's globals.css and strip the @tailwind directives.
 *
 * The generated app has its own globals.css with design-system tokens,
 * status colors, micro-interactions, hero gradients, scrollbar styles, etc.
 * The scaffold has its own globals.css for Tailwind base/components/utilities,
 * so we strip those directives from the project's file (they can't be
 * processed at runtime) and inject the remaining CSS as a <style> tag.
 * This brings the standalone-app visual fidelity into the preview.
 *
 * Returns an empty string if globals.css is absent — older projects without
 * a design_agent run keep rendering with scaffold-default styles.
 */
async function loadProjectGlobalsCss(projectRoot: string): Promise<string> {
  try {
    const text = await fs.readFile(
      path.join(projectRoot, "src", "app", "globals.css"),
      "utf8",
    );
    // Remove @tailwind directives — they're Tailwind-CLI-only and would
    // appear as invalid CSS if injected into the browser at runtime.
    return text.replace(/^@tailwind\s+\w+\s*;\s*$/gm, "").trim();
  } catch {
    return "";
  }
}

/**
 * Load shell.json from src/schemas/. Returns null when absent — projects
 * without a shell.json get the old bare/PreviewShell rendering.
 */
async function loadShellSchema(projectRoot: string): Promise<unknown | null> {
  try {
    const text = await fs.readFile(
      path.join(projectRoot, "src", "schemas", "shell.json"),
      "utf8",
    );
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// Legacy fallback bare-route set — used only when nav-flow.json is absent or
// has no auth_routes field (e.g. projects generated before Day 3).
const BARE_ROUTES_FALLBACK = new Set(["login", "signup", "forgot-password"]);

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string; slug: string[] }>;
  searchParams: Promise<{ preview?: string; dev?: string }>;
}) {
  const { projectId, slug } = await params;
  const { preview, dev } = await searchParams;
  const isPreview = preview === "true";
  // Dev mode re-enables the PreviewShell sidebar. Default is the exported-app
  // look (shell.json nav bar or bare page). Access via ?dev=1.
  const isDevMode = dev === "1";

  // Resolve the project root — throws if the id contains traversal chars,
  // which notFound() converts to a clean 404 rather than an unhandled error.
  let projectRoot: string;
  try {
    projectRoot = resolveProject(projectId);
  } catch {
    notFound();
  }

  // Resolve the schema path with production-style URL fallbacks.
  //
  // The relay pipeline emits one schema per (entity, page-type): list, detail,
  // form. Live Next.js apps generated from this platform use dynamic routes:
  // `/tasks/[id]` for detail, `/tasks/new` for create. Schemas accordingly
  // emit `navigate: "/tasks/{{item.id}}"` and `"/tasks/new"`. The scaffold's
  // own routing is flat (`/<entity>/<page-type>`), so without a fallback,
  // every "View" / "Create" button on a list page 404s.
  //
  // Fallback chain:
  //   1. Literal path (e.g. tasks/list)
  //   2. Dynamic-route placeholder (e.g. /notes/abc-123 → notes/[id])
  //   3. Legacy fallback (new/create → form; anything else → detail)
  const rawSlug = slug.join("/");
  let pagePath = rawSlug;
  let raw = await loadSchema(projectRoot!, pagePath);

  // Step 2: dynamic-route placeholder. /notes/abc-123 → notes/[id]
  if (!raw && slug.length >= 2) {
    const dynPath = [...slug.slice(0, -1), "[id]"].join("/");
    raw = await loadSchema(projectRoot!, dynPath);
    if (raw) pagePath = dynPath;
  }

  // Step 3: legacy fallback: <entity>/<page-type>.json patterns
  if (!raw && slug.length >= 2) {
    const last = slug[slug.length - 1];
    const entityPath = slug.slice(0, -1).join("/");
    const candidate =
      last === "new" || last === "create"
        ? `${entityPath}/form`
        : `${entityPath}/detail`;
    raw = await loadSchema(projectRoot!, candidate);
    if (raw) pagePath = candidate;
  }

  if (!raw) notFound();

  // Parse through the schema package's Page union (PageV1 | PageV2).
  // We build the union here rather than importing `Page` by name because that
  // name is both a Zod const and a TypeScript type alias in the schema package;
  // the bundler may strip the value and leave undefined at runtime.
  //
  // safeParse + permissive fallback: when the LLM-generated schema has shape
  // mismatches (commonly Mustache placeholders in typed fields like
  // `delta.value: "{{stats.approvedDelta}}"`, or semantic gap tokens like
  // `gap: "lg"` instead of `gap: "primary.500"`), we still want the page to
  // render something the user can see. The runtime renderer is already tolerant
  // of unknown shapes — unknown node types render as labelled placeholders, and
  // mustache strings interpolate at render time. So we fall through to the raw
  // tree on Zod failure rather than 500-ing the whole page.
  // Build the discriminated union defensively. If the union itself fails to
  // construct (e.g. one variant is wrapped in ZodEffects, or the schema
  // package shipped a mid-refactor build), fall through to raw rendering
  // rather than 500-ing every page. This used to crash for every project
  // whenever the schema package was in an intermediate state.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let page: any = raw;
  try {
    const PageUnion = z.discriminatedUnion("schemaVersion", [PageV1, PageV2]);
    const parsed = PageUnion.safeParse(raw);
    if (parsed.success) {
      page = parsed.data;
    } else {
      const issues = parsed.error.issues.slice(0, 3).map((i) => `${i.path.join(".")}: ${i.message}`);
      console.warn(`[scaffold] schema validation failed for ${projectId}/${pagePath} (${parsed.error.issues.length} issues), rendering raw. First: ${JSON.stringify(issues)}`);
    }
  } catch (e) {
    console.warn(`[scaffold] PageUnion could not be constructed (${(e as Error).message}); rendering raw schema.`);
  }

  // Compile project tokens into CSS custom properties for this render.
  const tokens = await loadTokens(projectRoot!);
  // compileTokens expects Record<string, Record<string, string>>; cast is safe
  // because loadTokens merges against defaultTokens which has that exact shape.
  const tokenCssVars = compileTokens(tokens as Record<string, Record<string, string>>) as React.CSSProperties;

  // Load the design register from design-spec.json (falls back to "default").
  const register = await loadRegister(projectRoot!);

  // Load nav-flow.json so that scaffold navigation resolves transitions and
  // guards at click-time via the engine's useNavigate hook (W1.5 delegation).
  const navFlow = await loadNavFlow(projectRoot!);

  // Load shell.json if present. When a page entry has shell:true, the scaffold
  // renders the shell schema wrapping the page content via PageOutletContext.
  const shellSchema = await loadShellSchema(projectRoot!);

  // Load the project's globals.css (design tokens, status colors, micro-
  // interactions). Empty string when the file is absent — preserves the
  // existing scaffold-default render path for older projects.
  const projectGlobalsCss = await loadProjectGlobalsCss(projectRoot!);

  const a11yTree = buildA11yTree(page as any);

  // Fetch fixture data from the backend. This replaces the no-op DataEngine
  // so that {{stats.pendingCount}} and similar bindings resolve to real values.
  const previewData = await loadPreviewData(projectId);

  // Load the raw project token overrides (tokens.custom.json). Passed to
  // SchemaRendererWrapper so EngineProvider can inject CSS custom properties
  // like --color-primary-500 and shadcn semantic vars like --primary. Without
  // this, bg-primary / text-primary Tailwind utilities resolve to nothing and
  // buttons appear unstyled in the preview.
  const cssVarTokens = await loadTokensCustom(projectRoot!);

  void isPreview; // retained for ?preview=true cache-busting compat

  // Determine whether this route should render bare (no PreviewShell / shell).
  // Prefer nav-flow's auth_routes list (set by the MCP pipeline auto-classifier).
  // Fall back to the legacy hardcoded set for projects without the Day 3 fields.
  const currentRoute = `/${rawSlug}`;
  const navFlowAny = navFlow as any;
  const authRoutes: string[] = Array.isArray(navFlowAny?.auth_routes)
    ? navFlowAny.auth_routes
    : [];
  const isBare =
    authRoutes.length > 0
      ? authRoutes.includes(currentRoute)
      : BARE_ROUTES_FALLBACK.has(slug[0] ?? "");

  // Check whether the nav-flow marks this page as shell:true (should be
  // wrapped in the shell schema). Only applies when shell.json exists.
  const currentPageEntry = (navFlowAny?.pages ?? []).find(
    (p: any) => p.route === currentRoute,
  );
  const wantsShell = !isBare && !!shellSchema && (currentPageEntry?.shell === true);

  const commonProps = {
    register,
    tokens: tokens as Record<string, Record<string, string>>,
    previewData,
    projectId,
    navFlow,
    cssVarTokens: cssVarTokens ?? undefined,
  };

  // Render strategy:
  // 1. Shell-wrapped (exported-app default): shell.json nav + PageOutlet → page content
  // 2. Dev sidebar (?dev=1): PreviewShell sidebar (for browsing all pages)
  // 3. Bare: auth pages (login, etc.) rendered without any frame
  let mainContent: React.ReactNode;
  if (wantsShell) {
    // Schema-driven shell: shell.json wraps the page via PageOutletContext.
    // This is the default for authenticated pages that have shell:true.
    mainContent = (
      <ShellWrapper
        shell={shellSchema}
        page={page}
        {...commonProps}
      />
    );
  } else {
    // Bare page or dev-mode sidebar.
    const pageContent = (
      <SchemaRendererWrapper
        page={page}
        {...commonProps}
      />
    );
    mainContent = (!isBare && isDevMode) ? (
      <PreviewShell projectId={projectId} navFlow={navFlow as any}>
        {pageContent}
      </PreviewShell>
    ) : pageContent;
  }

  return (
    <main
      style={tokenCssVars}
      data-project-id={projectId}
      data-page-path={pagePath}
      data-register={register}
    >
      {projectGlobalsCss && (
        <style
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: projectGlobalsCss }}
        />
      )}
      {/*
        SchemaRendererWrapper is a "use client" component. It receives only
        serialisable props (page JSON, tokens object, register string,
        previewData), then builds the registry + mounts TokensProvider +
        renders SchemaRenderer on the client side.
      */}
      {mainContent}
      <A11yTreeEmbed tree={a11yTree} />
    </main>
  );
}
