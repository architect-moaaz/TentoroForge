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

import { use, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronRight, ChevronDown, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
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

/**
 * §94's preview states, as the Workspace sees them.
 *
 * `servePath` is where the browser reaches the running app: the backend
 * registers the dev server under the project's short id and starts it with
 * that prefix as its basePath, so the same-origin rewrite of /api/projects/*
 * carries the frame, and every asset the app emits, through the proxy. The
 * frame used to compose `/preview/<route>` from the UUID in this page's URL,
 * which no route serves — selecting a page opened a 404.
 */
type Preview =
  | { status: "stopped" }
  | { status: "starting" }
  | { status: "running"; servePath: string }
  | { status: "failed"; reason: string };

interface PreviewStatus {
  running: boolean;
  port: number | null;
  servePath: string;
}

export default function WorkspacePage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = use(params);
  const search = useSearchParams();
  return (
    <Workspace
      projectId={projectId}
      brief={search.get("brief") ?? undefined}
      evidence={search.getAll("doc")}
    />
  );
}

export function Workspace({
  projectId,
  brief,
  evidence,
}: {
  projectId: string;
  brief?: string;
  evidence: string[];
}) {
  const [doc, setDoc] = useState<Blueprint | null>(null);
  const [missing, setMissing] = useState(false);
  const [route, setRoute] = useState<string | null>(null);
  const [previewNonce, setPreviewNonce] = useState(0);
  const [preview, setPreview] = useState<Preview>({ status: "stopped" });
  // Read by callbacks that must not re-create themselves on every state
  // change — a start already in flight is not started twice.
  const previewRef = useRef(preview);
  previewRef.current = preview;

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

  // A preview left running by an earlier visit is reused, not restarted.
  useEffect(() => {
    let cancelled = false;
    api
      .get<PreviewStatus>(`/api/projects/${projectId}/preview/status`)
      .then((s) => {
        if (!cancelled && s.running && previewRef.current.status === "stopped") {
          setPreview({ status: "running", servePath: s.servePath });
        }
      })
      .catch(() => {
        /* not running, or not reachable — selecting a page will start it */
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  /** Start the dev server unless it is already up or on its way. */
  const ensurePreview = useCallback(async () => {
    const current = previewRef.current.status;
    if (current === "running" || current === "starting") return;
    setPreview({ status: "starting" });
    try {
      const started = await api.post<PreviewStatus>(
        `/api/projects/${projectId}/preview/start`,
      );
      setPreview({ status: "running", servePath: started.servePath });
    } catch (err) {
      setPreview({
        status: "failed",
        reason: err instanceof Error ? err.message : "The preview could not start.",
      });
    }
  }, [projectId]);

  // §113 — selecting a page opens it in the live application. The first
  // selection is what starts the application; nothing else on this page
  // needs it running.
  const selectRoute = useCallback(
    (r: string) => {
      setRoute(r);
      void ensurePreview();
    },
    [ensurePreview],
  );

  // A finished run changes both panes: the Blueprint gained sections and the
  // preview is serving new files. A preview that could not start because the
  // application did not exist yet can start now.
  const onRunComplete = useCallback(() => {
    void loadBlueprint();
    setPreviewNonce((n) => n + 1);
    if (previewRef.current.status === "failed" && route) void ensurePreview();
  }, [loadBlueprint, ensurePreview, route]);

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
          onSelectRoute={selectRoute}
        />

        <main className="min-w-0 flex-1 bg-muted/30">
          {route ? (
            <LiveApplication
              route={route}
              preview={preview}
              nonce={previewNonce}
              onRetry={ensurePreview}
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
          initialBrief={brief}
          evidence={evidence}
          blueprint={doc}
          onRunComplete={onRunComplete}
          className="w-[380px] shrink-0"
        />
      </div>
    </div>
  );
}

/** The middle pane: the page asked for, or why it is not on screen yet. */
function LiveApplication({
  route,
  preview,
  nonce,
  onRetry,
}: {
  route: string;
  preview: Preview;
  nonce: number;
  onRetry: () => void;
}) {
  if (preview.status === "running") {
    return (
      <iframe
        key={`${route}-${nonce}`}
        src={`${preview.servePath}${route}`}
        className="h-full w-full border-0 bg-background"
        title="Live application"
      />
    );
  }

  return (
    <div className="flex h-full items-center justify-center p-8 text-center">
      {preview.status === "failed" ? (
        <div className="max-w-sm space-y-3">
          <p className="text-sm text-muted-foreground">
            The preview could not start: {preview.reason}
          </p>
          <button
            onClick={onRetry}
            className="rounded-md border px-3 py-1.5 text-xs hover:bg-muted"
          >
            Try again
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Starting the preview…
        </div>
      )}
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
