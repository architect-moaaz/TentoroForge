"use client";

/**
 * The two reviews before a build — the requirements, then the product model.
 *
 * Each is a conversation that loops until the person says yes: they tell
 * Smith what to change, Smith changes it, and the panel shows what moved
 * since the last round. The first is WHAT THE APP MUST DO, grouped by what
 * the product does. The second is WHAT IT IS MADE OF, module by module — the
 * screens, records, processes and connections that will be generated — with
 * a choice to build every module or only the ones ticked.
 *
 * Everything drawn here is read from `GET /gates` (services/smith/gates.py);
 * the only state of its own is which modules are ticked and which rows are
 * open.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowRight,
  Check,
  ChevronDown,
  Database,
  FileText,
  Hammer,
  KeyRound,
  Layers,
  Lock,
  Maximize2,
  Minimize2,
  Pencil,
  Plug,
  Users,
  Workflow,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { AppTile, blueprintName } from "./BlueprintSummary";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

// ---------------------------------------------------------------------------
// The payload
// ---------------------------------------------------------------------------

export type GateName = "requirements" | "product_model";

export interface RequirementItem {
  id: string;
  description: string;
  area: string;
  criteria: string[];
  assumption: string;
}

export interface RequirementsDiff {
  added: string[];
  removed: RequirementItem[];
  changed: { id: string; was: string }[];
}

export interface PartRow {
  id: string;
  name: string;
  route?: string;
  purpose?: string;
  description?: string;
  fields?: string[];
  trigger?: string;
}

export interface ModuleView {
  id: string;
  name: string;
  description: string;
  deferred: boolean;
  pages: PartRow[];
  entities: PartRow[];
  workflows: PartRow[];
  requirements: string[];
}

export interface ModelView {
  modules: ModuleView[];
  foundation: {
    roles: { id: string; name: string; description: string }[];
    auth: PartRow[];
    pages: PartRow[];
    entities: PartRow[];
    workflows: PartRow[];
  };
  integrations: { id: string; name: string; kind: string; provider: string; connected: boolean }[];
  uncovered: string[];
  counts: Record<string, number>;
}

export interface ModelDiff {
  added: string[];
  removed: { id: string; name: string }[];
  changed: { id: string; added: string[]; removed: { key: string; name: string }[]; was?: string }[];
  integrations: { added: string[]; removed: string[] };
}

type Approval = "approved" | "stale" | "open";

export interface GatesPayload {
  gate: GateName | null;
  built: boolean;
  requirements: { version: number; items: RequirementItem[]; diff: RequirementsDiff | null; approval: Approval };
  product_model: { version: number; items: ModelView; diff: ModelDiff | null; approval: Approval };
}

/**
 * The reviews, read whenever `key` changes — the Blueprint after a turn or a
 * run, which is exactly when what they show can have moved.
 */
export function useGates(projectId: string | null, key: unknown) {
  const [data, setData] = useState<GatesPayload | null>(null);
  const reload = useCallback(async () => {
    if (!projectId) return;
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/gates`, {
        credentials: "include",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        setData(null);
        return;
      }
      setData((await res.json()) as GatesPayload);
    } catch {
      /* the panel falls back to the Blueprint summary; a reload recovers it */
    }
  }, [projectId]);
  useEffect(() => {
    void reload();
  }, [reload, key]);
  return { data, reload };
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

/** One colour per kind of part, the same in every module and in the legend. */
const KIND = {
  page: { dot: "bg-sky-600", icon: FileText, label: "Screen" },
  entity: { dot: "bg-violet-600", icon: Database, label: "Record" },
  workflow: { dot: "bg-emerald-700", icon: Workflow, label: "Process" },
  integration: { dot: "bg-orange-600", icon: Plug, label: "Connection" },
  role: { dot: "bg-slate-500", icon: Users, label: "Role" },
} as const;
type Kind = keyof typeof KIND;

const n = (k: number, one: string, many = `${one}s`) => `${k} ${k === 1 ? one : many}`;

function Pill({ tone, children }: { tone: "amber" | "emerald" | "rose" | "sky" | "muted" | "primary"; children: ReactNode }) {
  const tones = {
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300",
    emerald: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300",
    rose: "bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300",
    sky: "bg-sky-100 text-sky-800 dark:bg-sky-950/60 dark:text-sky-300",
    muted: "bg-muted text-muted-foreground",
    primary: "bg-primary/10 text-primary",
  };
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium", tones[tone])}>
      {children}
    </span>
  );
}

function Version({ n: v, current }: { n: number; current?: boolean }) {
  return (
    <span
      className={cn(
        "rounded-md border px-1.5 py-px font-mono text-[11px] tabular-nums",
        current ? "border-primary text-primary" : "text-muted-foreground",
      )}
    >
      v{v}
    </span>
  );
}

function Header({
  doc,
  title,
  version,
  approval,
  extra,
}: {
  doc: Record<string, unknown> | null | undefined;
  title: string;
  version: number;
  approval: Approval;
  extra?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 border-b px-4 py-3">
      <AppTile doc={doc} className="h-10 w-10 text-base" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs text-muted-foreground">{blueprintName(doc)}</p>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold">{title}</h3>
          {version > 0 && <Version n={version} current />}
          {approval === "approved" ? (
            <Pill tone="emerald">
              <Check className="h-3 w-3" /> Approved
            </Pill>
          ) : (
            <Pill tone="amber">Waiting for you</Pill>
          )}
        </div>
      </div>
      {extra}
    </div>
  );
}

function Footer({ hint, children }: { hint: ReactNode; children: ReactNode }) {
  return (
    <footer className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 px-4 py-3">
      <p className="text-xs text-muted-foreground">{hint}</p>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </footer>
  );
}

function Button({
  onClick,
  primary,
  disabled,
  children,
}: {
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50",
        primary
          ? "bg-primary text-primary-foreground hover:bg-primary/90"
          : "border bg-card hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Review 1 — the requirements
// ---------------------------------------------------------------------------

export interface RequirementsReviewProps {
  doc: Record<string, unknown> | null | undefined;
  data: GatesPayload["requirements"];
  busy?: boolean;
  onApprove: () => void;
  onEdit: () => void;
  className?: string;
}

/** Requirements by area, in the order the areas first appear. */
function byArea(items: RequirementItem[]): [string, RequirementItem[]][] {
  const groups = new Map<string, RequirementItem[]>();
  for (const r of items) {
    const key = r.area || "General";
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  return [...groups.entries()];
}

function RequirementRow({
  r,
  mark,
  was,
}: {
  r: RequirementItem;
  mark?: "added" | "removed" | "changed";
  was?: string;
}) {
  const [open, setOpen] = useState(false);
  const tint =
    mark === "added"
      ? "bg-emerald-50 dark:bg-emerald-950/30"
      : mark === "removed"
        ? "bg-rose-50 dark:bg-rose-950/30"
        : mark === "changed"
          ? "bg-sky-50 dark:bg-sky-950/30"
          : "";
  return (
    <li className={cn("grid grid-cols-[3.25rem_minmax(0,1fr)_auto] items-start gap-2 px-3 py-2", tint)}>
      <span className="pt-px font-mono text-[11px] text-muted-foreground">{r.id}</span>
      <span className="min-w-0 text-xs leading-snug">
        <span className={cn(mark === "removed" && "text-muted-foreground line-through")}>{r.description}</span>
        {was && <span className="mt-0.5 block text-[11px] text-muted-foreground line-through">{was}</span>}
        {r.criteria.length > 0 && mark !== "removed" && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
            aria-expanded={open}
          >
            {n(r.criteria.length, "acceptance criterion", "acceptance criteria")}
            <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
          </button>
        )}
        {open && (
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] text-muted-foreground">
            {r.criteria.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        )}
      </span>
      <span className="flex flex-col items-end gap-1">
        {mark === "added" && <Pill tone="emerald">added</Pill>}
        {mark === "removed" && <Pill tone="rose">removed</Pill>}
        {mark === "changed" && <Pill tone="sky">changed</Pill>}
        {r.assumption && mark !== "removed" && <Pill tone="amber" >assumed</Pill>}
      </span>
    </li>
  );
}

export function RequirementsReview({ doc, data, busy, onApprove, onEdit, className }: RequirementsReviewProps) {
  const diff = data.diff;
  const [onlyChanges, setOnlyChanges] = useState(false);
  const added = new Set(diff?.added ?? []);
  const changed = new Map((diff?.changed ?? []).map((c) => [c.id, c.was]));
  const touched = (r: RequirementItem) => added.has(r.id) || changed.has(r.id);
  const shown = onlyChanges && diff ? data.items.filter(touched) : data.items;
  const groups = byArea([...shown, ...(diff?.removed ?? []).map((r) => ({ ...r, removed: true }))]);
  const assumed = data.items.filter((r) => r.assumption).length;
  const areas = new Set(data.items.map((r) => r.area).filter(Boolean)).size;

  return (
    <div className={cn("flex min-h-0 flex-col bg-card", className)}>
      <Header doc={doc} title="Requirements" version={data.version} approval={data.approval} />
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        <p className="px-1 text-xs text-muted-foreground">
          What the app must do, before anything is designed. Tell Smith what to change, or approve
          them and Smith works out the modules, screens and records.
        </p>
        {diff && (diff.added.length > 0 || diff.removed.length > 0 || diff.changed.length > 0) && (
          <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-dashed px-2.5 py-2 text-xs">
            <span className="text-muted-foreground">Since v{data.version - 1}:</span>
            {diff.added.length > 0 && <Pill tone="emerald">+{diff.added.length} added</Pill>}
            {diff.removed.length > 0 && <Pill tone="rose">−{diff.removed.length} removed</Pill>}
            {diff.changed.length > 0 && <Pill tone="sky">{diff.changed.length} changed</Pill>}
            <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-muted-foreground">
              <input
                id="gate-only-changes"
                type="checkbox"
                checked={onlyChanges}
                onChange={(e) => setOnlyChanges(e.target.checked)}
                className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
              />
              Only changes
            </label>
          </div>
        )}
        {groups.map(([area, rows]) => (
          <section key={area} className="overflow-hidden rounded-lg border bg-background">
            <header className="flex items-center gap-2 border-b px-3 py-1.5">
              <span className="text-xs font-semibold">{area}</span>
              <span className="ml-auto font-mono text-[11px] text-muted-foreground tabular-nums">
                {rows.filter((r) => !(r as { removed?: boolean }).removed).length}
              </span>
            </header>
            <ul className="divide-y">
              {rows.map((r) => {
                const removed = (r as { removed?: boolean }).removed;
                return (
                  <RequirementRow
                    key={`${r.id}${removed ? "-gone" : ""}`}
                    r={r}
                    mark={removed ? "removed" : added.has(r.id) ? "added" : changed.has(r.id) ? "changed" : undefined}
                    was={removed ? undefined : changed.get(r.id)}
                  />
                );
              })}
            </ul>
          </section>
        ))}
      </div>
      <Footer
        hint={
          <>
            {n(data.items.length, "requirement")}
            {areas > 0 && ` in ${n(areas, "area")}`}
            {assumed > 0 && ` · ${assumed} assumed`}
          </>
        }
      >
        <Button onClick={onEdit}>
          <Pencil className="h-3.5 w-3.5" /> Ask for changes
        </Button>
        <Button onClick={onApprove} primary disabled={busy}>
          Approve requirements <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </Footer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Review 2 — the product model
// ---------------------------------------------------------------------------

function Part({
  kind,
  name,
  detail,
  route,
  added,
}: {
  kind: Kind;
  name: string;
  detail?: string;
  route?: string;
  added?: boolean;
}) {
  return (
    <li
      className={cn(
        "grid grid-cols-[0.625rem_minmax(0,1fr)] items-baseline gap-2 rounded-md py-0.5 text-xs",
        added && "-mx-1 bg-emerald-50 px-1 dark:bg-emerald-950/30",
      )}
    >
      <span className={cn("h-2 w-2 translate-y-[-1px] rounded-sm", KIND[kind].dot)} aria-label={KIND[kind].label} />
      <span className="min-w-0">
        <span className="font-medium">{name}</span>
        {route && <span className="ml-1.5 font-mono text-[10.5px] text-muted-foreground">{route}</span>}
        {detail && <span className="block text-[11px] leading-snug text-muted-foreground">{detail}</span>}
      </span>
    </li>
  );
}

function Checkbox({ on, locked, onClick, label }: { on: boolean; locked?: boolean; onClick?: () => void; label: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={on}
      aria-label={label}
      disabled={locked}
      onClick={onClick}
      className={cn(
        "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border-[1.5px]",
        on ? "border-primary bg-primary text-primary-foreground" : "border-muted-foreground/60",
        locked && "border-dashed opacity-80",
      )}
    >
      {on && (locked ? <Lock className="h-2.5 w-2.5" /> : <Check className="h-3 w-3" />)}
    </button>
  );
}

function ModuleCard({
  m,
  selected,
  selectable,
  onToggle,
  added,
  changed,
}: {
  m: ModuleView;
  selected: boolean;
  selectable: boolean;
  onToggle: () => void;
  added: boolean;
  changed?: ModelDiff["changed"][number];
}) {
  const newParts = new Set(changed?.added ?? []);
  const parts = m.pages.length + m.entities.length + m.workflows.length;
  return (
    <article
      className={cn(
        "flex flex-col gap-2 rounded-xl border bg-background p-3",
        selected ? "border-primary ring-1 ring-inset ring-primary" : "opacity-70",
      )}
    >
      <div className="flex items-start gap-2.5">
        {selectable ? (
          <Checkbox on={selected} onClick={onToggle} label={`Build ${m.name}`} />
        ) : (
          <Layers className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h4 className="text-sm font-semibold">{m.name}</h4>
            {added && <Pill tone="emerald">new</Pill>}
            {!added && changed && <Pill tone="sky">changed</Pill>}
          </div>
          {m.description && <p className="text-[11px] leading-snug text-muted-foreground">{m.description}</p>}
          {changed?.was && <p className="text-[11px] text-muted-foreground line-through">{changed.was}</p>}
        </div>
      </div>
      {parts > 0 ? (
        <ul className="space-y-0.5">
          {m.pages.map((p) => (
            <Part key={p.id} kind="page" name={p.name} route={p.route} detail={p.purpose} added={newParts.has(`pages:${p.id}`)} />
          ))}
          {m.entities.map((e) => (
            <Part
              key={e.id}
              kind="entity"
              name={e.name}
              detail={[e.description, e.fields?.length ? e.fields.slice(0, 6).join(", ") + (e.fields.length > 6 ? ", …" : "") : ""]
                .filter(Boolean)
                .join(" · ")}
              added={newParts.has(`entities:${e.id}`)}
            />
          ))}
          {m.workflows.map((w) => (
            <Part key={w.id} kind="workflow" name={w.name} detail={w.purpose} added={newParts.has(`workflows:${w.id}`)} />
          ))}
        </ul>
      ) : (
        <p className="text-[11px] text-muted-foreground">Nothing in this module yet.</p>
      )}
      {(changed?.removed?.length ?? 0) > 0 && (
        <p className="text-[11px] text-rose-700 dark:text-rose-300">
          Removed: {changed!.removed.map((r) => r.name).join(", ")}
        </p>
      )}
      {m.requirements.length > 0 && (
        <div className="mt-auto flex flex-wrap gap-1 border-t border-dashed pt-2">
          {m.requirements.map((r) => (
            <span key={r} className="rounded border px-1 font-mono text-[10px] text-muted-foreground">
              {r}
            </span>
          ))}
        </div>
      )}
    </article>
  );
}

export interface ProductModelReviewProps {
  doc: Record<string, unknown> | null | undefined;
  gates: GatesPayload;
  busy?: boolean;
  wide?: boolean;
  onToggleWide?: () => void;
  /** `null` builds everything; a list builds those modules and the foundation. */
  onBuild: (modules: string[] | null) => void;
  onEdit: () => void;
  className?: string;
}

export function ProductModelReview({
  doc,
  gates,
  busy,
  wide,
  onToggleWide,
  onBuild,
  onEdit,
  className,
}: ProductModelReviewProps) {
  const data = gates.product_model;
  const view = data.items;
  const diff = data.diff;
  const ids = useMemo(() => view.modules.map((m) => m.id), [view.modules]);
  // Everything ticked to begin with: the whole app is the default answer.
  const [picked, setPicked] = useState<Set<string>>(() => new Set(ids));
  const [seen, setSeen] = useState<Set<string>>(() => new Set(ids));
  useEffect(() => {
    // A module that appears in a later round arrives ticked; one that was
    // retired leaves the choice.
    setPicked((cur) => new Set(ids.filter((id) => cur.has(id) || !seen.has(id))));
    setSeen(new Set(ids));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join("|")]);
  const [showReqs, setShowReqs] = useState(false);
  const allPicked = ids.every((id) => picked.has(id));
  const toggle = (id: string) =>
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const pickedPages = view.modules.filter((m) => picked.has(m.id)).reduce((k, m) => k + m.pages.length, 0);
  const foundationPages = view.foundation.auth.length + view.foundation.pages.length;
  const changedById = new Map((diff?.changed ?? []).map((c) => [c.id, c]));
  const addedModules = new Set(diff?.added ?? []);
  const c = view.counts;
  const reqs = gates.requirements;

  return (
    <div className={cn("flex min-h-0 flex-col bg-card", className)}>
      <Header
        doc={doc}
        title="Product model"
        version={data.version}
        approval={data.approval}
        extra={
          onToggleWide && (
            <button
              type="button"
              onClick={onToggleWide}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label={wide ? "Narrow the panel" : "Widen the panel"}
              title={wide ? "Narrow the panel" : "Widen the panel"}
            >
              {wide ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
          )
        }
      />
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {/* The requirements this model was worked out from, locked. */}
        <div className="rounded-lg border bg-background">
          <div className="flex items-center gap-1 pr-2">
            <button
              type="button"
              onClick={() => setShowReqs((s) => !s)}
              aria-expanded={showReqs}
              className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-xs"
            >
              <Pill tone={reqs.approval === "approved" ? "emerald" : "amber"}>
                {reqs.approval === "approved" ? "Approved" : "Changed"}
              </Pill>
              <span className="truncate">
                Requirements <span className="font-mono">v{reqs.version}</span> · {n(reqs.items.length, "item")}
              </span>
              <ChevronDown className={cn("ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", showReqs && "rotate-180")} />
            </button>
            {/* Still changeable here: tell Smith which one, and the model follows it. */}
            <button
              type="button"
              onClick={onEdit}
              className="shrink-0 rounded-md px-2 py-1 text-[11px] font-medium text-primary hover:bg-primary/10"
            >
              Change
            </button>
          </div>
          {showReqs && (
            <ul className="max-h-56 divide-y overflow-y-auto border-t">
              {reqs.items.map((r) => (
                <li key={r.id} className="grid grid-cols-[3.25rem_minmax(0,1fr)] gap-2 px-3 py-1.5 text-[11px]">
                  <span className="font-mono text-muted-foreground">{r.id}</span>
                  <span>{r.description}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {(
            [
              ["page", c.pages, "screen"],
              ["entity", c.entities, "record"],
              ["workflow", c.workflows, "process", "processes"],
              ["integration", c.integrations, "connection"],
              ["role", c.roles, "role"],
            ] as [Kind, number, string, string?][]
          )
            .filter(([, k]) => k > 0)
            .map(([kind, k, one, many]) => (
              <span key={kind} className="flex items-center gap-1.5 rounded-md border bg-background px-2 py-1 text-[11px]">
                <span className={cn("h-2 w-2 rounded-sm", KIND[kind].dot)} />
                <span className="font-mono tabular-nums">{k}</span> {k === 1 ? one : (many ?? `${one}s`)}
              </span>
            ))}
        </div>

        {diff && (diff.added.length > 0 || diff.removed.length > 0 || diff.changed.length > 0) && (
          <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-dashed px-2.5 py-2 text-xs">
            <span className="text-muted-foreground">Since v{data.version - 1}:</span>
            {diff.added.length > 0 && <Pill tone="emerald">+{n(diff.added.length, "module")}</Pill>}
            {diff.removed.length > 0 && <Pill tone="rose">−{diff.removed.map((m) => m.name).join(", ")}</Pill>}
            {diff.changed.length > 0 && <Pill tone="sky">{n(diff.changed.length, "module")} changed</Pill>}
          </div>
        )}

        {view.uncovered.length > 0 && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            Not covered by any screen yet: {view.uncovered.join(", ")}. Ask Smith to add what they need.
          </p>
        )}

        <div className={cn("grid gap-2.5", wide ? "grid-cols-[repeat(auto-fill,minmax(250px,1fr))]" : "grid-cols-1")}>
          {/* The foundation: always built, because every module sits on it. */}
          <article className="flex flex-col gap-2 rounded-xl border border-dashed bg-muted/30 p-3">
            <div className="flex items-start gap-2.5">
              <Checkbox on locked label="Foundation is always built" />
              <div>
                <h4 className="text-sm font-semibold">Foundation</h4>
                <p className="text-[11px] text-muted-foreground">Always built — every module sits on it.</p>
              </div>
            </div>
            <ul className="space-y-0.5">
              {view.foundation.auth.length > 0 && (
                <Part kind="page" name="Sign in" detail={view.foundation.auth.map((p) => p.route).join(", ")} />
              )}
              {view.foundation.roles.length > 0 && (
                <Part kind="role" name="Who signs in" detail={view.foundation.roles.map((r) => r.name).join(", ")} />
              )}
              {view.foundation.pages.map((p) => (
                <Part key={p.id} kind="page" name={p.name} route={p.route} detail={p.purpose} />
              ))}
              {view.foundation.entities.map((e) => (
                <Part key={e.id} kind="entity" name={e.name} detail={e.description} />
              ))}
              {view.foundation.workflows.map((w) => (
                <Part key={w.id} kind="workflow" name={w.name} detail={w.purpose} />
              ))}
            </ul>
          </article>

          {view.modules.map((m) => (
            <ModuleCard
              key={m.id}
              m={m}
              selectable
              selected={picked.has(m.id)}
              onToggle={() => toggle(m.id)}
              added={addedModules.has(m.id)}
              changed={changedById.get(m.id)}
            />
          ))}

          {view.integrations.length > 0 && (
            <article className="flex flex-col gap-2 rounded-xl border bg-background p-3">
              <div className="flex items-start gap-2.5">
                <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <div>
                  <h4 className="text-sm font-semibold">Connections</h4>
                  <p className="text-[11px] text-muted-foreground">Outside services the app talks to.</p>
                </div>
              </div>
              <ul className="space-y-0.5">
                {view.integrations.map((i) => (
                  <Part
                    key={i.id}
                    kind="integration"
                    name={i.name}
                    detail={[i.provider || i.kind, i.connected ? "ready to connect" : "declared — needs its key"]
                      .filter(Boolean)
                      .join(" · ")}
                  />
                ))}
              </ul>
            </article>
          )}
        </div>

        {!allPicked && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            Records and processes are built for every module, so the modules you leave out can be added
            later without rework. Only their screens wait.
          </p>
        )}

        <ul className="flex flex-wrap gap-x-3 gap-y-1 px-1 text-[11px] text-muted-foreground">
          {(Object.keys(KIND) as Kind[]).map((k) => (
            <li key={k} className="flex items-center gap-1.5">
              <span className={cn("h-2 w-2 rounded-sm", KIND[k].dot)} />
              {KIND[k].label}
            </li>
          ))}
        </ul>
      </div>
      <Footer
        hint={
          allPicked
            ? `All ${n(view.modules.length, "module")} · ${n(c.pages, "screen")}`
            : `${n(picked.size, "module")} of ${view.modules.length} · ${n(pickedPages + foundationPages, "screen")} of ${c.pages}`
        }
      >
        <Button onClick={onEdit}>
          <Pencil className="h-3.5 w-3.5" /> Ask for changes
        </Button>
        <Button onClick={() => onBuild([...picked])} disabled={busy || allPicked || picked.size === 0}>
          <Hammer className="h-3.5 w-3.5" /> Build selected ({picked.size})
        </Button>
        <Button onClick={() => onBuild(null)} primary disabled={busy}>
          Build app <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </Footer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// After a scoped build — the modules still waiting
// ---------------------------------------------------------------------------

export function WaitingModules({
  gates,
  busy,
  onBuild,
}: {
  gates: GatesPayload;
  busy?: boolean;
  onBuild: (modules: string[] | null) => void;
}) {
  const modules = gates.product_model.items.modules;
  const waiting = modules.filter((m) => m.deferred);
  if (!gates.built || waiting.length === 0) return null;
  const built = modules.filter((m) => !m.deferred).map((m) => m.id);
  return (
    <section className="border-b bg-card px-4 py-3">
      <div className="mb-2 flex items-center gap-2">
        <Layers className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">Not built yet</h3>
        <span className="text-xs text-muted-foreground">as you chose</span>
      </div>
      <ul className="space-y-1.5">
        {waiting.map((m) => (
          <li key={m.id} className="flex items-center gap-3 rounded-lg border bg-background px-3 py-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-medium">{m.name}</span>
              <span className="block text-[11px] text-muted-foreground">
                {n(m.pages.length, "screen")} waiting · its records and processes are already built
              </span>
            </span>
            <Button onClick={() => onBuild([...built, m.id])} disabled={busy}>
              <Hammer className="h-3.5 w-3.5" /> Build
            </Button>
          </li>
        ))}
      </ul>
      {waiting.length > 1 && (
        <div className="mt-2 flex justify-end">
          <Button onClick={() => onBuild(null)} disabled={busy}>
            Build the rest
          </Button>
        </div>
      )}
    </section>
  );
}

/** The transcript card's second line, by which review is open. */
export function gateCardLine(gates: GatesPayload | null): { label: string; line: string } | null {
  if (!gates?.gate) return null;
  if (gates.gate === "requirements") {
    const r = gates.requirements;
    return { label: `Requirements · v${r.version}`, line: `${n(r.items.length, "requirement")} to review` };
  }
  const m = gates.product_model;
  const c = m.items.counts;
  return {
    label: `Product model · v${m.version}`,
    line: [n(c.modules ?? 0, "module"), n(c.pages ?? 0, "screen"), n(c.entities ?? 0, "record")].join(" · "),
  };
}
