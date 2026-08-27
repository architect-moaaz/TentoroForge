/**
 * InteractionEditor — visual authoring UI for a form field's `interaction`
 * block (computed / optionsFrom / onChange / dependsOn / visibleIf / …).
 *
 * Same backend validator as the Smith `set_field_interaction` tool
 * (POST /api/projects/{projectId}/field-interactions). No new schema
 * concept — this component just makes the interaction block the runtime
 * already understands editable by hand.
 *
 * Drop-in usage inside the visual editor's field-properties panel:
 *
 *   <InteractionEditor
 *     projectId={projectId}
 *     page="employees/new"
 *     field={selectedField}       // full field-node object
 *     siblings={allFieldsInForm}  // for autocomplete + validation preview
 *     onSaved={(res) => { … })    // re-fetch the schema after success
 *   />
 */

"use client";

import React, { useMemo, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { api } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────

interface ComputedInteraction {
  formula: string;
  readOnly?: boolean;
}
interface DynamicOptions {
  source: string;
  value: string;
  label: string;
  filter?: Record<string, string>;
}
interface OnChangeInteraction {
  fetch: { resource: string; by: string; from: string };
  set: Record<string, string>;
}
interface FieldInteraction {
  computed?: ComputedInteraction;
  optionsFrom?: DynamicOptions;
  onChange?: OnChangeInteraction;
  dependsOn?: string[];
  visibleIf?: string;
  requiredIf?: string;
  enabledIf?: string;
  readOnlyIf?: string;
}

interface FieldNode {
  name: string;
  kind?: string;
  control?: string;
  label?: string;
  interaction?: FieldInteraction;
}

interface Props {
  projectId: string;
  page: string;
  field: FieldNode;
  siblings: FieldNode[];
  onSaved?: (result: SaveResult) => void;
}

interface SaveResult {
  applied: boolean;
  diff_summary?: string;
  reason?: string;
  errors?: string[];
  warnings?: string[];
  edited_paths?: string[];
}

// Functions available in formulas (mirrored from
// packages/renderer/src/runtime/formInteraction.ts INTERACTION_FUNCTIONS +
// backend/services/interaction_spec.py KNOWN_FUNCTIONS).
const KNOWN_FUNCTIONS = [
  "daysBetween", "hoursBetween", "sum", "min", "max",
  "round", "abs", "ceil", "floor", "ifElse",
  "concat", "upper", "lower", "title", "slug", "initials",
  "contains", "startsWith", "endsWith",
  "avg", "count", "pow", "sqrt", "percent", "clamp",
  "now", "age", "today", "yearsBetween", "formatDate",
  "formatCurrency", "formatNumber", "formatPhone",
  "matches", "coalesce",
];

type InteractionKind =
  | "computed"
  | "optionsFrom"
  | "onChange"
  | "visibleIf"
  | "requiredIf"
  | "enabledIf"
  | "readOnlyIf";

// ── Component ─────────────────────────────────────────────────────────────

export function InteractionEditor({ projectId, page, field, siblings, onSaved }: Props) {
  // Local draft state — the field's interaction block plus any in-flight edits.
  // We DON'T persist until the user hits Save; that keeps the UI reactive and
  // the server free of intermediate half-authored states.
  const [draft, setDraft] = useState<FieldInteraction>(() => field.interaction ?? {});
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<SaveResult | null>(null);

  const isDirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(field.interaction ?? {}),
    [draft, field.interaction]
  );

  const siblingNames = useMemo(
    () => siblings.filter((s) => s.name !== field.name).map((s) => s.name),
    [siblings, field.name]
  );

  const activeKinds = useMemo(() => {
    const kinds: InteractionKind[] = [];
    if (draft.computed) kinds.push("computed");
    if (draft.optionsFrom) kinds.push("optionsFrom");
    if (draft.onChange) kinds.push("onChange");
    if (draft.visibleIf) kinds.push("visibleIf");
    if (draft.requiredIf) kinds.push("requiredIf");
    if (draft.enabledIf) kinds.push("enabledIf");
    if (draft.readOnlyIf) kinds.push("readOnlyIf");
    return kinds;
  }, [draft]);

  const availableKinds = useMemo(
    () =>
      (["computed", "optionsFrom", "onChange", "visibleIf", "requiredIf", "enabledIf", "readOnlyIf"] as InteractionKind[]).filter(
        (k) => !activeKinds.includes(k)
      ),
    [activeKinds]
  );

  const removeKind = useCallback(
    (k: InteractionKind) =>
      setDraft((d) => {
        const next = { ...d };
        delete next[k];
        return next;
      }),
    []
  );

  const save = useCallback(
    async (mode: "merge" | "replace" | "remove" = "replace") => {
      setSaving(true);
      setResult(null);
      try {
        const body =
          mode === "remove"
            ? { page, field: field.name, mode }
            : { page, field: field.name, mode, interaction: draft };
        // api.post<T> returns Promise<T> directly (not wrapped in {data}).
        const r = await api.post<SaveResult>(
          `/api/projects/${projectId}/field-interactions`,
          body,
        );
        setResult(r);
        if (r.applied) onSaved?.(r);
      } catch (err: unknown) {
        // network / auth failure
        setResult({
          applied: false,
          reason: err instanceof Error ? err.message : "request failed",
        });
      } finally {
        setSaving(false);
      }
    },
    [projectId, page, field.name, draft, onSaved]
  );

  return (
    <div className="space-y-4 border rounded-md p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold">Interactions</div>
          <div className="text-xs text-muted-foreground">
            Reactive behaviour for <code className="text-xs">{field.name}</code>. Same runtime as Smith
            authors via chat.
          </div>
        </div>
        {activeKinds.length > 0 && (
          <Badge variant="secondary">{activeKinds.length} active</Badge>
        )}
      </div>

      {/* Active interaction cards */}
      <div className="space-y-3">
        {draft.computed && (
          <ComputedCard
            value={draft.computed}
            siblingNames={siblingNames}
            onChange={(v) => setDraft((d) => ({ ...d, computed: v }))}
            onRemove={() => removeKind("computed")}
          />
        )}
        {draft.optionsFrom && (
          <OptionsFromCard
            value={draft.optionsFrom}
            siblingNames={siblingNames}
            onChange={(v) => setDraft((d) => ({ ...d, optionsFrom: v }))}
            onRemove={() => removeKind("optionsFrom")}
          />
        )}
        {draft.onChange && (
          <OnChangeCard
            value={draft.onChange}
            siblingNames={siblingNames}
            onChange={(v) => setDraft((d) => ({ ...d, onChange: v }))}
            onRemove={() => removeKind("onChange")}
          />
        )}
        {(["visibleIf", "requiredIf", "enabledIf", "readOnlyIf"] as const).map(
          (kind) =>
            draft[kind] && (
              <PredicateCard
                key={kind}
                kind={kind}
                value={draft[kind]!}
                siblingNames={siblingNames}
                onChange={(v) => setDraft((d) => ({ ...d, [kind]: v }))}
                onRemove={() => removeKind(kind)}
              />
            )
        )}
      </div>

      {/* Add-new dropdown */}
      {availableKinds.length > 0 && (
        <div>
          <Label className="text-xs">Add interaction</Label>
          <div className="flex flex-wrap gap-2 mt-1">
            {availableKinds.map((k) => (
              <Button
                key={k}
                size="sm"
                variant="outline"
                onClick={() => setDraft((d) => ({ ...d, [k]: defaultForKind(k) }))}
              >
                + {labelForKind(k)}
              </Button>
            ))}
          </div>
        </div>
      )}

      <Separator />

      {/* Save + status */}
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-muted-foreground">
          {isDirty ? "Unsaved changes." : "No changes."}
        </div>
        <div className="flex gap-2">
          {field.interaction && activeKinds.length === 0 && (
            <Button size="sm" variant="destructive" onClick={() => save("remove")} disabled={saving}>
              Remove all
            </Button>
          )}
          <Button size="sm" onClick={() => save("replace")} disabled={!isDirty || saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>

      {result && <ResultBanner result={result} />}
    </div>
  );
}

// ── Cards (one per interaction kind) ──────────────────────────────────────

function ComputedCard({
  value, siblingNames, onChange, onRemove,
}: {
  value: ComputedInteraction;
  siblingNames: string[];
  onChange: (v: ComputedInteraction) => void;
  onRemove: () => void;
}) {
  return (
    <Card title="⚡ Computed value" onRemove={onRemove}>
      <FormulaField
        value={value.formula}
        siblingNames={siblingNames}
        onChange={(formula) => onChange({ ...value, formula })}
        placeholder="basicSalary * 0.4"
        help={`Sibling fields: ${siblingNames.join(", ") || "(none)"}. Functions: ${KNOWN_FUNCTIONS.slice(0, 8).join(", ")}…`}
      />
      <div className="flex items-center gap-2 text-xs">
        <input
          id="ro"
          type="checkbox"
          checked={value.readOnly !== false}
          onChange={(e) => onChange({ ...value, readOnly: e.target.checked })}
        />
        <label htmlFor="ro">Read-only (recommended for computed fields)</label>
      </div>
    </Card>
  );
}

function OptionsFromCard({
  value, siblingNames, onChange, onRemove,
}: {
  value: DynamicOptions;
  siblingNames: string[];
  onChange: (v: DynamicOptions) => void;
  onRemove: () => void;
}) {
  const filterEntries = Object.entries(value.filter ?? {});
  return (
    <Card title="🔗 Dependent options" onRemove={onRemove}>
      <div className="grid grid-cols-3 gap-2">
        <SmallField label="Resource" value={value.source} onChange={(v) => onChange({ ...value, source: v })} placeholder="states" />
        <SmallField label="Value col" value={value.value} onChange={(v) => onChange({ ...value, value: v })} placeholder="id" />
        <SmallField label="Label col" value={value.label} onChange={(v) => onChange({ ...value, label: v })} placeholder="name" />
      </div>
      <Label className="text-xs mt-2">Filter (template like {"{{country}}"})</Label>
      <div className="space-y-1">
        {filterEntries.map(([k, v], i) => (
          <div key={i} className="flex gap-1">
            <Input value={k} onChange={(e) => {
              const nk = e.target.value;
              const next = { ...(value.filter ?? {}) };
              delete next[k]; if (nk) next[nk] = v;
              onChange({ ...value, filter: next });
            }} placeholder="countryId" className="text-xs" />
            <Input value={v} onChange={(e) => {
              onChange({ ...value, filter: { ...(value.filter ?? {}), [k]: e.target.value } });
            }} placeholder={`{{${siblingNames[0] ?? "country"}}}`} className="text-xs" />
            <Button size="sm" variant="ghost" onClick={() => {
              const next = { ...(value.filter ?? {}) }; delete next[k];
              onChange({ ...value, filter: Object.keys(next).length ? next : undefined });
            }}>×</Button>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={() => {
          const key = `col${filterEntries.length + 1}`;
          onChange({ ...value, filter: { ...(value.filter ?? {}), [key]: "" } });
        }}>+ Filter</Button>
      </div>
    </Card>
  );
}

function OnChangeCard({
  value, siblingNames, onChange, onRemove,
}: {
  value: OnChangeInteraction;
  siblingNames: string[];
  onChange: (v: OnChangeInteraction) => void;
  onRemove: () => void;
}) {
  const setEntries = Object.entries(value.set ?? {});
  return (
    <Card title="⇢ Autofill on change" onRemove={onRemove}>
      <div className="grid grid-cols-3 gap-2">
        <SmallField label="Resource" value={value.fetch.resource} onChange={(v) => onChange({ ...value, fetch: { ...value.fetch, resource: v } })} placeholder="customers" />
        <SmallField label="Match by" value={value.fetch.by} onChange={(v) => onChange({ ...value, fetch: { ...value.fetch, by: v } })} placeholder="id" />
        <SmallField label="From field" value={value.fetch.from} onChange={(v) => onChange({ ...value, fetch: { ...value.fetch, from: v } })} placeholder={siblingNames[0] ?? "customerId"} />
      </div>
      <Label className="text-xs mt-2">Set fields (from `{"{{result.X}}"}` templates)</Label>
      <div className="space-y-1">
        {setEntries.map(([k, v], i) => (
          <div key={i} className="flex gap-1">
            <Input value={k} onChange={(e) => {
              const nk = e.target.value; const next = { ...(value.set ?? {}) };
              delete next[k]; if (nk) next[nk] = v;
              onChange({ ...value, set: next });
            }} placeholder="address" className="text-xs" />
            <Input value={v} onChange={(e) => {
              onChange({ ...value, set: { ...(value.set ?? {}), [k]: e.target.value } });
            }} placeholder="{{result.address}}" className="text-xs" />
            <Button size="sm" variant="ghost" onClick={() => {
              const next = { ...(value.set ?? {}) }; delete next[k];
              onChange({ ...value, set: next });
            }}>×</Button>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={() => {
          const key = `field${setEntries.length + 1}`;
          onChange({ ...value, set: { ...(value.set ?? {}), [key]: "" } });
        }}>+ Field</Button>
      </div>
    </Card>
  );
}

function PredicateCard({
  kind, value, siblingNames, onChange, onRemove,
}: {
  kind: "visibleIf" | "requiredIf" | "enabledIf" | "readOnlyIf";
  value: string;
  siblingNames: string[];
  onChange: (v: string) => void;
  onRemove: () => void;
}) {
  const titleMap = {
    visibleIf: "👁 Show only when",
    requiredIf: "❗ Required when",
    enabledIf: "✓ Enabled when",
    readOnlyIf: "🔒 Read-only when",
  };
  return (
    <Card title={titleMap[kind]} onRemove={onRemove}>
      <FormulaField
        value={value}
        siblingNames={siblingNames}
        onChange={onChange}
        placeholder="country == 'US'"
        help={`Predicate over: ${siblingNames.join(", ") || "(no siblings)"}`}
      />
    </Card>
  );
}

// ── Building blocks ───────────────────────────────────────────────────────

function Card({
  title, onRemove, children,
}: {
  title: string;
  onRemove: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="border rounded p-3 space-y-2 bg-muted/30">
      <div className="flex justify-between items-center">
        <div className="text-xs font-medium">{title}</div>
        <Button size="sm" variant="ghost" onClick={onRemove} title="Remove">
          ×
        </Button>
      </div>
      {children}
    </div>
  );
}

function SmallField({
  label, value, onChange, placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <Label className="text-xs">{label}</Label>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="text-xs h-8"
      />
    </div>
  );
}

function FormulaField({
  value, onChange, placeholder, help,
}: {
  value: string;
  siblingNames: string[];
  onChange: (v: string) => void;
  placeholder?: string;
  help?: string;
}) {
  return (
    <div>
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={2}
        className="font-mono text-xs"
      />
      {help && <div className="text-[10px] text-muted-foreground mt-1">{help}</div>}
    </div>
  );
}

function ResultBanner({ result }: { result: SaveResult }) {
  if (result.applied) {
    return (
      <div className="text-xs text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950/30 border border-green-200 rounded p-2">
        ✓ Saved. {result.diff_summary?.split("\n")[0]}
      </div>
    );
  }
  return (
    <div className="text-xs text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 rounded p-2 space-y-1">
      <div className="font-medium">Could not save: {result.reason}</div>
      {result.errors?.map((e, i) => <div key={i}>• {e}</div>)}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────

function defaultForKind(k: InteractionKind): unknown {
  switch (k) {
    case "computed":    return { formula: "", readOnly: true };
    case "optionsFrom": return { source: "", value: "id", label: "name" };
    case "onChange":    return { fetch: { resource: "", by: "id", from: "" }, set: {} };
    default:            return "";
  }
}

function labelForKind(k: InteractionKind): string {
  return {
    computed: "Computed value",
    optionsFrom: "Dependent options",
    onChange: "Autofill on change",
    visibleIf: "Show only when",
    requiredIf: "Required when",
    enabledIf: "Enabled when",
    readOnlyIf: "Read-only when",
  }[k];
}
