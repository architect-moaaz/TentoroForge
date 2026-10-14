"use client";

import { useEffect, useMemo } from "react";
import { Code2, Info, ListTree } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ConditionBuilder } from "@/components/rules/ConditionBuilder";
import type { ConditionExpression } from "@/types/rules";
import type { ColumnModel } from "@/types/app-model";
import { conditionToFeel, type FieldTypeMap } from "@/lib/condition-to-feel";
import { feelToCondition } from "@/lib/feel-to-condition";
import { buildFieldMeta } from "@/lib/field-types";
import { ActionEditor } from "./ActionEditor";
import { RulePlayground } from "./RulePlayground";
import type { ConditionActionConfig, RuleScope } from "@/types/business-rules";

/** Editing draft for a condition→action business rule. */
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

export function emptyDraft(): ConditionActionDraft {
  return {
    name: "",
    model_name: null,
    is_active: true,
    config: {
      source: "manual",
      when: null,
      whenFeel: "true",
      then: [],
      otherwise: [],
      scope: "entity",
      salience: 0,
    },
  };
}

interface RuleEditorProps {
  draft: ConditionActionDraft;
  onChange: (next: ConditionActionDraft) => void;
  /** Entity/model names from the project's data model. */
  models: string[];
  /** Typed columns for a model (from the data model). */
  getFields: (model: string | null | undefined) => ColumnModel[];
  /** Enum values for a column type that names an enum (else null). */
  enumValuesForType: (type: string | undefined) => string[] | null;
  /** Whether the project has a data model at all. */
  hasModel: boolean;
  /** The app's workflows (Blueprint apps), for "start a workflow". */
  workflows?: { id: string; name: string }[];
  /** A Blueprint rule: shows the sentence it is read back as. */
  withStatement?: boolean;
}

export function RuleEditor({
  draft,
  onChange,
  models,
  getFields,
  enumValuesForType,
  hasModel,
  workflows,
  withStatement,
}: RuleEditorProps) {
  const columns = getFields(draft.model_name);
  const fieldNames = useMemo(() => columns.map((c) => c.name), [columns]);

  // Type metadata drives the condition builder (operators + value controls)
  // and the FEEL compiler (type-correct value encoding).
  const fieldMeta = useMemo(
    () => buildFieldMeta(columns, enumValuesForType),
    [columns, enumValuesForType],
  );
  const fieldTypes: FieldTypeMap = useMemo(() => {
    const m: FieldTypeMap = {};
    for (const [name, fm] of Object.entries(fieldMeta)) m[name] = fm.category;
    return m;
  }, [fieldMeta]);

  const patchConfig = (patch: Partial<ConditionActionConfig>) =>
    onChange({ ...draft, config: { ...draft.config, ...patch } });

  const onConditionChange = (when: ConditionExpression | null) =>
    patchConfig({ when, whenFeel: conditionToFeel(when, fieldTypes) });

  // The data model resolves asynchronously (/app-model). If the editor opened
  // before types arrived, recompile whenFeel from the condition tree once they
  // do, so the persisted FEEL always uses type-correct encoding.
  useEffect(() => {
    if (draft.expression) return; // the text is the condition; nothing to recompile
    const recompiled = conditionToFeel(draft.config.when, fieldTypes);
    if (recompiled !== draft.config.whenFeel) patchConfig({ whenFeel: recompiled });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fieldTypes]);

  // Text ↔ builder. Back to the builder only when the text reads as a tree
  // over this record's fields — otherwise it would show something else.
  const toExpression = () => onChange({ ...draft, expression: true });
  const parsedBack = useMemo(() => feelToCondition(draft.config.whenFeel), [draft.config.whenFeel]);
  const canUseBuilder = parsedBack !== undefined;
  const toBuilder = () => {
    if (!canUseBuilder) return;
    onChange({ ...draft, expression: false, config: { ...draft.config, when: parsedBack ?? null } });
  };

  const changeModel = (model: string) => {
    // Recompile against the new model's types so whenFeel stays correct.
    const nextCols = getFields(model);
    const nextMeta = buildFieldMeta(nextCols, enumValuesForType);
    const nextTypes: FieldTypeMap = {};
    for (const [name, fm] of Object.entries(nextMeta)) nextTypes[name] = fm.category;
    onChange({
      ...draft,
      model_name: model,
      config: { ...draft.config, whenFeel: conditionToFeel(draft.config.when, nextTypes) },
    });
  };

  return (
    <div className="space-y-4">
      {/* Identity */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="space-y-1">
          <Label className="text-xs">Rule name</Label>
          <Input
            className="h-8 text-sm"
            placeholder="e.g. block-negative-amount"
            value={draft.name}
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Applies to (record)</Label>
          {models.length > 0 ? (
            <Select value={draft.model_name ?? undefined} onValueChange={changeModel}>
              <SelectTrigger className="h-8 text-sm">
                <SelectValue placeholder="Select a model" />
              </SelectTrigger>
              <SelectContent>
                {models.map((m) => (
                  <SelectItem key={m} value={m} className="text-sm">
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input
              className="h-8 text-sm"
              placeholder="model name"
              value={draft.model_name ?? ""}
              onChange={(e) => onChange({ ...draft, model_name: e.target.value })}
            />
          )}
        </div>
      </div>

      {!hasModel && (
        <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            This project has no data model yet — type field names by hand. Generate the app or
            define entities in the Data Model tab to get typed field pickers (dropdowns, enum
            values, type-correct operators).
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <Label className="text-xs">Where it runs</Label>
          <Select
            value={draft.config.scope}
            onValueChange={(v) => patchConfig({ scope: v as RuleScope })}
          >
            <SelectTrigger className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="entity" className="text-sm">Everywhere (form + every save)</SelectItem>
              <SelectItem value="form" className="text-sm">How the form looks only</SelectItem>
              <SelectItem value="server" className="text-sm">On save only (not the form)</SelectItem>
            </SelectContent>
          </Select>
          {draft.config.scope === "form" &&
            [...draft.config.then, ...draft.config.otherwise].some(
              (a) => !["set_visibility", "set_readonly", "set_options", "recommendation"].includes(a.type),
            ) && (
              <p className="text-[10px] text-muted-foreground">
                Refusing a save or setting a value is always enforced on save too.
              </p>
            )}
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Priority (salience)</Label>
          <Input
            type="number"
            className="h-8 text-sm"
            value={draft.config.salience}
            onChange={(e) => {
              const raw = e.target.value;
              const n = raw === "" || raw === "-" ? 0 : Number(raw);
              if (!Number.isNaN(n)) patchConfig({ salience: n });
            }}
          />
        </div>
        <div className="flex items-end gap-2 pb-1">
          <Switch
            checked={draft.is_active}
            onCheckedChange={(is_active) => onChange({ ...draft, is_active })}
          />
          <Label className="text-xs">On</Label>
        </div>
      </div>

      {withStatement && (
        <div className="space-y-1">
          <Label className="text-xs">What the rule means (shown to people and to Smith)</Label>
          <Textarea
            className="min-h-[52px] text-sm"
            placeholder="e.g. Expenses above ₹5,000 need a manager's note. (Left empty, Forge writes one.)"
            value={draft.statement ?? ""}
            onChange={(e) => onChange({ ...draft, statement: e.target.value })}
          />
        </div>
      )}

      {/* IF — type-aware condition builder bound to the model's fields, or
          the condition as text when the builder cannot show it. */}
      <div className="rounded-md border bg-card p-3">
        <div className="mb-2 flex items-center justify-end">
          {draft.expression ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 text-[11px]"
              onClick={toBuilder}
              disabled={!canUseBuilder}
              title={canUseBuilder ? "Edit with the visual builder" : "This condition is beyond the visual builder"}
            >
              <ListTree className="mr-1 h-3 w-3" /> Visual builder
            </Button>
          ) : (
            <Button type="button" variant="ghost" size="sm" className="h-6 text-[11px]" onClick={toExpression}>
              <Code2 className="mr-1 h-3 w-3" /> Edit as expression
            </Button>
          )}
        </div>
        {draft.expression ? (
          <div className="space-y-1">
            <Label className="text-xs">When (expression)</Label>
            <Textarea
              className="min-h-[60px] font-mono text-xs"
              placeholder='e.g. amount > 5000 and status = "submitted"   ·   previous.status = "done" and status = "todo"'
              value={draft.config.whenFeel}
              onChange={(e) => patchConfig({ whenFeel: e.target.value, when: null })}
            />
            <p className="text-[10px] text-muted-foreground">
              Fields by name · <code>and</code> / <code>or</code> / <code>not(…)</code> · <code>=</code>{" "}
              <code>!=</code> <code>&gt;</code> <code>&lt;</code> · <code>previous.field</code> is the
              value before an edit · <code>user.role</code> is the person saving.
            </p>
          </div>
        ) : (
          <ConditionBuilder
            value={draft.config.when}
            onChange={onConditionChange}
            fields={fieldNames}
            fieldMeta={fieldMeta}
          />
        )}
      </div>

      {/* THEN / ELSE */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <ActionEditor
          branch="then"
          value={draft.config.then}
          onChange={(then) => patchConfig({ then })}
          fields={fieldNames}
          fieldMeta={fieldMeta}
          workflows={workflows}
        />
        <ActionEditor
          branch="else"
          value={draft.config.otherwise}
          onChange={(otherwise) => patchConfig({ otherwise })}
          fields={fieldNames}
          fieldMeta={fieldMeta}
          workflows={workflows}
        />
      </div>

      {/* Playground */}
      <RulePlayground
        whenFeel={draft.config.whenFeel}
        then={draft.config.then}
        otherwise={draft.config.otherwise}
        fields={fieldNames}
      />
    </div>
  );
}
