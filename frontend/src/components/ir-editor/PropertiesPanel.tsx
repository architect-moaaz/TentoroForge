"use client";

import { useCallback, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Database, Workflow } from "lucide-react";
import { useIREditorStore, type IRNode, type NodePath } from "@/stores/ir-editor";
import { DataBindingPanel } from "./DataBindingPanel";
import { WorkflowBindingPanel } from "./WorkflowBindingPanel";

// ---------------------------------------------------------------------------
// Node spec (lightweight — mirrors registry for the frontend)
// ---------------------------------------------------------------------------

interface PropDef {
  name: string;
  type: "string" | "number" | "boolean" | "enum" | "spacing" | "color" | "icon" | "binding";
  values?: string[];
  label?: string;
}

const SPACING_TOKENS = ["xs", "sm", "md", "lg", "xl", "2xl"];
const COLOR_TOKENS = ["default", "primary", "secondary", "muted", "danger", "warning", "success"];
const ALIGN_VALUES = ["start", "center", "end", "stretch"];
const JUSTIFY_VALUES = ["start", "center", "end", "between", "around"];
const TYPOGRAPHY_TOKENS = ["heading-1", "heading-2", "heading-3", "body", "body-sm", "caption", "overline"];

/** Minimal prop specs per node type (most commonly edited props) */
const NODE_PROPS: Record<string, PropDef[]> = {
  Stack: [
    { name: "gap", type: "spacing" },
    { name: "padding", type: "spacing" },
    { name: "align", type: "enum", values: ALIGN_VALUES },
    { name: "justify", type: "enum", values: JUSTIFY_VALUES },
    { name: "width", type: "string" },
    { name: "height", type: "string" },
    { name: "scroll", type: "boolean" },
  ],
  Row: [
    { name: "gap", type: "spacing" },
    { name: "padding", type: "spacing" },
    { name: "align", type: "enum", values: ALIGN_VALUES },
    { name: "justify", type: "enum", values: JUSTIFY_VALUES },
    { name: "width", type: "string" },
    { name: "height", type: "string" },
    { name: "wrap", type: "boolean" },
  ],
  Grid: [
    { name: "columns", type: "number", label: "Columns" },
    { name: "gap", type: "spacing" },
    { name: "padding", type: "spacing" },
  ],
  Text: [
    { name: "content", type: "string", label: "Content" },
    { name: "typography", type: "enum", values: TYPOGRAPHY_TOKENS },
    { name: "weight", type: "enum", values: ["normal", "medium", "semibold", "bold"] },
    { name: "color", type: "color" },
    { name: "align", type: "enum", values: ["left", "center", "right"] },
    { name: "truncate", type: "number" },
  ],
  Button: [
    { name: "label", type: "string", label: "Label" },
    { name: "variant", type: "enum", values: ["primary", "secondary", "ghost", "outline", "danger", "link"] },
    { name: "size", type: "enum", values: ["sm", "md", "lg"] },
    { name: "icon", type: "icon" },
    { name: "width", type: "string" },
    { name: "submit", type: "boolean" },
  ],
  Badge: [
    { name: "content", type: "string", label: "Content" },
    { name: "variant", type: "enum", values: ["default", "primary", "success", "warning", "danger", "outline"] },
    { name: "size", type: "enum", values: ["sm", "md"] },
  ],
  TextInput: [
    { name: "bind", type: "binding", label: "Bind to" },
    { name: "label", type: "string" },
    { name: "placeholder", type: "string" },
    { name: "type", type: "enum", values: ["text", "email", "url", "tel", "number", "password"] },
    { name: "icon", type: "icon" },
    { name: "required", type: "boolean" },
    { name: "debounce", type: "number" },
  ],
  TextArea: [
    { name: "bind", type: "binding", label: "Bind to" },
    { name: "label", type: "string" },
    { name: "placeholder", type: "string" },
    { name: "rows", type: "number" },
    { name: "required", type: "boolean" },
  ],
  Select: [
    { name: "bind", type: "binding", label: "Bind to" },
    { name: "label", type: "string" },
    { name: "placeholder", type: "string" },
    { name: "searchable", type: "boolean" },
    { name: "clearable", type: "boolean" },
  ],
  DataTable: [
    { name: "data", type: "binding", label: "Data source" },
    { name: "pagination", type: "boolean" },
    { name: "sorting", type: "boolean" },
    { name: "filtering", type: "boolean" },
    { name: "selection", type: "enum", values: ["none", "single", "multiple"] },
    { name: "density", type: "enum", values: ["compact", "default", "comfortable"] },
  ],
  Card: [
    { name: "padding", type: "spacing" },
    { name: "hoverable", type: "boolean" },
    { name: "border", type: "boolean" },
  ],
  Image: [
    { name: "src", type: "string", label: "Source" },
    { name: "alt", type: "string" },
    { name: "width", type: "string" },
    { name: "height", type: "string" },
    { name: "fit", type: "enum", values: ["cover", "contain", "fill"] },
  ],
  Avatar: [
    { name: "src", type: "string" },
    { name: "name", type: "string" },
    { name: "size", type: "enum", values: ["xs", "sm", "md", "lg", "xl"] },
  ],
  StatCard: [
    { name: "label", type: "string" },
    { name: "value", type: "binding" },
    { name: "format", type: "enum", values: ["number", "currency", "percent", "compact"] },
    { name: "icon", type: "icon" },
  ],
  EmptyState: [
    { name: "icon", type: "icon" },
    { name: "title", type: "string" },
    { name: "message", type: "string" },
  ],
  Repeater: [
    { name: "data", type: "binding", label: "Data source" },
    { name: "itemKey", type: "string", label: "Key field" },
    { name: "direction", type: "enum", values: ["vertical", "horizontal", "grid"] },
    { name: "gap", type: "spacing" },
  ],
  Spacer: [
    { name: "size", type: "spacing" },
  ],
  Divider: [
    { name: "direction", type: "enum", values: ["horizontal", "vertical"] },
    { name: "label", type: "string" },
  ],
  Icon: [
    { name: "name", type: "icon" },
    { name: "size", type: "enum", values: ["xs", "sm", "md", "lg", "xl"] },
    { name: "color", type: "color" },
  ],
  Toggle: [
    { name: "bind", type: "binding" },
    { name: "label", type: "string" },
    { name: "description", type: "string" },
  ],
  Checkbox: [
    { name: "bind", type: "binding" },
    { name: "label", type: "string" },
    { name: "description", type: "string" },
  ],
};

// ---------------------------------------------------------------------------
// Property field renderers
// ---------------------------------------------------------------------------

interface FieldProps {
  name: string;
  def: PropDef;
  value: unknown;
  onChange: (value: unknown) => void;
}

function PropertyField({ name, def, value, onChange }: FieldProps) {
  const label = def.label || name.replace(/([A-Z])/g, " $1").replace(/^./, (s) => s.toUpperCase());

  switch (def.type) {
    case "string":
    case "binding":
    case "icon":
      return (
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">{label}</Label>
          <Input
            value={(value as string) || ""}
            onChange={(e) => onChange(e.target.value)}
            className="h-7 text-xs"
            placeholder={def.type === "binding" ? "state:..." : ""}
          />
        </div>
      );

    case "number":
      return (
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">{label}</Label>
          <Input
            type="number"
            value={(value as number) ?? ""}
            onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}
            className="h-7 text-xs"
          />
        </div>
      );

    case "boolean":
      return (
        <div className="flex items-center justify-between py-0.5">
          <Label className="text-xs text-muted-foreground">{label}</Label>
          <Switch
            checked={!!value}
            onCheckedChange={(checked) => onChange(checked)}
            className="scale-75"
          />
        </div>
      );

    case "enum":
    case "spacing":
    case "color": {
      const options =
        def.type === "spacing"
          ? SPACING_TOKENS
          : def.type === "color"
            ? COLOR_TOKENS
            : def.values || [];
      return (
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">{label}</Label>
          <Select
            value={(value as string) || ""}
            onValueChange={(v) => onChange(v || undefined)}
          >
            <SelectTrigger className="h-7 text-xs">
              <SelectValue placeholder="—" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__clear__">—</SelectItem>
              {options.map((opt) => (
                <SelectItem key={opt} value={opt}>
                  {opt}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      );
    }

    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Main properties panel
// ---------------------------------------------------------------------------

type PanelTab = "props" | "data" | "workflows" | "raw";

export function PropertiesPanel() {
  const selectedPath = useIREditorStore((s) => s.selectedPath);
  const selectedNode = useIREditorStore((s) => s.getSelectedNode());
  const applyOps = useIREditorStore((s) => s.applyOps);
  const [tab, setTab] = useState<PanelTab>("props");

  const handleChange = useCallback(
    (propName: string, value: unknown) => {
      if (!selectedPath) return;
      const cleanValue = value === "__clear__" ? undefined : value;
      applyOps([{ type: "setProp", path: selectedPath, prop: propName, value: cleanValue }]);
    },
    [selectedPath, applyOps],
  );

  if (!selectedNode || !selectedPath) {
    return (
      <div className="p-4 text-xs text-muted-foreground text-center">
        Select a component to edit its properties
      </div>
    );
  }

  const nodeType = selectedNode.node;
  const propDefs = NODE_PROPS[nodeType] || [];
  const hasDataBinding = nodeType === "Form" || nodeType === "DataTable";
  const hasWorkflowBinding = nodeType === "Form";

  const TABS: { key: PanelTab; label: string; disabled?: boolean; disabledTitle?: string }[] = [
    { key: "props", label: "Props" },
    { key: "data", label: "Data", disabled: !hasDataBinding, disabledTitle: "Form and DataTable only" },
    { key: "workflows", label: "Flows", disabled: !hasWorkflowBinding, disabledTitle: "Form only" },
    { key: "raw", label: "JSON" },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Node type header */}
      <div className="px-3 pt-2 pb-1.5 border-b shrink-0 space-y-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs font-semibold text-primary">{nodeType}</span>
          <span className="text-[10px] text-muted-foreground">
            [{selectedPath.join(" → ")}]
          </span>
        </div>
        {/* Binding badges */}
        <div className="flex items-center gap-1 flex-wrap">
          {(selectedNode.entityBinding as { entity?: string } | undefined)?.entity && (
            <span
              className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-medium bg-blue-100 text-blue-700 cursor-pointer"
              onClick={() => setTab("data")}
              title="Click to edit data binding"
            >
              <Database className="h-2.5 w-2.5" />
              {(selectedNode.entityBinding as { entity: string }).entity}
            </span>
          )}
          {(selectedNode.onSuccessWorkflow as { workflowId?: string } | undefined)?.workflowId && (
            <span
              className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-medium bg-purple-100 text-purple-700 cursor-pointer"
              onClick={() => setTab("workflows")}
              title="Click to edit workflow binding"
            >
              <Workflow className="h-2.5 w-2.5" />
              {(selectedNode.onSuccessWorkflow as { workflowId: string }).workflowId}
            </span>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b shrink-0">
        {TABS.map(({ key, label, disabled, disabledTitle }) => (
          <button
            key={key}
            onClick={() => !disabled && setTab(key)}
            className={`flex-1 py-1.5 text-xs font-medium border-b-2 transition-colors ${
              tab === key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            } ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
            disabled={disabled}
            title={disabled ? disabledTitle : undefined}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {tab === "props" && (
          <div className="p-3 space-y-3">
            {propDefs.length > 0 ? (
              propDefs.map((def) => (
                <PropertyField
                  key={def.name}
                  name={def.name}
                  def={def}
                  value={selectedNode[def.name]}
                  onChange={(v) => handleChange(def.name, v)}
                />
              ))
            ) : (
              <p className="text-xs text-muted-foreground">
                No editable properties for {nodeType}
              </p>
            )}
          </div>
        )}

        {tab === "data" && hasDataBinding && (
          <DataBindingPanel node={selectedNode} selectedPath={selectedPath} />
        )}

        {tab === "workflows" && hasWorkflowBinding && (
          <WorkflowBindingPanel node={selectedNode} selectedPath={selectedPath} />
        )}

        {tab === "raw" && (
          <div className="p-3">
            <pre className="p-2 bg-muted rounded text-[10px] overflow-auto max-h-full">
              {JSON.stringify(selectedNode, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
