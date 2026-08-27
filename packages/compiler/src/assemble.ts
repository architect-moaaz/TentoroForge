/**
 * File Assembler — takes emitted JSX and context, produces complete TSX file strings.
 */

import type { PageIR, DataSourceDef } from "@tentoroforge/ir";
import type { ImportSpec } from "./context.js";
import { EmitContext } from "./context.js";

// ---------------------------------------------------------------------------
// Import formatting
// ---------------------------------------------------------------------------

function formatImports(imports: ImportSpec[]): string {
  if (imports.length === 0) return "";

  // Sort: react first, then next, then external, then internal
  const sorted = [...imports].sort((a, b) => {
    const order = (s: string) => {
      if (s === "react") return 0;
      if (s.startsWith("next")) return 1;
      if (s.startsWith("@/")) return 3;
      if (s.startsWith("./") || s.startsWith("../")) return 4;
      return 2;
    };
    return order(a.from) - order(b.from);
  });

  return sorted
    .map((imp) => {
      const parts: string[] = [];
      if (imp.default) parts.push(imp.default);
      if (imp.named && imp.named.length > 0) {
        parts.push(`{ ${imp.named.join(", ")} }`);
      }
      return `import ${parts.join(", ")} from "${imp.from}";`;
    })
    .join("\n");
}

// ---------------------------------------------------------------------------
// State declaration formatting
// ---------------------------------------------------------------------------

function formatStateDeclarations(page: PageIR, ctx: EmitContext): string {
  const lines: string[] = [];

  // Page state from IR
  if (page.state) {
    for (const [key, defaultValue] of Object.entries(page.state)) {
      const setter = `set${key.charAt(0).toUpperCase()}${key.slice(1)}`;
      const valueStr = JSON.stringify(defaultValue);
      const typeStr = inferTypeFromValue(defaultValue);
      lines.push(`const [${key}, ${setter}] = useState<${typeStr}>(${valueStr});`);
    }
  }

  // Additional state from context (e.g., modal open states)
  for (const decl of ctx.getStateDeclarations()) {
    // Skip if already declared from page state
    if (page.state && decl.name in page.state) continue;
    const setter = `set${decl.name.charAt(0).toUpperCase()}${decl.name.slice(1)}`;
    lines.push(`const [${decl.name}, ${setter}] = useState<${decl.type}>(${decl.initialValue});`);
  }

  return lines.join("\n  ");
}

function inferTypeFromValue(value: unknown): string {
  if (value === null) return "string | null";
  if (typeof value === "string") return "string";
  if (typeof value === "number") return "number";
  if (typeof value === "boolean") return "boolean";
  if (Array.isArray(value)) return "any[]";
  if (typeof value === "object") return "Record<string, any>";
  return "any";
}

// ---------------------------------------------------------------------------
// Hook generation for data sources
// ---------------------------------------------------------------------------

function formatDataSourceHooks(
  dataSources: Record<string, DataSourceDef>,
  page: PageIR,
): string {
  const lines: string[] = [];

  // Determine which data sources this page uses
  const usedSources = findUsedDataSources(page);

  for (const sourceName of usedSources) {
    const ds = dataSources[sourceName];
    if (!ds) continue;

    if (ds.method === "GET") {
      // Query hook
      const varName = `${sourceName}Data`;
      const loadingVar = `${sourceName}IsLoading`;
      const errorVar = `${sourceName}Error`;

      // Build params
      const params = ds.params
        ? Object.entries(ds.params)
            .map(([key, param]) => {
              if (param.from) {
                const val = param.from.startsWith("state:") ? param.from.slice(6) : `"${param.from}"`;
                return `${key}: ${val}`;
              }
              return param.default !== undefined ? `${key}: ${JSON.stringify(param.default)}` : null;
            })
            .filter(Boolean)
            .join(", ")
        : "";

      const queryParams = params ? `{ ${params} }` : "{}";

      lines.push(
        `const { data: ${varName}, isLoading: ${loadingVar}, error: ${errorVar} } = useQuery({`,
        `  queryKey: ["${sourceName}", ${queryParams}],`,
        `  queryFn: async () => {`,
        `    const res = await fetch("${ds.path}");`,
        `    if (!res.ok) throw new Error("Failed to fetch");`,
        `    return res.json();`,
        `  },`,
        `});`,
      );
    } else {
      // Mutation hook
      const mutateVar = `${sourceName}Mutate`;
      const invalidations = ds.onSuccess?.invalidate
        ? ds.onSuccess.invalidate.map((s) => JSON.stringify(s)).join(", ")
        : "";

      lines.push(
        `const ${mutateVar} = useMutation({`,
        `  mutationFn: async (data: any) => {`,
        `    const res = await fetch("${ds.path}", {`,
        `      method: "${ds.method}",`,
        `      headers: { "Content-Type": "application/json" },`,
        `      body: JSON.stringify(data),`,
        `    });`,
        `    if (!res.ok) throw new Error("Request failed");`,
        `    return res.json();`,
        `  },`,
        invalidations
          ? `  onSuccess: () => { queryClient.invalidateQueries({ queryKey: [${invalidations}] }); },`
          : "",
        `});`,
      );

      if (invalidations) {
        // Need queryClient
      }
    }
  }

  return lines.filter(Boolean).join("\n  ");
}

function findUsedDataSources(page: PageIR): Set<string> {
  const used = new Set<string>();
  const json = JSON.stringify(page);

  // Find source: references
  const sourceRefs = json.matchAll(/source:(\w+)/g);
  for (const match of sourceRefs) {
    used.add(match[1]);
  }

  // Find mutate action references
  const mutateRefs = json.matchAll(/"source"\s*:\s*"(\w+)"/g);
  for (const match of mutateRefs) {
    used.add(match[1]);
  }

  return used;
}

// ---------------------------------------------------------------------------
// Page file assembly
// ---------------------------------------------------------------------------

export function assemblePageFile(
  page: PageIR,
  emittedJSX: string,
  ctx: EmitContext,
  dataSources: Record<string, DataSourceDef>,
): string {
  const parts: string[] = [];

  // 1. "use client" directive
  ctx.needsClientDirective = true; // Pages with state/hooks always need this
  parts.push('"use client";\n');

  // 2. Ensure React imports
  if (page.state && Object.keys(page.state).length > 0) {
    ctx.ensureImport("react", "useState");
  }

  // Check if we need query/mutation hooks
  const usedSources = findUsedDataSources(page);
  const hasQueries = [...usedSources].some((s) => dataSources[s]?.method === "GET");
  const hasMutations = [...usedSources].some((s) => dataSources[s]?.method !== "GET");

  if (hasQueries) {
    ctx.ensureImport("@tanstack/react-query", "useQuery");
  }
  if (hasMutations) {
    ctx.ensureImport("@tanstack/react-query", "useMutation");
    if ([...usedSources].some((s) => dataSources[s]?.onSuccess?.invalidate?.length)) {
      ctx.ensureImport("@tanstack/react-query", "useQueryClient");
    }
  }

  // 3. Imports
  parts.push(formatImports(ctx.getImports()));
  parts.push("");

  // 4. File headers (Zod schemas, type defs)
  for (const header of ctx.getFileHeaders()) {
    parts.push(header);
  }

  // 5. Component name
  const componentName = pageIdToComponentName(page.$id);
  parts.push(`export default function ${componentName}() {`);

  // 6. Hooks
  for (const hook of ctx.getHookCalls()) {
    parts.push(`  ${hook}`);
  }

  // 7. Data source hooks
  const dsHooks = formatDataSourceHooks(dataSources, page);
  if (dsHooks) {
    parts.push(`  ${dsHooks}`);
  }

  // 8. State
  const stateDecls = formatStateDeclarations(page, ctx);
  if (stateDecls) {
    parts.push(`  ${stateDecls}`);
  }

  // 9. Effects
  for (const effect of ctx.getEffects()) {
    parts.push(`  ${effect}`);
  }

  // 10. Helpers (memoized columns, variant maps, etc.)
  for (const helper of ctx.getHelpers()) {
    parts.push(`  ${helper}`);
  }

  // 11. Handlers
  for (const handler of ctx.getHandlers()) {
    parts.push(`  ${handler}`);
  }

  // 12. Return JSX
  parts.push("");
  parts.push("  return (");
  parts.push(`    ${emittedJSX}`);
  parts.push("  );");
  parts.push("}");

  return parts.join("\n");
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pageIdToComponentName(id: string): string {
  return id
    .split(/[-_]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join("") + "Page";
}
