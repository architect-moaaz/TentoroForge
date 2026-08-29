"use client";

/**
 * The Application Workspace (§112).
 *
 * Three panes, as the PRD draws them: the Blueprint on the left, the live
 * application in the middle, Smith on the right. Smith is a column, not a tab
 * — §79 requires it to stay accessible in every mode.
 *
 * This route exists because the product had no way to reach the Blueprint
 * engine. `frontend/` contained no reference to the word "blueprint", and the
 * engine's only HTTP entry — POST /api/projects/{id}/generate/blueprint — was
 * referenced nowhere outside a test asserting the route registers. The 20-node
 * DAG, its verification edges and its projections all ran correctly and were
 * unreachable from anything a user touches. So did GET .../blueprint, which is
 * §110's tree and §113's link target, and which this page is the first caller
 * of.
 */

import { use, useCallback, useEffect, useState } from "react";
import { ChevronRight, ChevronDown, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { SmithPanel } from "@/components/smith/SmithPanel";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

/** §110's tree, in the PRD's own grouping and order. */
const TREE: Array<{ group: string; sections: Array<[string, string]> }> = [
  {
    group: "Product",
    sections: [
      ["requirements", "Requirements"],
      ["roles", "Users & Roles"],
      ["modules", "Modules"],
    ],
  },
  {
    group: "Experience",
    sections: [
      ["pages", "Pages"],
      ["navigation", "Navigation"],
      ["components", "Components"],
    ],
  },
  {
    group: "Logic",
    sections: [
      ["workflows", "Workflows"],
      ["businessRules", "Business Rules"],
    ],
  },
  { group: "Data", sections: [["data", "Entities"]] },
  {
    group: "Platform",
    sections: [
      ["apis", "APIs"],
      ["integrations", "Integrations"],
      ["security", "Security"],
      ["deployment", "Deployment"],
    ],
  },
];

type Blueprint = Record<string, unknown>;

export default function WorkspacePage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = use(params);
  const [doc, setDoc] = useState<Blueprint | null>(null);
  const [missing, setMissing] = useState(false);
  const [route, setRoute] = useState<string | null>(null);
  const [previewNonce, setPreviewNonce] = useState(0);

  const loadBlueprint = useCallback(async () => {
    const token =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;
    const res = await fetch(
      `${API_BASE}/api/projects/${projectId}/blueprint`,
      {
        credentials: "include",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
    ).catch(() => null);

    // 404 is an ordinary state, not a failure: the project exists and nothing
    // has been generated into it yet.
    if (!res || res.status === 404) {
      setMissing(true);
      setDoc(null);
      return;
    }
    if (!res.ok || res.redirected) return;
    setMissing(false);
    setDoc((await res.json()) as Blueprint);
  }, [projectId]);

  useEffect(() => {
    void loadBlueprint();
  }, [loadBlueprint]);

  // A finished run changes both panes: the Blueprint gained sections and the
  // preview is serving new files.
  const onRunComplete = useCallback(() => {
    void loadBlueprint();
    setPreviewNonce((n) => n + 1);
  }, [loadBlueprint]);

  const pages = (doc?.pages as Array<Record<string, unknown>>) ?? [];

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center justify-between border-b px-4">
        <h1 className="text-sm font-semibold">Application Workspace</h1>
        <button
          onClick={onRunComplete}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </header>

      <div className="flex min-h-0 flex-1">
        <BlueprintTree
          doc={doc}
          missing={missing}
          pages={pages}
          activeRoute={route}
          onSelectRoute={setRoute}
        />

        <main className="min-w-0 flex-1 bg-muted/30">
          {route ? (
            <iframe
              key={`${route}-${previewNonce}`}
              src={`/api/projects/${projectId}/preview${route}`}
              className="h-full w-full border-0 bg-background"
              title="Live application"
            />
          ) : (
            <div className="flex h-full items-center justify-center p-8 text-center">
              <p className="max-w-xs text-sm text-muted-foreground">
                {missing
                  ? "No application yet. Describe one to Smith and it will be built here."
                  : "Select a page in the Blueprint to open it."}
              </p>
            </div>
          )}
        </main>

        <SmithPanel
          projectId={projectId}
          onRunComplete={onRunComplete}
          className="w-[380px] shrink-0"
        />
      </div>
    </div>
  );
}

/**
 * §110's Blueprint tree, and half of §113's link.
 *
 * Selecting Pages → a page navigates the preview to that page's route. The
 * PRD requires the reverse direction too — the preview telling the Blueprint
 * what is on screen — which needs the preview to post its route back, and is
 * not built here.
 */
function BlueprintTree({
  doc,
  missing,
  pages,
  activeRoute,
  onSelectRoute,
}: {
  doc: Blueprint | null;
  missing: boolean;
  pages: Array<Record<string, unknown>>;
  activeRoute: string | null;
  onSelectRoute: (route: string) => void;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({ Experience: true });

  const countOf = (key: string): number | null => {
    if (!doc) return null;
    if (key === "data") {
      const entities = (doc.data as { entities?: unknown[] } | undefined)
        ?.entities;
      return Array.isArray(entities) ? entities.length : null;
    }
    const v = doc[key];
    if (Array.isArray(v)) return v.length;
    if (v && typeof v === "object") return Object.keys(v).length || null;
    return null;
  };

  return (
    <aside className="w-[240px] shrink-0 overflow-y-auto border-r p-3">
      <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Blueprint
      </h2>

      {missing && (
        <p className="px-1 text-xs text-muted-foreground">
          Nothing generated yet.
        </p>
      )}

      {TREE.map(({ group, sections }) => (
        <div key={group} className="mb-1">
          <button
            onClick={() => setOpen((o) => ({ ...o, [group]: !o[group] }))}
            className="flex w-full items-center gap-1 rounded px-1 py-1 text-xs font-medium hover:bg-muted"
          >
            {open[group] ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            {group}
          </button>

          {open[group] && (
            <ul className="ml-4 space-y-0.5">
              {sections.map(([key, label]) => {
                const n = countOf(key);
                return (
                  <li key={key}>
                    <div className="flex items-center justify-between rounded px-1 py-0.5 text-xs">
                      <span
                        className={cn(
                          n === null && "text-muted-foreground/50",
                        )}
                      >
                        {label}
                      </span>
                      {n !== null && (
                        <span className="tabular-nums text-muted-foreground">
                          {n}
                        </span>
                      )}
                    </div>

                    {/* §113 — selecting a page navigates the preview. */}
                    {key === "pages" && pages.length > 0 && (
                      <ul className="ml-2 mt-0.5 space-y-0.5 border-l pl-2">
                        {pages.map((p, i) => {
                          const r = String(p.route ?? "");
                          return (
                            <li key={String(p.id ?? i)}>
                              <button
                                onClick={() => r && onSelectRoute(r)}
                                className={cn(
                                  "w-full truncate rounded px-1 py-0.5 text-left text-xs hover:bg-muted",
                                  activeRoute === r
                                    ? "bg-muted font-medium"
                                    : "text-muted-foreground",
                                )}
                              >
                                {String(p.name ?? p.id ?? r)}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ))}
    </aside>
  );
}
