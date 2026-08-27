/**
 * AHTML-to-TSX Prompt Builder
 *
 * Parses annotated HTML and builds a structured prompt for the LLM agent
 * that converts it to valid Next.js TSX pages.
 *
 * This module does NOT call the LLM — it produces the prompt input.
 * The actual LLM call happens in the backend (ahtml_conversion_agent.py).
 */

import { parseAnnotatedHtml } from "./html-parser.js";
import type { ParsedPage, PageSummary } from "./html-parser.js";

// ---------------------------------------------------------------------------
// TSX Generation Context (passed to the LLM agent)
// ---------------------------------------------------------------------------

export interface TsxGenerationContext {
  /** One context per page */
  pages: PageTsxContext[];
}

export interface PageTsxContext {
  /** Page metadata */
  pageId: string;
  route: string;
  title?: string;
  requiresAuth: boolean;
  authRoles?: string[];

  /** The raw annotated HTML body */
  html: string;

  /** Extracted semantic model */
  dataSources: Record<string, { method: string; path: string; params?: Record<string, unknown> }>;
  stateFields: Record<string, unknown>;
  modals: Record<string, { title: string; size?: string }>;

  /** Summary of what the page needs */
  summary: PageSummary;

  /** Generated TSX hints — the expected imports, hooks, and structure */
  tsxHints: TsxHints;
}

export interface TsxHints {
  /** React imports needed */
  reactImports: string[];
  /** Library imports needed (shadcn/ui, lucide, etc.) */
  libraryImports: string[];
  /** React Query hooks needed */
  queryHooks: string[];
  /** useState declarations needed */
  stateDeclarations: string[];
  /** Event handlers needed */
  handlers: string[];
}

// ---------------------------------------------------------------------------
// Build TSX generation context from annotated HTML
// ---------------------------------------------------------------------------

export function buildTsxContext(html: string): TsxGenerationContext {
  const parsed = parseAnnotatedHtml(html);
  return {
    pages: parsed.map(buildPageContext),
  };
}

function buildPageContext(page: ParsedPage): PageTsxContext {
  const tsxHints = deriveTsxHints(page);

  return {
    pageId: page.pageId,
    route: page.route,
    title: page.title,
    requiresAuth: !!page.auth?.required,
    authRoles: page.auth?.roles,
    html: page.bodyHtml,
    dataSources: Object.fromEntries(
      Object.entries(page.dataSources).map(([k, v]) => [k, { method: v.method, path: v.path, params: v.params as any }]),
    ),
    stateFields: page.state,
    modals: page.modals,
    summary: page.summary,
    tsxHints,
  };
}

// ---------------------------------------------------------------------------
// Derive TSX hints from the semantic model
// ---------------------------------------------------------------------------

function deriveTsxHints(page: ParsedPage): TsxHints {
  const reactImports = new Set<string>(["useState"]);
  const libraryImports = new Set<string>();
  const queryHooks: string[] = [];
  const stateDeclarations: string[] = [];
  const handlers: string[] = [];

  // Data sources → useQuery / useMutation hooks
  for (const [name, ds] of Object.entries(page.dataSources)) {
    if (ds.method === "GET") {
      queryHooks.push(`const { data: ${name}Data, isLoading: ${name}IsLoading } = useQuery({ queryKey: ["${name}"], queryFn: () => fetch("${ds.path}").then(r => r.json()) });`);
      libraryImports.add(`import { useQuery } from "@tanstack/react-query";`);
    } else {
      queryHooks.push(`const ${name}Mutation = useMutation({ mutationFn: (data) => fetch("${ds.path}", { method: "${ds.method}", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }) });`);
      libraryImports.add(`import { useMutation, useQueryClient } from "@tanstack/react-query";`);
    }
  }

  // State bindings → useState declarations
  const stateKeys = new Set<string>();
  for (const binding of page.summary.stateBindings) {
    if (!stateKeys.has(binding.stateKey)) {
      stateKeys.add(binding.stateKey);
      const initValue = page.state[binding.stateKey];
      const initStr = initValue !== undefined ? JSON.stringify(initValue) : '""';
      stateDeclarations.push(`const [${binding.stateKey}, set${capitalize(binding.stateKey)}] = useState(${initStr});`);
    }
  }

  // Actions → handler functions
  for (const action of page.summary.actions) {
    if (action.type === "navigate") {
      libraryImports.add(`import { useRouter } from "next/navigation";`);
      reactImports.add("useCallback");
    }
    if (action.type === "mutate") {
      handlers.push(`// Handler for mutate ${action.source}`);
    }
  }

  // Component types → imports
  for (const compType of page.summary.componentTypes) {
    if (compType === "DataTable") {
      libraryImports.add(`import { DataTable } from "@/components/ui/data-table";`);
      reactImports.add("useMemo");
    }
    if (compType === "Card") {
      libraryImports.add(`import { Card, CardContent } from "@/components/ui/card";`);
    }
    if (compType === "Tabs") {
      libraryImports.add(`import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";`);
    }
    if (compType === "Form") {
      libraryImports.add(`import { Input } from "@/components/ui/input";`);
    }
  }

  // Modals
  if (Object.keys(page.modals).length > 0) {
    libraryImports.add(`import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";`);
    for (const [id] of Object.entries(page.modals)) {
      stateDeclarations.push(`const [${id}Open, set${capitalize(id)}Open] = useState(false);`);
    }
  }

  return {
    reactImports: Array.from(reactImports),
    libraryImports: Array.from(libraryImports),
    queryHooks,
    stateDeclarations,
    handlers,
  };
}

// ---------------------------------------------------------------------------
// Generate the LLM prompt for TSX conversion
// ---------------------------------------------------------------------------

export function buildTsxPrompt(pageCtx: PageTsxContext): string {
  return `Convert the following annotated HTML page to a valid Next.js "use client" TSX component.

## Page Metadata
- Page ID: ${pageCtx.pageId}
- Route: ${pageCtx.route}
- Title: ${pageCtx.title || "Untitled"}
- Auth Required: ${pageCtx.requiresAuth}

## Data Sources
${JSON.stringify(pageCtx.dataSources, null, 2)}

## State Fields
${JSON.stringify(pageCtx.stateFields, null, 2)}

## Modals
${JSON.stringify(pageCtx.modals, null, 2)}

## Semantic Summary
- State bindings: ${pageCtx.summary.stateBindings.map((b) => b.expression).join(", ") || "none"}
- Data sources referenced: ${pageCtx.summary.dataSourceRefs.join(", ") || "none"}
- Actions: ${pageCtx.summary.actions.map((a) => `${a.type}${a.to ? `→${a.to}` : ""}${a.source ? `→${a.source}` : ""}`).join(", ") || "none"}
- Slots: ${pageCtx.summary.slots.map((s) => `${s.type}${s.entity ? `(${s.entity})` : ""}`).join(", ") || "none"}
- Repeaters: ${pageCtx.summary.repeaters.map((r) => r.data).join(", ") || "none"}
- Components: ${pageCtx.summary.componentTypes.join(", ") || "none"}

## TSX Hints (suggested imports/hooks)
\`\`\`typescript
${pageCtx.tsxHints.libraryImports.join("\n")}

// React hooks
import { ${pageCtx.tsxHints.reactImports.join(", ")} } from "react";

// Query hooks
${pageCtx.tsxHints.queryHooks.join("\n")}

// State
${pageCtx.tsxHints.stateDeclarations.join("\n")}
\`\`\`

## Annotated HTML (the source to convert)
\`\`\`html
${pageCtx.html}
\`\`\`

## Rules
1. Output ONLY the TSX code, no explanations
2. Start with "use client" directive
3. Use shadcn/ui components where matching (Button, Card, Input, Badge, Tabs, etc.)
4. Convert data-bind attributes to useState + onChange handlers
5. Convert data-action="navigate" to router.push()
6. Convert data-action="mutate" to useMutation
7. Convert data-repeat to .map() with proper keys
8. Convert data-field to column accessors or field references
9. Convert data-visible to conditional rendering {condition && (...)}
10. Convert data-slot placeholders to TODO comments with the slot type
11. Preserve ALL Tailwind classes exactly as-is
12. Preserve ALL visual styles, colors, spacing, and layout
13. Use the component name: ${capitalize(pageCtx.pageId)}Page
14. Export as default
`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
