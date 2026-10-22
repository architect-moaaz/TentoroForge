"use client";

// A when → then rule, in Drools' guided-rule shape and in plain words:
//   WHEN  a <record> is <created | changed>  AND  <conditions>
//   THEN  <actions>          OTHERWISE  <actions>
// The condition is a typed builder over the record's fields (an enum's values
// are a picker, numbers compare as numbers), or its FEEL text when the
// builder cannot show it. Testing it is the side panel's: the app's engine.

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Code2, ListTree } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ConditionBuilder } from "@/components/rules/ConditionBuilder";
import type { ConditionExpression } from "@/types/rules";
import type { ColumnModel } from "@/types/app-model";
import { conditionToFeel, type FieldTypeMap } from "@/lib/condition-to-feel";
import { feelToCondition } from "@/lib/feel-to-condition";
import { buildFieldMeta } from "@/lib/field-types";
import { ActionEditor } from "../ActionEditor";
import type { ConditionActionConfig, RuleScope } from "@/types/business-rules";
import type { FiresOn } from "@/lib/rules-studio";

/** Editing draft for a when → then rule. */
export interface ConditionActionDraft {
  id?: string;
  name: string;
  model_name: string | null;
  is_active: boolean;
  config: ConditionActionConfig;
  /** What the rule means, in a sentence (Blueprint rules carry one). */
  statement?: string;
  /** The condition is edited as text: the builder cannot show it as a tree. */
  expression?: boolean;
}

export function emptyDraft(model: string | null = null): ConditionActionDraft {
  return {
    name: "", model_name: model, is_active: true,
    config: { source: "manual", when: null, whenFeel: "true", then: [], otherwise: [], scope: "entity", salience: 0 },
  };
}

const SCOPES: { id: RuleScope; label: string; says: string }[] = [
  { id: "entity", label: "Everywhere", says: "Checked every time it is saved, and shown on the form while people type." },
  { id: "server", label: "Only when saving", says: "Checked every time it is saved. The form shows nothing until then." },
  { id: "form", label: "Only on the form", says: "Only changes how the form looks (show, hide, required, suggestions). A message that stops the save, or a value it fills in, still applies when saving." },
];

export function WhenThenEditor({
  draft, onChange, models, getFields, enumValuesForType, workflows, on, onOn, disabled,
}: {
  draft: ConditionActionDraft;
  onChange: (d: ConditionActionDraft) => void;
  models: string[];
  getFields: (model: string | null | undefined) => ColumnModel[];
  enumValuesForType: (type: string | undefined) => string[] | null;
  workflows: { id: string; name: string }[];
  on: FiresOn[];
  onOn: (on: FiresOn[]) => void;
  disabled?: boolean;
}) {
  const [advanced, setAdvanced] = useState(false);
  const columns = getFields(draft.model_name);
  const fieldNames = useMemo(() => columns.map((c) => c.name), [columns]);
  const fieldMeta = useMemo(() => buildFieldMeta(columns, enumValuesForType), [columns, enumValuesForType]);
  const fieldTypes: FieldTypeMap = useMemo(() => {
    const m: FieldTypeMap = {};
    for (const [name, fm] of Object.entries(fieldMeta)) m[name] = fm.category;
    return m;
  }, [fieldMeta]);
  const patch = (p: Partial<ConditionActionConfig>) => onChange({ ...draft, config: { ...draft.config, ...p } });

  // The types arrive with the catalogue: recompile once so the FEEL encodes values by type.
  useEffect(() => {
    if (draft.expression) return;
    const recompiled = conditionToFeel(draft.config.when, fieldTypes);
    if (recompiled !== draft.config.whenFeel) patch({ whenFeel: recompiled });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fieldTypes]);

  const parsedBack = useMemo(() => feelToCondition(draft.config.whenFeel), [draft.config.whenFeel]);
  const canUseBuilder = parsedBack !== undefined;
  const changeModel = (model: string) => {
    const meta = buildFieldMeta(getFields(model), enumValuesForType);
    const types: FieldTypeMap = {};
    for (const [n, fm] of Object.entries(meta)) types[n] = fm.category;
    onChange({ ...draft, model_name: model, config: { ...draft.config, whenFeel: conditionToFeel(draft.config.when, types) } });
  };
  const toggleOn = (e: FiresOn) => {
    const next = on.includes(e) ? on.filter((x) => x !== e) : [...on, e];
    if (next.length) onOn(next);   // at least one: a rule that fires on nothing is a switched-off rule
  };

  return (
    <div className="space-y-5" data-testid="when-then-editor">
      {/* WHEN */}
      <section className="rounded-xl border bg-sky-50/40 p-4 dark:bg-sky-950/20">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-widest text-sky-700 dark:text-sky-300">If</p>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>a</span>
          <select aria-label="Record" value={draft.model_name ?? ""} disabled={disabled}
                  onChange={(e) => changeModel(e.target.value)}
                  className="h-8 rounded-md border bg-background px-2 text-sm font-medium">
            {!draft.model_name && <option value="">choose what it is about…</option>}
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <span>is</span>
          {(["create", "update"] as FiresOn[]).map((e) => (
            <button key={e} type="button" disabled={disabled} onClick={() => toggleOn(e)} aria-pressed={on.includes(e)}
                    className={cn("rounded-full border px-3 py-1 text-xs font-medium",
                                  on.includes(e) ? "border-sky-600 bg-sky-600 text-white" : "bg-background hover:bg-muted")}>
              {e === "create" ? "added" : "changed"}
            </button>
          ))}
          <span className="text-xs text-muted-foreground">(pick one or both)</span>
        </div>
        <div className="mt-3 rounded-lg border bg-background p-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs text-muted-foreground">and</p>
            {draft.expression ? (
              <Button type="button" variant="ghost" size="sm" className="h-6 text-[11px]" disabled={!canUseBuilder || disabled}
                      title={canUseBuilder ? "Choose the fields and values from lists" : "This condition is too complex for the lists — keep typing it"}
                      onClick={() => canUseBuilder && onChange({ ...draft, expression: false, config: { ...draft.config, when: parsedBack ?? null } })}>
                <ListTree className="mr-1 h-3 w-3" /> Pick from lists
              </Button>
            ) : (
              <Button type="button" variant="ghost" size="sm" className="h-6 text-[11px]" disabled={disabled}
                      onClick={() => onChange({ ...draft, expression: true })}>
                <Code2 className="mr-1 h-3 w-3" /> Type it instead
              </Button>
            )}
          </div>
          {draft.expression ? (
            <div className="space-y-1">
              <Textarea className="min-h-[64px] font-mono text-xs" disabled={disabled} aria-label="Condition"
                        placeholder='amount > 5000 and managerNote = null   ·   previous.status = "closed" and status = "open"'
                        value={draft.config.whenFeel} onChange={(e) => patch({ whenFeel: e.target.value, when: null })} />
              <p className="text-[10px] text-muted-foreground">
                Use field names · <code>and</code> <code>or</code> <code>not(…)</code> · <code>=</code> means “is”, <code>!=</code> means “is not”,{" "}
                <code>&gt;</code> more than, <code>&lt;</code> less than · <code>previous.status</code> is the value before the change ·{" "}
                <code>user.role</code> is the person saving.
              </p>
            </div>
          ) : (
            <ConditionBuilder value={draft.config.when} fields={fieldNames} fieldMeta={fieldMeta}
                              onChange={(when: ConditionExpression | null) => patch({ when, whenFeel: conditionToFeel(when, fieldTypes) })} />
          )}
          {!draft.expression && !draft.config.when && (
            <p className="mt-1 text-[11px] text-muted-foreground">No condition yet, so the rule applies every time {on.length === 1 ? (on[0] === "create" ? "one is added" : "one is changed") : "one is saved"}. Add a condition above to narrow it down.</p>
          )}
        </div>
      </section>

      {/* THEN / OTHERWISE */}
      <section className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <div className="rounded-xl border bg-emerald-50/40 p-3 dark:bg-emerald-950/20">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-emerald-700 dark:text-emerald-300">Then</p>
          <p className="mb-2 text-[11px] text-muted-foreground">What happens when the “If” is true.</p>
          <ActionEditor bare branch="then" value={draft.config.then} onChange={(then) => patch({ then })}
                        fields={fieldNames} fieldMeta={fieldMeta} workflows={workflows} />
        </div>
        <div className="rounded-xl border bg-slate-50/60 p-3 dark:bg-slate-900/40">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-600 dark:text-slate-300">Otherwise <span className="font-normal normal-case tracking-normal">(optional)</span></p>
          <p className="mb-2 text-[11px] text-muted-foreground">What happens when it is not. Usually left empty.</p>
          <ActionEditor bare branch="else" value={draft.config.otherwise} onChange={(otherwise) => patch({ otherwise })}
                        fields={fieldNames} fieldMeta={fieldMeta} workflows={workflows} />
        </div>
      </section>

      {/* Meaning + advanced */}
      <section className="space-y-2">
        <label className="block space-y-1">
          <span className="text-xs font-medium">Describe the rule in one sentence <span className="font-normal text-muted-foreground">(optional — if you leave it empty, Forge writes it for you)</span></span>
          <Textarea className="min-h-[48px] text-sm" disabled={disabled} value={draft.statement ?? ""}
                    placeholder="An expense above 5000 needs a manager note."
                    onChange={(e) => onChange({ ...draft, statement: e.target.value })} />
        </label>
        <button type="button" onClick={() => setAdvanced(!advanced)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", advanced && "rotate-180")} /> More options
        </button>
        {advanced && (
          <div className="grid grid-cols-1 gap-3 rounded-lg border p-3 md:grid-cols-[2fr_1fr]">
            <div className="space-y-1.5">
              <p className="text-xs font-medium">Where it is checked</p>
              {SCOPES.map((s) => (
                <label key={s.id} className="flex items-start gap-2 text-xs">
                  <input type="radio" name="scope" aria-label={s.label} className="mt-0.5" checked={draft.config.scope === s.id} disabled={disabled}
                         onChange={() => patch({ scope: s.id })} />
                  <span><span className="font-medium">{s.label}</span> — <span className="text-muted-foreground">{s.says}</span></span>
                </label>
              ))}
            </div>
            <label className="space-y-1.5">
              <span className="text-xs font-medium">Order</span>
              <Input type="number" className="h-8" disabled={disabled} value={draft.config.salience}
                     onChange={(e) => { const n = e.target.value === "" || e.target.value === "-" ? 0 : Number(e.target.value); if (!Number.isNaN(n)) patch({ salience: n }); }} />
              <span className="block text-[11px] text-muted-foreground">A higher number is checked first. If two rules fill in the same field, the higher number wins. Most rules can stay at 0.</span>
            </label>
          </div>
        )}
      </section>
    </div>
  );
}
