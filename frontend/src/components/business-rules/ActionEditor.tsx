"use client";

import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ACTION_META,
  ACTION_TYPES,
  type RuleAction,
  type RuleActionType,
  type ValueMode,
} from "@/types/business-rules";
import type { FieldMeta } from "@/lib/field-types";

interface ActionEditorProps {
  /** "then" (condition true / ✓) or "else" (condition false / ✗). */
  branch: "then" | "else";
  /** Inside a section that already says Then / Otherwise: no frame, no heading. */
  bare?: boolean;
  value: RuleAction[];
  onChange: (next: RuleAction[]) => void;
  /** Field names of the rule's model, for field-target dropdowns. */
  fields: string[];
  /** Optional field -> type metadata (type chips + enum value dropdowns). */
  fieldMeta?: Record<string, FieldMeta>;
  /** The app's workflows, for "start a workflow" — chosen, not typed. */
  workflows?: { id: string; name: string }[];
}

function genActionId() {
  return `act_${crypto.randomUUID()}`;
}

function newAction(): RuleAction {
  return { id: genActionId(), type: "set_field", valueMode: "literal", value: "" };
}

export function ActionEditor({ branch, value, onChange, fields, fieldMeta, workflows, bare }: ActionEditorProps) {
  const accent =
    branch === "then"
      ? "border-emerald-200 dark:border-emerald-900/50"
      : "border-rose-200 dark:border-rose-900/50";

  const update = (i: number, patch: Partial<RuleAction>) => {
    const next = [...value];
    next[i] = { ...next[i], ...patch };
    onChange(next);
  };
  const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i));
  const add = () => onChange([...value, newAction()]);

  return (
    <div className={bare ? "space-y-2" : `space-y-2 rounded-md border ${accent} bg-muted/10 p-3`}>
      {!bare && (
        <div className="flex items-center justify-between">
          <Label className="text-xs font-semibold">
            {branch === "then" ? "Then (condition is true)" : "Else (condition is false)"}
          </Label>
          <Button type="button" variant="outline" size="sm" className="h-7 text-xs" onClick={add}>
            <Plus className="mr-1 h-3 w-3" />
            Action
          </Button>
        </div>
      )}

      {value.length === 0 && (
        <p className="py-2 text-center text-xs text-muted-foreground">
          {bare ? (branch === "then" ? "Nothing yet — add what the rule does." : "Nothing — the rule does nothing otherwise.") : "No actions yet."}
        </p>
      )}

      {value.map((action, i) => {
        // An action this editor does not know (written by a newer build) is
        // shown and kept, never dropped or crashed on.
        const meta = ACTION_META[action.type] ?? {
          label: action.type, description: "Kept as written.", formOnly: false,
          needsField: !!action.field, needsValue: false, needsMessage: !!action.message,
        };
        const targetMeta = action.field ? fieldMeta?.[action.field] : undefined;
        const enumOpts =
          targetMeta?.category === "enum" ? targetMeta.enumValues ?? [] : undefined;
        return (
          <div key={action.id} className="space-y-2 rounded-md border bg-background p-2.5">
            <div className="flex items-start gap-2">
              <Select
                value={action.type}
                onValueChange={(v) => update(i, { type: v as RuleActionType })}
              >
                <SelectTrigger className="h-7 flex-1 text-xs" aria-label="What it does">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ACTION_TYPES.map((t) => (
                    <SelectItem key={t} value={t} className="text-xs">
                      {ACTION_META[t].label}
                      {ACTION_META[t].formOnly ? " (form)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0 text-muted-foreground hover:text-rose-500"
                onClick={() => remove(i)}
                aria-label="Remove action"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>

            <p className="text-[11px] text-muted-foreground">{meta.description}</p>

            {meta.needsField && (
              <FieldSelect
                value={action.field ?? ""}
                onChange={(field) => update(i, { field })}
                fields={fields}
                fieldMeta={fieldMeta}
              />
            )}

            {meta.needsValue && (
              <div className="flex gap-2">
                <Select
                  value={action.valueMode ?? "literal"}
                  onValueChange={(v) => update(i, { valueMode: v as ValueMode })}
                >
                  <SelectTrigger className="h-7 w-[110px] text-xs" aria-label="Where the value comes from">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="literal" className="text-xs">Value</SelectItem>
                    <SelectItem value="field" className="text-xs">Field</SelectItem>
                    <SelectItem value="formula" className="text-xs">Formula</SelectItem>
                  </SelectContent>
                </Select>
                {action.valueMode === "field" ? (
                  <div className="flex-1">
                    <FieldSelect
                      value={action.value ?? ""}
                      onChange={(value) => update(i, { value })}
                      fields={fields}
                      fieldMeta={fieldMeta}
                    />
                  </div>
                ) : action.valueMode !== "formula" && enumOpts && enumOpts.length > 0 ? (
                  <Select
                    value={action.value || undefined}
                    onValueChange={(v) => update(i, { value: v })}
                  >
                    <SelectTrigger className="h-7 flex-1 text-xs" aria-label="Value">
                      <SelectValue placeholder="value" />
                    </SelectTrigger>
                    <SelectContent>
                      {enumOpts.map((v) => (
                        <SelectItem key={v} value={v} className="text-xs">
                          {v}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    className="h-7 flex-1 text-xs"
                    placeholder={action.valueMode === "formula" ? "FEEL expression" : "value"}
                    value={action.value ?? ""}
                    onChange={(e) => update(i, { value: e.target.value })}
                  />
                )}
              </div>
            )}

            {meta.needsMessage && (
              <Textarea
                className="min-h-[40px] text-xs"
                placeholder="Message shown to the user"
                value={action.message ?? ""}
                onChange={(e) => update(i, { message: e.target.value })}
              />
            )}

            {action.type === "set_visibility" && (
              <ToggleRow label="Visible" checked={action.visible ?? true} onChange={(visible) => update(i, { visible })} />
            )}
            {action.type === "set_required" && (
              <ToggleRow label="Required" checked={action.required ?? true} onChange={(required) => update(i, { required })} />
            )}
            {action.type === "set_readonly" && (
              <ToggleRow label="Read-only (locked)" checked={action.readonly ?? true} onChange={(readonly) => update(i, { readonly })} />
            )}
            {action.type === "trigger_workflow" &&
              (workflows && workflows.length > 0 ? (
                <Select
                  value={action.workflow || undefined}
                  onValueChange={(workflow) => update(i, { workflow })}
                >
                  <SelectTrigger className="h-7 text-xs" aria-label="Workflow to start">
                    <SelectValue placeholder="Choose the workflow to start" />
                  </SelectTrigger>
                  <SelectContent>
                    {workflows.map((w) => (
                      <SelectItem key={w.id} value={w.id} className="text-xs">
                        {w.name} <span className="text-muted-foreground">· {w.id}</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  className="h-7 text-xs"
                  placeholder="Workflow name"
                  value={action.workflow ?? ""}
                  onChange={(e) => update(i, { workflow: e.target.value })}
                />
              ))}
            {action.type === "set_options" && (
              <Input
                className="h-7 text-xs"
                placeholder="Options, comma-separated (e.g. todo, doing)"
                value={(action.options ?? []).map((o) => (o.label && o.label !== o.value ? `${o.value}=${o.label}` : o.value)).join(", ")}
                onChange={(e) =>
                  update(i, {
                    options: e.target.value
                      .split(",")
                      .map((x) => x.trim())
                      .filter(Boolean)
                      .map((x) => {
                        const [v, l] = x.split("=");
                        return { value: v.trim(), label: (l ?? v).trim() };
                      }),
                  })
                }
              />
            )}
          </div>
        );
      })}
      {bare && (
        <Button type="button" variant="outline" size="sm" className="h-7 w-full border-dashed text-xs" onClick={add}>
          <Plus className="mr-1 h-3 w-3" /> Add an action
        </Button>
      )}
    </div>
  );
}

function FieldSelect({
  value,
  onChange,
  fields,
  fieldMeta,
}: {
  value: string;
  onChange: (v: string) => void;
  fields: string[];
  fieldMeta?: Record<string, FieldMeta>;
}) {
  if (fields.length === 0) {
    return (
      <Input
        className="h-7 text-xs"
        placeholder="field name"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <Select value={value || undefined} onValueChange={onChange}>
      <SelectTrigger className="h-7 text-xs" aria-label="Field">
        <SelectValue placeholder="Select field" />
      </SelectTrigger>
      <SelectContent>
        {fields.map((f) => {
          const fm = fieldMeta?.[f];
          return (
            <SelectItem key={f} value={f} className="text-xs">
              <span className="flex w-full items-center justify-between gap-2">
                <span className="truncate">{f}</span>
                {fm && (
                  <span className="shrink-0 rounded bg-muted px-1 text-[9px] text-muted-foreground">
                    {fm.category}
                  </span>
                )}
              </span>
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <Switch checked={checked} onCheckedChange={onChange} aria-label={label} />
      <Label className="text-xs">{label}</Label>
    </div>
  );
}
