"use client";

/**
 * InputMappingSection — the "Inputs" area of the Properties panel v2.
 *
 * Renders one row per declared input in the node's ActionContract. Each
 * row has a source picker (from-step / typed-in / formula) and a value
 * control appropriate to the selected source + the input's type.
 */

import { useMemo, useState } from "react";
import {
  ChevronsUpDown,
  Check,
  Loader2,
  Minus,
  Plus,
  Trash2,
  Variable,
  Type,
  Wand2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { useOrgEntities } from "@/hooks/useOrgEntities";
import type { ActionContract, InputMapping, MappingSource, ParamContract, ParamType } from "./actionContracts";
import type { WorkflowVariable } from "./workflowVariables";
import { asObjectList } from "./config-guards";
import { readLegacyInputValue } from "./workflowVariables";
import { KeyValueMapper } from "./KeyValueMapper";
import type { WorkflowNodeConfig } from "@/types/workflow";
import type { AppModel } from "@/types/app-model";

interface InputMappingSectionProps {
  contract: ActionContract;
  config: WorkflowNodeConfig;
  variables: WorkflowVariable[];
  onChange: (mappings: InputMapping[]) => void;
  appModel?: AppModel | null;
  orgId?: string;
}

const SOURCE_LABEL: Record<MappingSource, string> = {
  variable: "From another step",
  literal: "Type it in",
  expression: "Formula",
};

const SOURCE_HELP: Record<MappingSource, string> = {
  variable: "Use a value produced by an earlier step or the trigger.",
  literal: "Type a value directly.",
  expression: "Compute the value with a small formula (advanced).",
};

const TYPE_TOOLTIP: Partial<Record<ParamType, string>> = {
  string: "Text",
  number: "A number",
  boolean: "Yes / no",
  email: "Email address",
  uuid: "Record ID",
  date: "Date/time",
  object: "A map of key → value",
  array: "A list of values",
  enum: "One of a preset list",
  table: "A database table",
  user: "A person or role",
};

export function InputMappingSection({
  contract,
  config,
  variables,
  onChange,
  appModel,
  orgId,
}: InputMappingSectionProps) {
  // A3-2/A4-3: `?? []` guarded nullish only — a wrong type or a null row threw.
  const mappings = asObjectList<InputMapping>(config.inputMappings);
  const [showOptional, setShowOptional] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [manualOptional, setManualOptional] = useState<Set<string>>(new Set());

  const rows = useMemo(() => {
    return contract.inputs.map((param) => {
      const existing = mappings.find((m) => m.name === param.name);
      if (existing) return { param, mapping: existing, isLegacySeed: false };
      const legacy = readLegacyInputValue(config, param.name);
      if (legacy !== undefined && legacy !== "") {
        return {
          param,
          mapping: legacyToMapping(param.name, legacy),
          isLegacySeed: true,
        };
      }
      return { param, mapping: null as InputMapping | null, isLegacySeed: false };
    });
  }, [contract, config, mappings]);

  const required = rows.filter((r) => r.param.required);
  const optional = rows.filter((r) => !r.param.required && !r.param.advanced);
  const advanced = rows.filter((r) => r.param.advanced);
  const visibleOptional = optional.filter(
    (r) => r.mapping || manualOptional.has(r.param.name) || showOptional,
  );
  const hiddenOptionalCount = optional.length - visibleOptional.length;
  const visibleAdvanced = advanced.filter(
    (r) => r.mapping || manualOptional.has(r.param.name) || showAdvanced,
  );
  const hiddenAdvancedCount = advanced.length - visibleAdvanced.length;

  const upsertMapping = (m: InputMapping) => {
    const next = mappings.filter((x) => x.name !== m.name);
    next.push(m);
    onChange(next);
  };

  const removeMapping = (name: string) => {
    onChange(mappings.filter((m) => m.name !== name));
    setManualOptional((prev) => {
      const s = new Set(prev);
      s.delete(name);
      return s;
    });
  };

  const renderRow = ({ param, mapping }: { param: ParamContract; mapping: InputMapping | null }) => (
    <InputRow
      key={param.name}
      param={param}
      mapping={mapping}
      variables={variables}
      appModel={appModel}
      orgId={orgId}
      onChange={upsertMapping}
      onClear={() => removeMapping(param.name)}
    />
  );

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-[10px] font-semibold uppercase text-muted-foreground">
          Inputs
        </Label>
        <span className="text-[10px] text-muted-foreground">
          {required.length} required
        </span>
      </div>

      <div className="space-y-2.5">
        {required.map(renderRow)}
        {visibleOptional.map(renderRow)}
      </div>

      {hiddenOptionalCount > 0 && (
        <div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-[10px] text-muted-foreground"
            onClick={() => setShowOptional(true)}
          >
            <Plus className="mr-1 h-3 w-3" />
            Add optional input ({hiddenOptionalCount})
          </Button>
        </div>
      )}

      {advanced.length > 0 && (
        <div className="pt-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-[10px] text-muted-foreground"
            onClick={() => setShowAdvanced((s) => !s)}
          >
            {showAdvanced ? (
              <Minus className="mr-1 h-3 w-3" />
            ) : (
              <Plus className="mr-1 h-3 w-3" />
            )}
            {showAdvanced
              ? "Hide advanced options"
              : `Advanced options${hiddenAdvancedCount ? ` (${hiddenAdvancedCount})` : ""}`}
          </Button>
          {showAdvanced && (
            <div className="mt-2 space-y-2.5 rounded border border-dashed border-muted p-2">
              {visibleAdvanced.map(renderRow)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function InputRow({
  param,
  mapping,
  variables,
  appModel,
  orgId,
  onChange,
  onClear,
}: {
  param: ParamContract;
  mapping: InputMapping | null;
  variables: WorkflowVariable[];
  appModel?: AppModel | null;
  orgId?: string;
  onChange: (m: InputMapping) => void;
  onClear: () => void;
}) {
  const source: MappingSource = mapping?.source ?? defaultSource(param);
  const value = mapping?.value;
  const isEmpty = value === undefined || value === "" || value === null;
  const missing = param.required && isEmpty;

  const setSource = (s: MappingSource) => {
    onChange({ name: param.name, source: s, value: s === source ? value : "" });
  };
  const setValue = (v: unknown) => {
    onChange({ name: param.name, source, value: v });
  };

  const typeTip = TYPE_TOOLTIP[param.type] ?? param.type;

  return (
    <div
      className={cn(
        "space-y-1 rounded border p-2",
        missing ? "border-red-300 bg-red-50/40" : "border-transparent",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          <Label
            className="text-[11px] font-medium"
            title={`${typeTip}${param.help ? ` — ${param.help}` : ""}`}
          >
            <span>{param.label ?? param.name}</span>
            {param.required && (
              <span className="ml-0.5 text-red-500" aria-label="required">
                *
              </span>
            )}
          </Label>
        </div>
        <Select value={source} onValueChange={(v) => setSource(v as MappingSource)}>
          <SelectTrigger
            className="h-6 w-[150px] text-[10px]"
            title={SOURCE_HELP[source]}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="variable" className="text-[11px]">
              <span className="flex items-center gap-1">
                <Variable className="h-3 w-3" /> {SOURCE_LABEL.variable}
              </span>
            </SelectItem>
            <SelectItem value="literal" className="text-[11px]">
              <span className="flex items-center gap-1">
                <Type className="h-3 w-3" /> {SOURCE_LABEL.literal}
              </span>
            </SelectItem>
            <SelectItem value="expression" className="text-[11px]">
              <span className="flex items-center gap-1">
                <Wand2 className="h-3 w-3" /> {SOURCE_LABEL.expression}
              </span>
            </SelectItem>
          </SelectContent>
        </Select>
        {mapping && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            title="Clear"
            onClick={onClear}
          >
            <Trash2 className="h-3 w-3 text-muted-foreground" />
          </Button>
        )}
      </div>

      <ValueControl
        param={param}
        source={source}
        value={value}
        variables={variables}
        appModel={appModel}
        orgId={orgId}
        onChange={setValue}
      />

      {missing && (
        <p className="text-[10px] text-red-600">This input is required.</p>
      )}
      {param.help && (
        <p className="text-[10px] text-muted-foreground">{param.help}</p>
      )}
    </div>
  );
}

function ValueControl({
  param,
  source,
  value,
  variables,
  appModel,
  orgId,
  onChange,
}: {
  param: ParamContract;
  source: MappingSource;
  value: unknown;
  variables: WorkflowVariable[];
  appModel?: AppModel | null;
  orgId?: string;
  onChange: (v: unknown) => void;
}) {
  if (source === "variable") {
    const str = typeof value === "string" ? value : "";
    const groups = new Map<string, WorkflowVariable[]>();
    for (const v of variables) {
      const g = groups.get(v.sourceLabel) ?? [];
      g.push(v);
      groups.set(v.sourceLabel, g);
    }
    if (variables.length === 0) {
      return (
        <div className="rounded border border-dashed border-muted-foreground/30 bg-muted/20 p-2 text-[10px] text-muted-foreground">
          No values are available yet. Add a step before this one — its
          outputs will show up here.
        </div>
      );
    }
    return (
      <Select value={str} onValueChange={onChange}>
        <SelectTrigger className="h-8 text-xs font-mono">
          <SelectValue placeholder="Pick a value from an earlier step…" />
        </SelectTrigger>
        <SelectContent>
          {Array.from(groups.entries()).map(([label, vars]) => (
            <SelectGroup key={label}>
              <SelectLabel className="text-[10px] uppercase text-muted-foreground">
                {label}
              </SelectLabel>
              {vars.map((v) => (
                <SelectItem key={v.path} value={v.path} className="text-[11px] font-mono">
                  {v.path}
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (source === "expression") {
    return (
      <Textarea
        className="h-16 text-xs font-mono"
        placeholder="e.g. concat(user.firstName, ' ', user.lastName)"
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  // Literal — control depends on the contract type.
  if (param.type === "boolean") {
    return (
      <div className="flex items-center gap-2 pt-1">
        <Switch
          checked={value === true || value === "true"}
          onCheckedChange={(v) => onChange(v === true)}
        />
        <span className="text-[11px] text-muted-foreground">
          {value === true ? "Yes" : "No"}
        </span>
      </div>
    );
  }

  if (param.type === "enum" && param.options) {
    return (
      <Select
        value={typeof value === "string" ? value : ""}
        onValueChange={onChange}
      >
        <SelectTrigger className="h-8 text-xs">
          <SelectValue placeholder="Select…" />
        </SelectTrigger>
        <SelectContent>
          {param.options.map((opt) => (
            <SelectItem key={opt} value={opt} className="text-xs">
              {opt}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (param.type === "table") {
    const tables = appModel?.database?.tables ?? [];
    const str = typeof value === "string" ? value : "";
    if (tables.length === 0) {
      return (
        <Input
          className="h-8 text-xs font-mono"
          placeholder="Table name (e.g. users)"
          value={str}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    }
    return (
      <Select value={str} onValueChange={onChange}>
        <SelectTrigger className="h-8 text-xs">
          <SelectValue placeholder="Pick a table…" />
        </SelectTrigger>
        <SelectContent>
          {tables.map((t) => (
            <SelectItem key={t.name} value={t.name} className="text-xs font-mono">
              {t.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (param.type === "user") {
    return (
      <UserPicker
        orgId={orgId}
        value={typeof value === "string" ? value : ""}
        onChange={onChange}
      />
    );
  }

  if (param.type === "object") {
    const obj =
      value && typeof value === "object" && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {};
    return (
      <KeyValueMapper
        value={obj}
        variables={variables}
        onChange={onChange}
        keyPlaceholder={
          param.name.includes(".")
            ? param.name.split(".").pop()!
            : "key"
        }
        addLabel="Add entry"
      />
    );
  }

  if (param.type === "array") {
    return (
      <ArrayEditor
        value={Array.isArray(value) ? value : []}
        variables={variables}
        onChange={onChange}
      />
    );
  }

  if (param.type === "number") {
    return (
      <Input
        type="number"
        className="h-8 text-xs"
        value={typeof value === "number" || typeof value === "string" ? String(value) : ""}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "" ? undefined : Number(v));
        }}
      />
    );
  }

  return (
    <Input
      className="h-8 text-xs"
      placeholder={param.type === "email" ? "user@example.com" : ""}
      value={typeof value === "string" ? value : ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function ArrayEditor({
  value,
  variables,
  onChange,
}: {
  value: unknown[];
  variables: WorkflowVariable[];
  onChange: (v: unknown) => void;
}) {
  const rows = value.length === 0 ? [""] : value.map((v) =>
    typeof v === "string" ? v : v === undefined || v === null ? "" : JSON.stringify(v),
  );
  const setRow = (i: number, next: string) => {
    const nextArr = [...rows];
    nextArr[i] = next;
    onChange(nextArr.filter((s, idx) => s !== "" || idx < nextArr.length - 1));
  };
  const addRow = () => onChange([...rows, ""]);
  const removeRow = (i: number) => onChange(rows.filter((_, idx) => idx !== i));

  return (
    <div className="space-y-1">
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-1">
          <ArrayItemInput
            value={row}
            variables={variables}
            onChange={(v) => setRow(i, v)}
          />
          {rows.length > 1 && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              onClick={() => removeRow(i)}
              title="Remove"
            >
              <Trash2 className="h-3 w-3 text-muted-foreground" />
            </Button>
          )}
        </div>
      ))}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-6 px-2 text-[10px] text-muted-foreground"
        onClick={addRow}
      >
        <Plus className="mr-1 h-3 w-3" /> Add item
      </Button>
    </div>
  );
}

function ArrayItemInput({
  value,
  variables,
  onChange,
}: {
  value: string;
  variables: WorkflowVariable[];
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex flex-1 items-center gap-1">
      <Input
        className="h-7 text-xs"
        value={value}
        placeholder="Value"
        onChange={(e) => onChange(e.target.value)}
      />
      {variables.length > 0 && (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              title="Insert value from a step"
            >
              <Variable className="h-3 w-3 text-muted-foreground" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-[240px] p-0" align="end">
            <Command>
              <CommandInput placeholder="Search values…" className="h-8 text-xs" />
              <CommandList>
                <CommandEmpty className="p-2 text-[11px] text-muted-foreground">
                  No matches.
                </CommandEmpty>
                <CommandGroup>
                  {variables.map((v) => (
                    <CommandItem
                      key={v.path}
                      value={v.path}
                      onSelect={() => {
                        onChange(`{{${v.path}}}`);
                        setOpen(false);
                      }}
                      className="text-[11px] font-mono"
                    >
                      {v.path}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}

function UserPicker({
  orgId,
  value,
  onChange,
}: {
  orgId?: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const { options, isLoading } = useOrgEntities(orgId, "person");
  const selected = options.find((o) => o.id === value);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="h-8 w-full justify-between text-xs font-normal"
        >
          <span className="truncate">
            {selected?.label || value || "Pick a person…"}
          </span>
          <ChevronsUpDown className="ml-1 h-3 w-3 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[240px] p-0" align="start">
        <Command>
          <CommandInput placeholder="Search people…" className="h-8 text-xs" />
          <CommandList>
            <CommandEmpty>
              {isLoading ? (
                <span className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" /> Loading…
                </span>
              ) : (
                "No matches."
              )}
            </CommandEmpty>
            <CommandGroup>
              {options.map((opt) => (
                <CommandItem
                  key={opt.id}
                  value={opt.label}
                  onSelect={() => {
                    onChange(opt.id);
                    setOpen(false);
                  }}
                  className="text-xs"
                >
                  <Check
                    className={cn(
                      "mr-2 h-3 w-3",
                      value === opt.id ? "opacity-100" : "opacity-0",
                    )}
                  />
                  {opt.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

export function defaultSource(param: ParamContract): MappingSource {
  if (param.type === "enum" || param.type === "boolean" || param.type === "table") {
    return "literal";
  }
  if (param.type === "user") return "literal";
  // A14-3: an EXPRESSION field is typed `string`, so it fell through to
  // "variable" — "From another step" — which looks the whole expression up as
  // a variable NAME and resolves to undefined. set_variable, transform and
  // custom all have a param called `expression`, so authoring any of them
  // through the editor's own default silently did nothing.
  if (param.name === "expression") return "expression";
  // A NEW variable NAME the user types (set_variable.variableName,
  // custom.assignTo) must default to "literal" — otherwise it renders as a
  // dropdown over EXISTING variables ("No values available yet…"), making the
  // obvious action (type a new name) impossible until the user flips the source.
  if (param.name === "variableName" || param.name === "assignTo") return "literal";
  return "variable";
}

/**
 * Convert a legacy top-level config field ("table: 'users'") into an
 * InputMapping row. Bare strings that begin with "{{" are variable refs;
 * everything else is treated as a literal.
 */
function legacyToMapping(name: string, raw: unknown): InputMapping {
  if (typeof raw === "string") {
    const trimmed = raw.trim();
    const match = trimmed.match(/^\{\{\s*(.+?)\s*\}\}$/);
    if (match) {
      return { name, source: "variable", value: match[1] };
    }
    return { name, source: "literal", value: raw };
  }
  return { name, source: "literal", value: raw };
}
