"use client";
import * as React from "react";
import { useParams } from "next/navigation";
import { useEditorStore } from "@/lib/editor-store";

/**
 * Data-aware binding editor. A grouped dropdown is the primary UX: it offers the
 * RIGHT expression for each of the page's data sources — metric keys for
 * op:"aggregate" sources, entity columns for lists/details, label/value (and the
 * whole array) for op:"series" charts — plus the common scopes (form / row /
 * state / user). A free-text field remains for advanced hand-written expressions.
 */
export interface BindingControlProps {
  label: string;
  value: any;
  onChange: (v: any) => void;
  placeholder?: string;
  /**
   * The page that owns the node being edited. Callers derive this by finding the
   * page that CONTAINS the selected node — which is the page a new data source
   * must be added to. Falls back to the store's currentPageId, but pass it: the
   * two can diverge (multi-page artifacts) and a mismatch silently breaks
   * addDataSource.
   */
  pageId?: string;
}

const labelCls = "flex flex-col gap-1 text-sm";
const labelText = "text-xs uppercase tracking-wide text-muted-foreground";
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

const norm = (s: string) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
const singular = (s: string) => {
  const n = norm(s);
  return n.endsWith("ies") ? n.slice(0, -3) + "y" : n.endsWith("s") ? n.slice(0, -1) : n;
};

// Prop names that hold a COLLECTION — for these, whole-array/list options are the
// most relevant, so we float them to the top of a source's option list.
const COLLECTION_PROP = /^(data|rows|items|options|series|entries|list|columns)$/i;
// Scope prefixes that need a field typed after them (handled via the text input).
const SCOPE_PREFIXES = new Set(["form.", "row.", "state."]);

type RegField = { name: string; type?: string; required?: boolean };
type RegEntity = { name: string; fields?: RegField[] };
type Src = { name?: string; entity?: string; op?: string; metrics?: Record<string, unknown> };
type Opt = { label: string; value: string };
type Group = { label: string; options: Opt[] };

export function BindingControl({ label, value, onChange, placeholder, pageId: pageIdProp }: BindingControlProps) {
  const artifacts = useEditorStore((s) => s.artifacts);
  const currentPageId = useEditorStore((s) => s.currentPageId);
  // Prefer the caller-supplied page (the one that owns the selected node); the
  // store's currentPageId is only a fallback and can point at a different page.
  const pageId = pageIdProp ?? currentPageId;
  const dispatch = useEditorStore((s) => s.dispatch);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // dataSources declared on the current page (what this page can actually bind to).
  const sources: Src[] = React.useMemo(() => {
    const ds = pageId ? (artifacts as any)?.pageSchemas?.[pageId]?.dataSources : undefined;
    return Array.isArray(ds) ? ds : [];
  }, [artifacts, pageId]);

  // Project id for the registry fetch. Prefer the route param (the editor lives
  // at /editor/[projectId]/…) and fall back to parsing the path — a background
  // fetch that silently fails must never be the thing that hides the UI.
  const routeParams = useParams() as Record<string, string | string[]> | null;
  const projectId = React.useMemo(() => {
    const fromRoute = routeParams?.projectId;
    if (typeof fromRoute === "string" && fromRoute) return fromRoute;
    if (typeof window !== "undefined") {
      const m =
        window.location.pathname.match(/\/editor\/([^/?#]+)/) ||
        window.location.pathname.match(/\/projects\/([^/?#]+)/);
      return m?.[1] ?? null;
    }
    return null;
  }, [routeParams]);

  // Registry entities (for column-level options + the create-source form).
  const [entities, setEntities] = React.useState<RegEntity[]>([]);
  const [entityLoad, setEntityLoad] = React.useState<"idle" | "loading" | "ready" | "error">("idle");
  const loadEntities = React.useCallback(() => {
    if (!projectId || typeof window === "undefined") return;
    setEntityLoad("loading");
    const token = window.localStorage?.getItem("token");
    fetch(`${API_BASE}/api/projects/${projectId}/registry/entities`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        setEntities(Array.isArray(d) ? d : (d?.entities ?? []));
        setEntityLoad("ready");
      })
      .catch((err) => {
        if (process.env.NODE_ENV !== "production") {
          console.warn("[BindingControl] registry entities load failed:", err);
        }
        setEntityLoad("error");
      });
  }, [projectId]);
  React.useEffect(() => {
    loadEntities();
  }, [loadEntities]);

  const wantsCollection = COLLECTION_PROP.test(label || "");

  const groups: Group[] = React.useMemo(() => {
    const fieldsFor = (entity?: string): RegField[] => {
      if (!entity) return [];
      const reg = entities.find(
        (e) => norm(e.name) === norm(entity) || singular(e.name) === singular(entity),
      );
      return reg?.fields ?? [];
    };

    const out: Group[] = [];
    for (const s of sources) {
      if (!s?.name) continue;
      const op = s.op;
      const opts: Opt[] = [];

      if (op === "aggregate" || op === "stats") {
        // Metric keys live on the source itself — bind straight to them.
        const keys =
          s.metrics && typeof s.metrics === "object" ? Object.keys(s.metrics as object) : [];
        for (const k of keys) opts.push({ label: `${s.name}.${k}`, value: `${s.name}.${k}` });
        if (!keys.length) opts.push({ label: s.name, value: s.name });
      } else if (op === "series") {
        // A series resolves to [{label,value}] — the whole array feeds a Chart's data.
        opts.push({ label: `${s.name} — whole series (chart data)`, value: s.name });
        opts.push({ label: `${s.name}[0].label`, value: `${s.name}[0].label` });
        opts.push({ label: `${s.name}[0].value`, value: `${s.name}[0].value` });
      } else if (op === "get" || op === "detail" || op === "find" || op === "one") {
        const fields = fieldsFor(s.entity);
        for (const f of fields) opts.push({ label: `${s.name}.${f.name}`, value: `${s.name}.${f.name}` });
        if (!fields.length) opts.push({ label: s.name, value: s.name });
      } else {
        // list / options / default — the whole array, or a column off the first row.
        const whole: Opt = { label: `${s.name} — whole list`, value: s.name };
        const fieldOpts = fieldsFor(s.entity).map((f) => ({
          label: `${s.name}[0].${f.name}`,
          value: `${s.name}[0].${f.name}`,
        }));
        // For a collection prop the whole list matters most; else lead with columns.
        opts.push(...(wantsCollection ? [whole, ...fieldOpts] : [...fieldOpts, whole]));
      }

      if (opts.length) {
        const meta = [s.entity, op].filter(Boolean).join(" · ");
        out.push({ label: meta ? `${s.name}  ·  ${meta}` : s.name, options: opts });
      }
    }

    out.push({
      label: "Scopes",
      options: [
        { label: "form.<field> — this form's input", value: "form." },
        { label: "row.<field> — current table row", value: "row." },
        { label: "state.<key> — page state", value: "state." },
        { label: "current user id", value: "global.user.id" },
      ],
    });
    return out;
  }, [sources, entities, wantsCollection]);

  const val = typeof value === "string" ? value : value ?? "";

  // The hand-written-expression box is edited locally and committed on blur /
  // Enter. Wiring it straight to `onChange` dispatched an updateProp/bindProp
  // PER KEYSTROKE, and editor-store pushes one undo entry per dispatch and
  // re-arms the 500 ms autosave each time — typing `form.email` cost nine undo
  // entries and nine save arms, and every intermediate prefix (`f`, `fo`, …)
  // was written into the schema as a real binding. Commit-on-blur matches
  // SizeField in StylePanel.tsx. The dropdown and "create data source" paths
  // are discrete choices and still commit immediately; the effect re-syncs the
  // draft whenever they (or an external edit) change the committed value.
  const [draft, setDraft] = React.useState<string>(String(val));
  React.useEffect(() => { setDraft(String(val)); }, [val]);
  const known = React.useMemo(() => {
    const set = new Set<string>();
    for (const g of groups) for (const o of g.options) set.add(o.value);
    return set;
  }, [groups]);
  const selectValue = val && known.has(val) ? val : val ? "__custom__" : "";

  const pick = (v: string) => {
    if (!v || v === "__custom__") return;
    onChange(v);
    // Scope prefixes need a field typed after them — focus the input to continue.
    if (SCOPE_PREFIXES.has(v)) requestAnimationFrame(() => inputRef.current?.focus());
  };

  const hasSources = groups.some((g) => g.label !== "Scopes");

  // ── Create-a-data-source affordance ─────────────────────────────────────
  // Collection props (a chart's `data`, a table's `rows`) need an aggregated
  // series to be useful, which the page may not have. Let the user build one
  // (entity + group-by field → op:"series") right here instead of dead-ending.
  const [showCreate, setShowCreate] = React.useState(false);
  const [ceEntity, setCeEntity] = React.useState("");
  const [ceField, setCeField] = React.useState("");
  const ceFields = React.useMemo(() => {
    const reg = entities.find((e) => norm(e.name) === norm(ceEntity));
    return reg?.fields ?? [];
  }, [entities, ceEntity]);

  const [createError, setCreateError] = React.useState<string | null>(null);
  const createSeries = () => {
    if (!pageId) { setCreateError("No target page for this node."); return; }
    if (!ceEntity || !ceField) return;
    const camel = ceEntity.charAt(0).toLowerCase() + ceEntity.slice(1);
    const base = `${camel}By${ceField.charAt(0).toUpperCase() + ceField.slice(1)}`;
    const taken = new Set(sources.map((s) => s.name));
    let name = base;
    for (let i = 2; taken.has(name); i++) name = `${base}${i}`;
    try {
      dispatch({
        type: "addDataSource",
        pageId,
        source: { name, entity: ceEntity, op: "series", groupBy: ceField, agg: { fn: "count" } },
      } as any);
      onChange(name);
    } catch (err) {
      // applyAction throws (e.g. unknown page / duplicate) rather than silently
      // failing — show it instead of leaving a dead button.
      if (process.env.NODE_ENV !== "production") {
        console.warn("[BindingControl] addDataSource failed:", err);
      }
      setCreateError(err instanceof Error ? err.message : "Could not create the data source.");
      return;
    }
    setCreateError(null);
    setShowCreate(false);
    setCeEntity("");
    setCeField("");
  };

  return (
    <label className={labelCls}>
      <span className={labelText}>{label}</span>

      <select
        className="border rounded px-2 py-1.5 text-sm bg-background"
        value={selectValue}
        onChange={(e) => pick(e.target.value)}
        title="Bind this prop to a data field"
      >
        <option value="">Bind to data…</option>
        {val && !known.has(val) && <option value="__custom__">Custom: {val}</option>}
        {groups.map((g, gi) => (
          <optgroup key={gi} label={g.label}>
            {g.options.map((o, oi) => (
              <option key={oi} value={o.value}>{o.label}</option>
            ))}
          </optgroup>
        ))}
      </select>

      {!hasSources && !wantsCollection && (
        <span className="text-[10px] text-muted-foreground">
          No page data sources — pick a scope above or type an expression below.
        </span>
      )}

      {/* Collection props always get the create affordance — its visibility must
          not hinge on an async fetch that can silently fail. Entity load state is
          surfaced inside the form (loading / retry / empty) instead of hiding it. */}
      {wantsCollection && (
        !showCreate ? (
          <button
            type="button"
            onClick={() => {
              setShowCreate(true);
              if (entityLoad === "idle" || entityLoad === "error") loadEntities();
            }}
            className="self-start text-[11px] font-medium text-primary hover:underline"
          >
            + Create a chart data source
          </button>
        ) : (
          <div className="space-y-1.5 rounded-md border bg-muted/30 p-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              New series source
            </div>

            {entityLoad === "loading" && (
              <p className="text-[10px] text-muted-foreground">Loading entities…</p>
            )}
            {entityLoad === "error" && (
              <div className="flex items-center gap-2 text-[10px] text-destructive">
                <span>Couldn&apos;t load entities.</span>
                <button type="button" onClick={loadEntities} className="underline">Retry</button>
              </div>
            )}
            {entityLoad === "ready" && entities.length === 0 && (
              <p className="text-[10px] text-muted-foreground">
                This project has no entities to chart yet.
              </p>
            )}

            {entities.length > 0 && (
              <>
                <select
                  value={ceEntity}
                  onChange={(e) => { setCeEntity(e.target.value); setCeField(""); }}
                  className="w-full rounded border bg-background px-2 py-1 text-xs"
                >
                  <option value="">Entity…</option>
                  {entities.map((e) => (
                    <option key={e.name} value={e.name}>{e.name}</option>
                  ))}
                </select>
                <select
                  value={ceField}
                  disabled={!ceEntity}
                  onChange={(e) => setCeField(e.target.value)}
                  className="w-full rounded border bg-background px-2 py-1 text-xs disabled:opacity-50"
                >
                  <option value="">Group by field…</option>
                  {ceFields.map((f) => (
                    <option key={f.name} value={f.name}>{f.name}</option>
                  ))}
                </select>
              </>
            )}

            {createError && (
              <p className="text-[10px] text-destructive">{createError}</p>
            )}
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={createSeries}
                disabled={!ceEntity || !ceField}
                className="flex-1 rounded bg-primary py-1 text-xs text-primary-foreground disabled:opacity-50"
              >
                Create + bind
              </button>
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="rounded border px-2 py-1 text-xs hover:bg-muted"
              >
                Cancel
              </button>
            </div>
            <p className="text-[10px] text-muted-foreground">
              Counts rows grouped by the field → {"{ label, value }"} the chart plots.
            </p>
          </div>
        )
      )}

      {/* Advanced: hand-written expression. */}
      <input
        ref={inputRef}
        type="text"
        className="border rounded px-2 py-1 text-xs bg-background font-mono text-muted-foreground"
        value={draft}
        placeholder={placeholder ?? "expression — e.g. form.name · drivers[0].label · row.status"}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { if (draft !== String(val)) onChange(draft); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          else if (e.key === "Escape") {
            setDraft(String(val));
            (e.target as HTMLInputElement).blur();
          }
        }}
      />
    </label>
  );
}
