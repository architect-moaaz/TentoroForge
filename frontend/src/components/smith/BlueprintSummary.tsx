"use client";

/**
 * The Blueprint, at a glance — what the right-hand panel shows once Smith
 * has a definition to show (§25, §109).
 *
 * One card. Identity at the top (mark, name, version, purpose, language,
 * palette, where it stands), the shape of the application as a row of four
 * counts, then each of those as a section that opens and closes in place,
 * and the decision in the footer. Everything is read off the Blueprint
 * document; the only state here is which sections are open.
 */

import { useState, type ReactNode } from "react";
import {
  ArrowRight,
  BarChart3,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  FilePlus2,
  FileText,
  Globe,
  Inbox,
  KanbanSquare,
  LayoutDashboard,
  ListChecks,
  ListOrdered,
  Loader2,
  Pencil,
  Search,
  Settings,
  Sparkles,
  SquarePlus,
  Table2,
  ToggleLeft,
  Trash2,
  Zap,
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
  /** §113 — a page row opens that page in the live application, where there is one. */
  onOpenPage?: (route: string) => void;
  className?: string;
}

// ---------------------------------------------------------------------------
// Reading the document
// ---------------------------------------------------------------------------

const rows = (v: unknown): Row[] =>
  Array.isArray(v) ? (v as Row[]).filter((x) => x && typeof x === "object") : [];
const text = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : String(v));
const isColor = (v: string) => /^(#|rgb|hsl|oklch)/i.test(v);

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

/** The application's brand colour, as its design system names it. */
function brandOf(doc: Doc | null | undefined): string {
  const colors = ((doc?.designSystem as Row | undefined)?.colors as Row | undefined) ?? {};
  const c = text(colors.primary) || text(colors.brand);
  return isColor(c) ? c : "";
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
 * Four swatches that stand for the palette — ground, tint, brand, ink — so
 * the row reads light to dark the way a palette card does. The brand swatch
 * is marked so it can be ringed. Anything the design system did not name is
 * filled from whatever other colours it declared.
 */
function swatches(colors: Record<string, unknown>): Array<{ value: string; brand: boolean }> {
  const get = (...keys: string[]) => keys.map((k) => text(colors[k])).find(isColor) ?? "";
  const picked = [
    { value: get("background", "surface", "canvas"), brand: false },
    { value: get("primary-subtle", "secondary", "accent", "surface-muted"), brand: false },
    { value: get("primary", "brand"), brand: true },
    { value: get("text-primary", "foreground", "text", "ink"), brand: false },
  ];
  const seen = new Set(picked.map((p) => p.value.toLowerCase()).filter(Boolean));
  const spare = Object.values(colors).map(text).filter((v) => isColor(v) && !seen.has(v.toLowerCase()));
  return picked
    .map((p) => (p.value ? p : { value: spare.shift() ?? "", brand: false }))
    .filter((p) => p.value)
    .slice(0, 4);
}

const PAGE_ICON: Record<string, LucideIcon> = {
  entity_list: Table2,
  data_explorer: Table2,
  search_results: Search,
  form: FilePlus2,
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

/** A capability's icon, from what its name says it does. */
function capabilityIcon(name: string): LucideIcon {
  const n = name.toLowerCase();
  if (/\b(toggle|switch|status|flip|mark)\b/.test(n)) return ToggleLeft;
  if (/\b(creat|new|add|capture|submit)/.test(n)) return SquarePlus;
  if (/\b(delet|remov|archiv)/.test(n)) return Trash2;
  if (/\b(edit|updat|chang|renam)/.test(n)) return Pencil;
  if (/\b(list|view|filter|search|brows|track|report|dashboard)/.test(n)) return ListChecks;
  return Sparkles;
}

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

/**
 * Section tints. Class strings are written out in full so Tailwind can see
 * them; a template would compile to nothing.
 */
const TONE = {
  sky: {
    dot: "bg-sky-600",
    icon: "bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300",
  },
  violet: {
    dot: "bg-violet-600",
    icon: "bg-violet-100 text-violet-700 dark:bg-violet-950/60 dark:text-violet-300",
  },
  emerald: {
    dot: "bg-emerald-700",
    icon: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300",
  },
  orange: {
    dot: "bg-orange-700",
    icon: "bg-orange-100 text-orange-700 dark:bg-orange-950/60 dark:text-orange-300",
  },
} as const;
type Tone = keyof typeof TONE;

/** The application's mark: its initial, in its own brand colour on a tint of it. */
export function AppTile({
  doc,
  className,
}: {
  doc: Doc | null | undefined;
  className?: string;
}) {
  const brand = brandOf(doc);
  const name = blueprintName(doc);
  return (
    <div
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-xl bg-primary/10 font-semibold text-primary",
        className,
      )}
      style={
        brand
          ? { backgroundColor: `color-mix(in srgb, ${brand} 14%, transparent)`, color: brand }
          : undefined
      }
    >
      {name.trim().charAt(0).toUpperCase()}
    </div>
  );
}

function StatusPill({ status }: { status: BlueprintStatus }) {
  const base =
    "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium";
  switch (status.kind) {
    case "ready":
      return (
        <span className={cn(base, "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300")}>
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Ready to build
        </span>
      );
    case "partial":
      return (
        <span className={cn(base, "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300")}>
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
          {status.missing} of {status.total} page{status.total === 1 ? "" : "s"} unbuilt
        </span>
      );
    case "building":
      return (
        <span className={cn(base, "bg-primary/10 text-primary")}>
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Building
        </span>
      );
    case "built":
      return (
        <span className={cn(base, "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300")}>
          <Check className="h-3.5 w-3.5" />
          Built
        </span>
      );
  }
}

function IconSquare({ icon: Icon, tone, className }: { icon: LucideIcon; tone: Tone; className?: string }) {
  return (
    <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", TONE[tone].icon, className)}>
      <Icon className="h-5 w-5" />
    </span>
  );
}

function Stat({ icon, tone, count, label }: { icon: LucideIcon; tone: Tone; count: number; label: string }) {
  return (
    <div className="flex items-center gap-3 px-4 py-4">
      <IconSquare icon={icon} tone={tone} />
      <span>
        <span className="block text-2xl font-semibold leading-none tabular-nums">{count}</span>
        <span className="mt-1 block text-sm text-muted-foreground">{label}</span>
      </span>
    </div>
  );
}

/** A section of the card that opens and closes in place. */
function Section({
  title,
  tone,
  count,
  open,
  onToggle,
  children,
}: {
  title: string;
  tone: Tone;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section className="border-t">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-5 py-3.5 text-left hover:bg-muted/40"
      >
        <span className={cn("h-2 w-2 rounded-full", TONE[tone].dot)} />
        <span className="text-base font-semibold">{title}</span>
        {!open && <span className="text-sm text-muted-foreground tabular-nums">{count}</span>}
        <ChevronDown
          className={cn(
            "ml-auto h-4 w-4 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && <div className="px-5 pb-4">{children}</div>}
    </section>
  );
}

/** "Show 4 more" under a list that was cut short. */
function ShowMore({ hidden, onClick }: { hidden: number; onClick: () => void }) {
  if (hidden <= 0) return null;
  return (
    <button
      type="button"
      onClick={onClick}
      className="mt-2 text-sm font-medium text-primary hover:underline"
    >
      Show {hidden} more
    </button>
  );
}

// ---------------------------------------------------------------------------
// The card
// ---------------------------------------------------------------------------

const PAGES_SHOWN = 6;
const ENTITIES_SHOWN = 3;
const CAPABILITIES_SHOWN = 5;
const REQUIREMENTS_SHOWN = 8;

export function BlueprintSummary({
  doc,
  status,
  onBuild,
  onEdit,
  onOpenPage,
  className,
}: BlueprintSummaryProps) {
  // Requirements start closed: they are the longest list and the one a
  // reader checks last, after seeing what the application is.
  const [open, setOpen] = useState<Record<string, boolean>>({
    pages: true,
    entities: true,
    core: true,
    requirements: false,
  });
  const [all, setAll] = useState<Record<string, boolean>>({});
  const toggle = (k: string) => setOpen((o) => ({ ...o, [k]: !o[k] }));
  const showAll = (k: string) => setAll((a) => ({ ...a, [k]: true }));

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
          detail:
            text(w.purpose) ||
            (TRIGGER_LABEL[text((w.trigger as Row | undefined)?.kind)] ?? ""),
        }));

  const locale = text(product.locale) || "en";
  const palette = swatches((design.colors as Record<string, unknown> | undefined) ?? {});
  const version = typeof doc.version === "number" ? doc.version : null;

  const cut = <T,>(key: string, list: T[], n: number) => (all[key] ? list : list.slice(0, n));
  const visiblePages = cut("pages", pages, PAGES_SHOWN);
  const visibleEntities = cut("entities", entities, ENTITIES_SHOWN);
  const visibleCore = cut("core", coreItems, CAPABILITIES_SHOWN);
  const visibleReqs = cut("requirements", requirements, REQUIREMENTS_SHOWN);

  return (
    <div className={cn("flex h-full min-h-0 flex-col", className)}>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="@container overflow-hidden rounded-2xl border bg-card shadow-sm">
          {/* Identity — the one block that says what this is. */}
          <div className="p-5">
            <div className="flex items-start gap-4">
              <AppTile doc={doc} className="h-14 w-14 text-2xl" />
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-baseline gap-2">
                    <h2 className="truncate text-xl font-semibold leading-tight">
                      {blueprintName(doc)}
                    </h2>
                    {version !== null && (
                      <span className="shrink-0 font-mono text-xs text-muted-foreground">v{version}</span>
                    )}
                  </div>
                  <StatusPill status={status} />
                </div>
                {text(app.description) && (
                  <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                    {text(app.description)}
                  </p>
                )}
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm">
                <Globe className="h-4 w-4 text-muted-foreground" />
                {languageName(locale)}
              </span>
              {palette.length > 0 && (
                <span
                  className="inline-flex items-center gap-1.5 rounded-full border px-2 py-1.5"
                  aria-label="Palette swatches"
                >
                  {palette.map((s) => (
                    <span
                      key={s.value}
                      className={cn(
                        "h-5 w-5 rounded-full border border-black/10 dark:border-white/10",
                        s.brand && "ring-2 ring-offset-1 ring-offset-card",
                      )}
                      style={{ backgroundColor: s.value, ...(s.brand ? { ["--tw-ring-color" as string]: s.value } : {}) }}
                      title={s.value}
                    />
                  ))}
                </span>
              )}
            </div>
          </div>

          {/* Shape — the four counts. */}
          {/* Two by two in the side column, four across when the card is wide:
              a container query, because the panel's width is not the page's. */}
          <div className="grid grid-cols-2 border-t @xl:grid-cols-4">
            <div className="border-b border-r @xl:border-b-0">
              <Stat icon={Table2} tone="sky" count={counts.pages} label={counts.pages === 1 ? "Page" : "Pages"} />
            </div>
            <div className="border-b @xl:border-b-0 @xl:border-r">
              <Stat icon={Database} tone="violet" count={counts.entities} label="Data model" />
            </div>
            <div className="border-r">
              <Stat icon={Zap} tone="emerald" count={counts.workflows} label={counts.workflows === 1 ? "Workflow" : "Workflows"} />
            </div>
            <Stat icon={ListChecks} tone="orange" count={counts.requirements} label="Requirements" />
          </div>

          {pages.length > 0 && (
            <Section title="Pages" tone="sky" count={pages.length} open={!!open.pages} onToggle={() => toggle("pages")}>
              <ul className="divide-y">
                {visiblePages.map((p, i) => {
                  const route = text(p.route);
                  const Icon = PAGE_ICON[text(p.pattern)] ?? FileText;
                  const body = (
                    <>
                      <IconSquare icon={Icon} tone="sky" />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline gap-2">
                          <span className="truncate text-base font-medium">{text(p.name) || route}</span>
                          <span className="truncate font-mono text-sm text-muted-foreground">{route}</span>
                        </span>
                        {text(p.purpose) && (
                          <span className="mt-0.5 line-clamp-2 text-sm text-muted-foreground">
                            {text(p.purpose)}
                          </span>
                        )}
                      </span>
                      {onOpenPage && route && <ChevronRight className="h-4 w-4 shrink-0 self-center text-muted-foreground" />}
                    </>
                  );
                  return (
                    <li key={text(p.id) || route || i}>
                      {onOpenPage && route ? (
                        <button
                          type="button"
                          onClick={() => onOpenPage(route)}
                          className="flex w-full items-start gap-3 py-3 text-left hover:bg-muted/40"
                        >
                          {body}
                        </button>
                      ) : (
                        <div className="flex items-start gap-3 py-3">{body}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
              <ShowMore hidden={pages.length - visiblePages.length} onClick={() => showAll("pages")} />
            </Section>
          )}

          {entities.length > 0 && (
            <Section title="Data model" tone="violet" count={entities.length} open={!!open.entities} onToggle={() => toggle("entities")}>
              <ul className="divide-y">
                {visibleEntities.map((e, i) => {
                  const fields = rows(e.fields).map((f) => text(f.name)).filter(Boolean);
                  return (
                    <li key={text(e.id) || i} className="py-3">
                      <div className="flex items-center gap-3">
                        <IconSquare icon={Database} tone="violet" />
                        <span className="flex items-baseline gap-2">
                          <span className="text-base font-medium">{text(e.name)}</span>
                          <span className="text-sm text-muted-foreground">
                            {fields.length} field{fields.length === 1 ? "" : "s"}
                          </span>
                        </span>
                      </div>
                      {fields.length > 0 && (
                        <ul className="mt-3 flex flex-wrap gap-1.5">
                          {fields.map((f) => (
                            <li key={f}>
                              <code className="rounded-md border bg-muted/50 px-2 py-1 font-mono text-sm">{f}</code>
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
              <ShowMore hidden={entities.length - visibleEntities.length} onClick={() => showAll("entities")} />
            </Section>
          )}

          {coreItems.length > 0 && (
            <Section title="Core capabilities" tone="emerald" count={coreItems.length} open={!!open.core} onToggle={() => toggle("core")}>
              <ul className="divide-y">
                {visibleCore.map((c) => (
                  <li key={c.key} className="flex items-start gap-3 py-3">
                    <IconSquare icon={capabilityIcon(c.name)} tone="emerald" />
                    <span className="min-w-0">
                      <span className="block text-base font-medium">{c.name}</span>
                      {c.detail && (
                        <span className="mt-0.5 line-clamp-2 text-sm text-muted-foreground">{c.detail}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
              <ShowMore hidden={coreItems.length - visibleCore.length} onClick={() => showAll("core")} />
            </Section>
          )}

          {requirements.length > 0 && (
            <Section title="Requirements" tone="orange" count={requirements.length} open={!!open.requirements} onToggle={() => toggle("requirements")}>
              <ul className="divide-y">
                {visibleReqs.map((r, i) => (
                  <li key={text(r.id) || i} className="flex items-start gap-3 py-2.5 text-sm">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                    <span>{text(r.description) || text(r.name) || text(r.id)}</span>
                  </li>
                ))}
              </ul>
              <ShowMore hidden={requirements.length - visibleReqs.length} onClick={() => showAll("requirements")} />
            </Section>
          )}

          {/* §25 — the decision. Nothing further is spent until this is answered. */}
          <footer className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 px-5 py-4">
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              {status.kind === "built" && (
                <>
                  <Check className="h-4 w-4 text-emerald-600" />
                  Built from this definition
                </>
              )}
              {status.kind === "ready" && "Nothing built from this definition yet"}
              {status.kind === "partial" &&
                `${status.missing} of ${status.total} page${status.total === 1 ? "" : "s"} still to compose`}
              {status.kind === "building" && (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Building the application
                </>
              )}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onEdit}
                className="flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-medium hover:bg-muted"
              >
                <Pencil className="h-4 w-4" />
                Edit blueprint
              </button>
              {(status.kind === "ready" || status.kind === "partial") && (
                <button
                  type="button"
                  onClick={onBuild}
                  className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                >
                  {status.kind === "partial" ? "Finish the missing pages" : "Build app"}
                  <ArrowRight className="h-4 w-4" />
                </button>
              )}
            </div>
          </footer>
        </div>
      </div>
    </div>
  );
}

export default BlueprintSummary;
