"use client";

/**
 * The Blueprint, at a glance — what the right-hand panel shows once Smith
 * has a definition to show (§25, §109).
 *
 * The approval gate used to be a stage list with a paragraph of names under
 * it: pages joined by dots, entities joined by dots, and a button. Nothing on
 * it said what the application WAS before asking whether to build it. This
 * reads the same Blueprint and lays it out the way a person looks at an app:
 * identity first (name, purpose, language, palette), then the shape of it
 * (how many pages, entities, workflows, requirements), then each of those by
 * name, then the decision.
 *
 * Everything here is read off the Blueprint document. Nothing is stored in
 * component state except which sections are expanded.
 */

import { useState, type ReactNode } from "react";
import {
  ArrowRight,
  BarChart3,
  Blocks,
  Calendar,
  CheckCircle2,
  ChevronRight,
  Database,
  FileText,
  Globe,
  Inbox,
  KanbanSquare,
  LayoutDashboard,
  List,
  ListChecks,
  ListOrdered,
  Loader2,
  Palette,
  Pencil,
  Plus,
  Search,
  Settings,
  Sparkles,
  Workflow as WorkflowIcon,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Doc = Record<string, unknown>;
type Row = Record<string, unknown>;

/**
 * Where the application stands relative to this definition. Derived by the
 * caller from the Blueprint and the run, so the panel never has to guess.
 */
export type BlueprintStatus =
  | { kind: "ready" }
  | { kind: "partial"; missing: number; total: number }
  | { kind: "building" }
  | { kind: "built" };

export interface BlueprintSummaryProps {
  doc: Doc;
  status: BlueprintStatus;
  /** Approve the definition and build (or finish) the application. */
  onBuild: () => void;
  /** Change the definition — which means telling Smith, so this focuses the composer. */
  onEdit: () => void;
  /** §113 — a page card opens that page in the live application, where there is one. */
  onOpenPage?: (route: string) => void;
  className?: string;
}

// ---------------------------------------------------------------------------
// Reading the document
// ---------------------------------------------------------------------------

const rows = (v: unknown): Row[] =>
  Array.isArray(v) ? (v as Row[]).filter((x) => x && typeof x === "object") : [];
const text = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : String(v));

/** The counts the tiles and the transcript card both show. */
export function blueprintCounts(doc: Doc | null | undefined) {
  const d = doc ?? {};
  const data = (d.data as Row | undefined) ?? {};
  return {
    pages: rows(d.pages).length,
    entities: rows(data.entities).length,
    workflows: rows(d.workflows).length,
    requirements: rows(d.requirements).length,
  };
}

export function blueprintName(doc: Doc | null | undefined): string {
  const app = ((doc ?? {}).application as Row | undefined) ?? {};
  return text(app.name) || "Untitled application";
}

/** "en" → "English", in the reader's own language; the bare tag if the runtime cannot say. */
function languageName(tag: string): string {
  try {
    const viewer = typeof navigator !== "undefined" ? navigator.language : "en";
    return new Intl.DisplayNames([viewer, "en"], { type: "language" }).of(tag) ?? tag;
  } catch {
    return tag.toUpperCase();
  }
}

/**
 * Four swatches that stand for the palette: the ground, the tint, the brand
 * colour and the ink — in that order, so the row reads light to dark the way
 * a palette card does. Anything the design system did not name is filled from
 * whatever other colours it declared.
 */
function swatches(colors: Record<string, unknown>): string[] {
  const get = (...keys: string[]) =>
    keys.map((k) => text(colors[k])).find((v) => /^(#|rgb|hsl|oklch)/i.test(v)) ?? "";
  const picked = [
    get("background", "surface", "canvas"),
    get("primary-subtle", "secondary", "accent", "surface-muted"),
    get("primary", "brand"),
    get("text-primary", "foreground", "text", "ink"),
  ];
  const seen = new Set(picked.filter(Boolean).map((c) => c.toLowerCase()));
  const spare = Object.values(colors)
    .map(text)
    .filter((v) => /^(#|rgb|hsl|oklch)/i.test(v) && !seen.has(v.toLowerCase()));
  return picked.map((c) => c || spare.shift() || "").filter(Boolean).slice(0, 4);
}

const PAGE_ICON: Record<string, LucideIcon> = {
  entity_list: List,
  data_explorer: List,
  search_results: Search,
  form: Plus,
  wizard: ListOrdered,
  dashboard: LayoutDashboard,
  command_center: LayoutDashboard,
  analytics: BarChart3,
  record_workspace: FileText,
  document_workspace: FileText,
  split_view: FileText,
  approval_inbox: Inbox,
  kanban: KanbanSquare,
  calendar: Calendar,
  scheduler: Calendar,
  timeline: ListOrdered,
  settings: Settings,
  configuration: Settings,
};

const TRIGGER_LABEL: Record<string, string> = {
  manual: "Manual",
  schedule: "Scheduled",
  webhook: "Webhook",
  api_event: "API event",
  db_change: "On data change",
};

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

/** The application's mark: its initial on its own primary colour. */
export function AppTile({
  doc,
  className,
}: {
  doc: Doc | null | undefined;
  className?: string;
}) {
  const colors = ((doc?.designSystem as Row | undefined)?.colors as Row | undefined) ?? {};
  const brand = text(colors.primary) || text(colors.brand);
  const name = blueprintName(doc);
  return (
    <div
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-2xl bg-primary font-semibold text-white shadow-sm",
        className,
      )}
      style={brand ? { backgroundColor: brand } : undefined}
    >
      {name.trim().charAt(0).toUpperCase()}
    </div>
  );
}

function StatusPill({ status }: { status: BlueprintStatus }) {
  const base =
    "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium";
  switch (status.kind) {
    case "ready":
      return (
        <span className={cn(base, "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300")}>
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Ready to build
        </span>
      );
    case "partial":
      return (
        <span className={cn(base, "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300")}>
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
          {status.missing} of {status.total} page{status.total === 1 ? "" : "s"} unbuilt
        </span>
      );
    case "building":
      return (
        <span className={cn(base, "bg-primary/10 text-primary")}>
          <Loader2 className="h-3 w-3 animate-spin" />
          Building
        </span>
      );
    case "built":
      return (
        <span className={cn(base, "bg-muted text-muted-foreground")}>
          <CheckCircle2 className="h-3 w-3" />
          Built
        </span>
      );
  }
}

function Chip({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs font-medium">
      <Icon className="h-3.5 w-3.5 text-primary" />
      {children}
    </span>
  );
}

const TILE_TONE = {
  sky: "bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300",
  emerald: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  violet: "bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-300",
  orange: "bg-orange-50 text-orange-700 dark:bg-orange-950/40 dark:text-orange-300",
} as const;

function StatTile({
  icon: Icon,
  count,
  label,
  tone,
}: {
  icon: LucideIcon;
  count: number;
  label: string;
  tone: keyof typeof TILE_TONE;
}) {
  return (
    <div className={cn("rounded-xl p-3", TILE_TONE[tone])}>
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/70 dark:bg-white/10">
        <Icon className="h-4 w-4" />
      </span>
      <p className="mt-2 text-xl font-semibold tabular-nums leading-none">{count}</p>
      <p className="mt-1 text-xs opacity-80">{label}</p>
    </div>
  );
}

/**
 * A titled block with a "View all (N)" control when there is more than it
 * shows. The control is a toggle, not a link: everything it reveals is
 * already in the document, so it opens in place rather than sending the
 * reader somewhere else to see the rest.
 */
function Section({
  title,
  total,
  shown,
  expanded,
  onToggle,
  moreLabel = "View all",
  children,
}: {
  title: string;
  total: number;
  shown: number;
  expanded: boolean;
  onToggle: () => void;
  moreLabel?: string;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">{title}</h3>
        {total > shown && (
          <button
            type="button"
            onClick={onToggle}
            className="text-xs font-medium text-primary hover:underline"
          >
            {expanded ? "Show less" : `${moreLabel} (${total})`}
          </button>
        )}
      </div>
      {children}
    </section>
  );
}

// ---------------------------------------------------------------------------
// The panel
// ---------------------------------------------------------------------------

const PAGES_SHOWN = 4;
const ENTITIES_SHOWN = 2;
const CAPABILITIES_SHOWN = 3;
const REQUIREMENTS_SHOWN = 3;

export function BlueprintSummary({
  doc,
  status,
  onBuild,
  onEdit,
  onOpenPage,
  className,
}: BlueprintSummaryProps) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const toggle = (k: string) => setOpen((o) => ({ ...o, [k]: !o[k] }));

  const app = (doc.application as Row | undefined) ?? {};
  const product = (doc.product as Row | undefined) ?? {};
  const design = (doc.designSystem as Row | undefined) ?? {};
  const data = (doc.data as Row | undefined) ?? {};
  const counts = blueprintCounts(doc);

  const pages = rows(doc.pages);
  const entities = rows(data.entities);
  const workflows = rows(doc.workflows);
  const requirements = rows(doc.requirements);
  // Before the build, the product's capabilities are what the pages will do;
  // an older document without them still has its workflows to name.
  const capabilities = rows(product.capabilities);
  const coreItems: Array<{ key: string; name: string; detail: string }> =
    capabilities.length > 0
      ? capabilities.map((c, i) => ({
          key: text(c.id) || `cap-${i}`,
          name: text(c.name),
          detail: text(c.description),
        }))
      : workflows.map((w, i) => ({
          key: text(w.id) || `wf-${i}`,
          name: text(w.name),
          detail: TRIGGER_LABEL[text((w.trigger as Row | undefined)?.kind)] ?? "",
        }));

  const locale = text(product.locale) || "en";
  const palette = swatches((design.colors as Record<string, unknown> | undefined) ?? {});
  const version = typeof doc.version === "number" ? doc.version : null;

  const visiblePages = open.pages ? pages : pages.slice(0, PAGES_SHOWN);
  const visibleEntities = open.entities ? entities : entities.slice(0, ENTITIES_SHOWN);
  const visibleCore = open.core ? coreItems : coreItems.slice(0, CAPABILITIES_SHOWN);
  const visibleReqs = open.requirements
    ? requirements
    : requirements.slice(0, REQUIREMENTS_SHOWN);

  const canBuild = status.kind === "ready" || status.kind === "partial";
  const buildLabel =
    status.kind === "partial"
      ? "Finish the missing pages"
      : status.kind === "building"
        ? "Building…"
        : "Build app";

  return (
    <div className={cn("flex h-full min-h-0 flex-col", className)}>
      <header className="flex shrink-0 items-center gap-2 border-b px-4 py-3">
        <Blocks className="h-4 w-4 text-primary" />
        <h2 className="text-sm font-semibold">App Blueprint</h2>
        {version !== null && (
          <span className="rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
            v{version}
          </span>
        )}
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {/* Identity — the one card that says what this is. */}
        <div className="rounded-2xl border bg-card p-4 shadow-sm">
          <div className="flex items-start gap-3">
            <AppTile doc={doc} className="h-14 w-14 text-2xl" />
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2">
                <h3 className="truncate text-lg font-semibold leading-tight">
                  {blueprintName(doc)}
                </h3>
                <StatusPill status={status} />
              </div>
              {text(app.description) && (
                <p className="mt-1 line-clamp-3 text-sm text-muted-foreground">
                  {text(app.description)}
                </p>
              )}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Chip icon={Globe}>{languageName(locale)}</Chip>
            {palette.length > 0 && (
              <>
                <Chip icon={Palette}>Palette</Chip>
                <span className="flex items-center gap-1" aria-label="Palette swatches">
                  {palette.map((c) => (
                    <span
                      key={c}
                      className="h-5 w-5 rounded-full border border-black/10 dark:border-white/10"
                      style={{ backgroundColor: c }}
                      title={c}
                    />
                  ))}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Shape — the four counts. */}
        <div className="grid grid-cols-4 gap-2">
          <StatTile icon={FileText} count={counts.pages} label={counts.pages === 1 ? "Page" : "Pages"} tone="sky" />
          <StatTile icon={Database} count={counts.entities} label="Data model" tone="emerald" />
          <StatTile icon={WorkflowIcon} count={counts.workflows} label={counts.workflows === 1 ? "Workflow" : "Workflows"} tone="violet" />
          <StatTile icon={ListChecks} count={counts.requirements} label="Requirements" tone="orange" />
        </div>

        {pages.length > 0 && (
          <Section
            title="Pages"
            total={pages.length}
            shown={PAGES_SHOWN}
            expanded={!!open.pages}
            onToggle={() => toggle("pages")}
          >
            <ul className="grid grid-cols-2 gap-2">
              {visiblePages.map((p, i) => {
                const route = text(p.route);
                const Icon = PAGE_ICON[text(p.pattern)] ?? FileText;
                const body = (
                  <>
                    <div className="flex items-center gap-2.5">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{text(p.name) || route}</span>
                        <span className="block truncate font-mono text-[11px] text-muted-foreground">{route}</span>
                      </span>
                      {onOpenPage && route && (
                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                      )}
                    </div>
                    {text(p.purpose) && (
                      <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{text(p.purpose)}</p>
                    )}
                  </>
                );
                const card = "block w-full rounded-xl border bg-card p-3 text-left";
                return (
                  <li key={text(p.id) || route || i}>
                    {onOpenPage && route ? (
                      <button type="button" onClick={() => onOpenPage(route)} className={cn(card, "hover:bg-muted/60")}>
                        {body}
                      </button>
                    ) : (
                      <div className={card}>{body}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          </Section>
        )}

        {(entities.length > 0 || coreItems.length > 0) && (
          <div className="grid grid-cols-2 gap-3">
            {entities.length > 0 && (
              <Section
                title="Data model"
                total={entities.length}
                shown={ENTITIES_SHOWN}
                expanded={!!open.entities}
                onToggle={() => toggle("entities")}
              >
                <ul className="space-y-2">
                  {visibleEntities.map((e, i) => {
                    const fields = rows(e.fields).map((f) => text(f.name)).filter(Boolean);
                    return (
                      <li key={text(e.id) || i} className="flex items-start gap-2.5 rounded-xl border bg-card p-3">
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
                          <Database className="h-4 w-4" />
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium">{text(e.name)}</span>
                          <span className="block text-xs text-muted-foreground">
                            {fields.length} field{fields.length === 1 ? "" : "s"}
                          </span>
                          {fields.length > 0 && (
                            <span className="mt-0.5 block truncate text-[11px] text-muted-foreground/80">
                              {fields.join(", ")}
                            </span>
                          )}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </Section>
            )}

            {coreItems.length > 0 && (
              <Section
                title="Core capabilities"
                total={coreItems.length}
                shown={CAPABILITIES_SHOWN}
                expanded={!!open.core}
                onToggle={() => toggle("core")}
              >
                <ul className="space-y-1.5">
                  {visibleCore.map((c) => (
                    <li key={c.key} className="flex items-start gap-2.5" title={c.detail || undefined}>
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <Sparkles className="h-3.5 w-3.5" />
                      </span>
                      <span className="min-w-0 pt-1 text-sm leading-tight">
                        <span className="block truncate">{c.name}</span>
                        {c.detail && (
                          <span className="block truncate text-[11px] text-muted-foreground">{c.detail}</span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </Section>
            )}
          </div>
        )}

        {requirements.length > 0 && (
          <Section
            title="Requirements"
            total={requirements.length}
            shown={REQUIREMENTS_SHOWN}
            expanded={!!open.requirements}
            onToggle={() => toggle("requirements")}
          >
            <ul className="space-y-1.5">
              {visibleReqs.map((r, i) => (
                <li key={text(r.id) || i} className="flex items-start gap-2 text-sm">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                  <span className="line-clamp-2">{text(r.description) || text(r.name) || text(r.id)}</span>
                </li>
              ))}
            </ul>
            {!open.requirements && requirements.length > REQUIREMENTS_SHOWN && (
              <button
                type="button"
                onClick={() => toggle("requirements")}
                className="mt-2 flex items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground"
              >
                <Plus className="h-3.5 w-3.5" />
                {requirements.length - REQUIREMENTS_SHOWN} more requirement
                {requirements.length - REQUIREMENTS_SHOWN === 1 ? "" : "s"}
              </button>
            )}
          </Section>
        )}
      </div>

      {/* §25 — the decision. Nothing further is spent until this is answered. */}
      <footer className="grid shrink-0 grid-cols-2 gap-2 border-t bg-background p-3">
        <button
          type="button"
          onClick={onEdit}
          className="flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium hover:bg-muted"
        >
          <Pencil className="h-4 w-4" />
          Edit blueprint
        </button>
        {status.kind === "built" ? (
          <p className="flex items-center justify-center rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
            Built from this definition
          </p>
        ) : (
          <button
            type="button"
            onClick={onBuild}
            disabled={!canBuild}
            className="flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {status.kind === "building" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : null}
            {buildLabel}
            {status.kind !== "building" && <ArrowRight className="h-4 w-4" />}
          </button>
        )}
      </footer>
    </div>
  );
}

export default BlueprintSummary;

/** "2 pages · 1 data model · 3 workflows · 9 requirements" — the transcript card's one line. */
export function blueprintCountsLine(doc: Doc | null | undefined): string {
  const c = blueprintCounts(doc);
  const n = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`;
  return [
    n(c.pages, "page", "pages"),
    n(c.entities, "data model", "data models"),
    n(c.workflows, "workflow", "workflows"),
    n(c.requirements, "requirement", "requirements"),
  ].join(" · ");
}
