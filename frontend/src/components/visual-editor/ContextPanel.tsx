"use client";

import React, { useState, useCallback, useEffect } from "react";
import {
  X,
  Plus,
  Type,
  Sparkles,
  Trash2,
  ExternalLink,
  Database,
  Workflow,
  Loader2,
  Link2,
  Zap,
} from "lucide-react";
import { InteractionEditor } from "./InteractionEditor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { useVisualEditorStore } from "@/stores/visual-editor";
import { api } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

// ---------------------------------------------------------------------------
// Registry types
// ---------------------------------------------------------------------------

interface EntityField { name: string; type: string; required: boolean }
interface EntitySchema { name: string; fields: EntityField[]; apiRoutes: string[] }
interface WorkflowSchema { id: string; name: string; description: string; inputs: { name: string; type?: string }[] }

function useRegistryEntities(projectId: string) {
  const [entities, setEntities] = useState<EntitySchema[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/projects/${projectId}/registry/entities`)
      .then((r) => r.ok ? r.json() : [])
      .then((d) => setEntities(Array.isArray(d) ? d : []))
      .catch(() => setEntities([]))
      .finally(() => setLoading(false));
  }, [projectId]);
  return { entities, loading };
}

function useRegistryWorkflows(projectId: string) {
  const [workflows, setWorkflows] = useState<WorkflowSchema[]>([]);
  useEffect(() => {
    fetch(`${API_BASE}/api/projects/${projectId}/registry/workflows`)
      .then((r) => r.ok ? r.json() : [])
      .then((d) => setWorkflows(Array.isArray(d) ? d : []))
      .catch(() => setWorkflows([]));
  }, [projectId]);
  return { workflows };
}

// ---------------------------------------------------------------------------
// Element type helpers
// ---------------------------------------------------------------------------

function detectElementKind(
  tagName: string,
  componentName: string | null | undefined,
): "form" | "table" | "other" {
  const comp = (componentName || "").toLowerCase();
  const tag = tagName.toLowerCase();
  if (tag === "form" || comp.includes("form")) return "form";
  if (tag === "table" || tag === "tbody" || comp.includes("table") || comp.includes("grid") || comp.includes("datatable")) return "table";
  return "other";
}

// ---------------------------------------------------------------------------
// Data Binding tab
// ---------------------------------------------------------------------------

interface DataTabProps {
  projectId: string;
  componentName: string | null | undefined;
  tagName: string;
  onAIEdit: (instruction: string) => void;
}

function DataTab({ projectId, componentName, tagName, onAIEdit }: DataTabProps) {
  const { entities, loading } = useRegistryEntities(projectId);
  const kind = detectElementKind(tagName, componentName);

  const [entityName, setEntityName] = useState("");
  const [mode, setMode] = useState<"create" | "edit">("create");
  const [submitRoute, setSubmitRoute] = useState("");
  const [applying, setApplying] = useState(false);

  const selectedEntity = entities.find((e) => e.name === entityName);

  useEffect(() => {
    if (selectedEntity) {
      const route = selectedEntity.apiRoutes.find((r) => r.includes("POST")) || selectedEntity.apiRoutes[0] || `/api/${entityName.toLowerCase()}s`;
      setSubmitRoute(route);
    }
  }, [entityName, selectedEntity]);

  const handleApply = useCallback(async () => {
    if (!entityName || !submitRoute) return;
    setApplying(true);

    const entity = entities.find((e) => e.name === entityName);
    const fieldList = entity?.fields.map((f) => `${f.name} (${f.type}${f.required ? ", required" : ""})`).join(", ") || "";

    let instruction = "";
    if (kind === "form") {
      instruction =
        `Bind this form to the "${entityName}" entity. ` +
        `Make it ${mode === "create" ? "POST to" : "PUT/PATCH to"} "${submitRoute}". ` +
        (mode === "edit" ? `Pre-populate fields from the existing record. ` : "") +
        `The entity fields are: ${fieldList}. ` +
        `Use react-hook-form or controlled state. Add proper validation for required fields. ` +
        `On success, show a toast and redirect or reset the form.`;
    } else if (kind === "table") {
      instruction =
        `Bind this table to the "${entityName}" entity. ` +
        `Fetch data from "${submitRoute}" and display it with columns matching: ${fieldList}. ` +
        `Add sorting, pagination, and an empty state.`;
    }

    onAIEdit(instruction);
    setApplying(false);
  }, [entityName, submitRoute, mode, kind, entities, onAIEdit]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (entities.length === 0) {
    return (
      <div className="p-3 text-xs text-muted-foreground space-y-1">
        <p className="font-medium">No entities in registry</p>
        <p>Generate the project first to populate the data model registry.</p>
      </div>
    );
  }

  if (kind === "other") {
    return (
      <div className="p-3 text-xs text-muted-foreground space-y-1">
        <p>Select a <strong>Form</strong> or <strong>Table</strong> element to bind it to a data entity.</p>
        <p className="text-[10px]">Current element: <code className="bg-muted px-1 rounded">{tagName}</code></p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
        <Database className="h-3.5 w-3.5" />
        {kind === "form" ? "Form → Entity" : "Table → Entity"}
      </div>

      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Entity</Label>
        <Select value={entityName || "__none__"} onValueChange={(v) => setEntityName(v === "__none__" ? "" : v)}>
          <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="Select entity…" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">— None —</SelectItem>
            {entities.map((e) => <SelectItem key={e.name} value={e.name}>{e.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {entityName && (
        <>
          {kind === "form" && (
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Mode</Label>
              <Select value={mode} onValueChange={(v) => setMode(v as "create" | "edit")}>
                <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="create">Create new record</SelectItem>
                  <SelectItem value="edit">Edit existing record</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">{kind === "form" ? "Submit route" : "Data route"}</Label>
            <Input
              value={submitRoute}
              onChange={(e) => setSubmitRoute(e.target.value)}
              className="h-7 text-xs"
              placeholder="/api/..."
            />
          </div>

          {selectedEntity && selectedEntity.fields.length > 0 && (
            <div className="pt-1 border-t space-y-0.5">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">Fields</p>
              {selectedEntity.fields.map((f) => (
                <div key={f.name} className="flex items-center justify-between text-[10px]">
                  <span className="font-mono">{f.name}</span>
                  <span className="text-muted-foreground">{f.type}{f.required ? " *" : ""}</span>
                </div>
              ))}
            </div>
          )}

          <Button
            size="sm"
            className="w-full h-7 text-xs gap-1.5"
            onClick={handleApply}
            disabled={applying || !submitRoute}
          >
            {applying ? <Loader2 className="h-3 w-3 animate-spin" /> : <Link2 className="h-3 w-3" />}
            Apply Binding via AI
          </Button>
          <p className="text-[10px] text-muted-foreground">
            AI will rewrite the component to connect it to the {entityName} entity.
          </p>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workflow Binding tab
// ---------------------------------------------------------------------------

interface FlowsTabProps {
  projectId: string;
  componentName: string | null | undefined;
  tagName: string;
  onAIEdit: (instruction: string) => void;
}

function FlowsTab({ projectId, componentName, tagName, onAIEdit }: FlowsTabProps) {
  const { workflows } = useRegistryWorkflows(projectId);
  const kind = detectElementKind(tagName, componentName);

  const [workflowId, setWorkflowId] = useState("");
  const [applying, setApplying] = useState(false);

  const selectedWorkflow = workflows.find((w) => w.id === workflowId);

  const handleConnect = useCallback(async () => {
    if (!workflowId || !selectedWorkflow) return;
    setApplying(true);

    const inputDesc = selectedWorkflow.inputs.length > 0
      ? `Pass the following form fields as workflow inputs: ${selectedWorkflow.inputs.map((i) => i.name).join(", ")}.`
      : "Pass the form's submitted values as workflow inputs.";

    const instruction =
      `After this form submits successfully, trigger the "${selectedWorkflow.name}" workflow. ` +
      `${inputDesc} ` +
      `Call POST /api/workflows/${workflowId}/trigger (or the correct workflow trigger endpoint). ` +
      `Handle errors gracefully and show the user feedback on success.`;

    onAIEdit(instruction);
    setApplying(false);
  }, [workflowId, selectedWorkflow, onAIEdit]);

  if (kind !== "form") {
    return (
      <div className="p-3 text-xs text-muted-foreground">
        <p>Select a <strong>Form</strong> element to connect it to a workflow.</p>
        <p className="text-[10px] mt-1">Current: <code className="bg-muted px-1 rounded">{tagName}</code></p>
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div className="p-3 text-xs text-muted-foreground space-y-1">
        <p className="font-medium">No workflows found</p>
        <p>Define workflows in the Workflows tab, then come back to connect them.</p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
        <Workflow className="h-3.5 w-3.5" />
        Trigger on Submit
      </div>

      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Workflow</Label>
        <Select value={workflowId || "__none__"} onValueChange={(v) => setWorkflowId(v === "__none__" ? "" : v)}>
          <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="— None —" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">— None —</SelectItem>
            {workflows.map((w) => <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {selectedWorkflow?.description && (
        <p className="text-[10px] text-muted-foreground italic">{selectedWorkflow.description}</p>
      )}

      {workflowId && selectedWorkflow && (
        <>
          {selectedWorkflow.inputs.length > 0 && (
            <div className="pt-1 border-t space-y-0.5">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">Workflow inputs</p>
              {selectedWorkflow.inputs.map((inp) => (
                <div key={inp.name} className="flex items-center justify-between text-[10px]">
                  <span className="font-mono">{inp.name}</span>
                  {inp.type && <span className="text-muted-foreground">{inp.type}</span>}
                </div>
              ))}
            </div>
          )}

          <Button
            size="sm"
            className="w-full h-7 text-xs gap-1.5"
            onClick={handleConnect}
            disabled={applying}
          >
            {applying ? <Loader2 className="h-3 w-3 animate-spin" /> : <Workflow className="h-3 w-3" />}
            Connect Workflow via AI
          </Button>
          <p className="text-[10px] text-muted-foreground">
            AI will add a workflow trigger to this form's submit handler.
          </p>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel types
// ---------------------------------------------------------------------------

interface ElementProps {
  props: Record<string, string>;
  classes: string[];
  component_name: string | null;
  text_content: string | null;
  self_closing: boolean;
}

type PanelTab = "element" | "data" | "flows" | "interactions";

interface ContextPanelProps {
  projectId: string;
  onClassChange: (action: "add" | "remove" | "replace", cls: string, replaceCls?: string) => void;
  onEditText: () => void;
  onAskAI: () => void;
  onDeleteElement: () => void;
  onAIEdit?: (instruction: string) => void;
}

export function ContextPanel({
  projectId,
  onClassChange,
  onEditText,
  onAskAI,
  onDeleteElement,
  onAIEdit,
}: ContextPanelProps) {
  const selectedElement = useVisualEditorStore((s) => s.selectedElement);
  const [newClass, setNewClass] = useState("");
  const [elementProps, setElementProps] = useState<ElementProps | null>(null);
  const [propsLoading, setPropsLoading] = useState(false);
  const [tab, setTab] = useState<PanelTab>("element");

  // Fetch element props when selection changes
  useEffect(() => {
    if (!selectedElement?.source) {
      setElementProps(null);
      return;
    }

    let cancelled = false;
    setPropsLoading(true);

    api
      .get<ElementProps>(
        `/api/projects/${projectId}/visual-edit/element-props?file=${encodeURIComponent(selectedElement.source.file)}&line=${selectedElement.source.line}`,
      )
      .then((data) => {
        if (!cancelled) setElementProps(data);
      })
      .catch(() => {
        if (!cancelled) setElementProps(null);
      })
      .finally(() => {
        if (!cancelled) setPropsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, selectedElement?.source?.file, selectedElement?.source?.line]);

  const handleAddClass = useCallback(() => {
    const cls = newClass.trim();
    if (!cls) return;
    onClassChange("add", cls);
    setNewClass("");
  }, [newClass, onClassChange]);

  const handleRemoveClass = useCallback(
    (cls: string) => {
      onClassChange("remove", cls);
    },
    [onClassChange],
  );

  // Parse classes from element className
  const currentClasses = selectedElement?.className
    ? selectedElement.className.split(/\s+/).filter(Boolean)
    : [];

  if (!selectedElement) {
    return (
      <div className="w-[320px] shrink-0 border-l flex flex-col overflow-hidden">
        <div className="flex items-center px-3 py-2 border-b shrink-0">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            Properties
          </span>
        </div>
        <div className="flex-1 flex items-center justify-center px-4">
          <p className="text-xs text-muted-foreground text-center">
            Select an element in the canvas to view its properties
          </p>
        </div>
      </div>
    );
  }

  const elementKind = detectElementKind(
    selectedElement.tagName,
    elementProps?.component_name || selectedElement.source?.component,
  );

  const TABS: { id: PanelTab; label: string; icon: React.ElementType; disabled?: boolean }[] = [
    { id: "element", label: "Element", icon: Type },
    { id: "data", label: "Data", icon: Database },
    { id: "flows", label: "Flows", icon: Workflow, disabled: elementKind !== "form" },
    { id: "interactions", label: "Interact", icon: Zap, disabled: elementKind !== "form" },
  ];

  // The InteractionEditor addresses a page by its schema-relative path
  // (e.g. "employees/new"). We derive that from the selected element's
  // source file — Next apps put page components at
  // `src/app/<route>/page.tsx`, so we strip the framework wrapping and
  // let the backend's resolver map the route back to a schema JSON.
  const derivedPagePath = React.useMemo(() => {
    const file = selectedElement?.source?.file;
    if (!file) return null;
    const m = file.match(/src\/app\/(.+?)\/page\.tsx$/);
    if (m) return m[1];
    // Fallback: apps that already emit a schemas path directly.
    const s = file.match(/src\/schemas\/(.+)\.json$/);
    return s ? s[1] : null;
  }, [selectedElement?.source?.file]);

  return (
    <div className="w-[320px] shrink-0 border-l flex flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b shrink-0">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => !t.disabled && setTab(t.id)}
              disabled={t.disabled}
              className={`flex-1 flex items-center justify-center gap-1 py-2 text-[11px] font-medium border-b-2 transition-colors ${
                active
                  ? "border-primary text-foreground"
                  : t.disabled
                  ? "border-transparent text-muted-foreground/40 cursor-not-allowed"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              title={t.disabled ? "Select a Form element to use this tab" : undefined}
            >
              <Icon className="h-3 w-3" />
              {t.label}
            </button>
          );
        })}
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* ── Element tab ── */}
        {tab === "element" && (
          <>
            {/* Element Info */}
            <div className="px-3 py-3 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="secondary" className="text-[10px] font-mono">
                  {selectedElement.tagName}
                </Badge>
                {(elementProps?.component_name || selectedElement.source?.component) && (
                  <Badge variant="outline" className="text-[10px]">
                    {elementProps?.component_name || selectedElement.source?.component}
                  </Badge>
                )}
              </div>
              {selectedElement.source && (
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground font-mono">
                  <ExternalLink className="h-2.5 w-2.5" />
                  {selectedElement.source.file}:{selectedElement.source.line}
                </div>
              )}
            </div>

            <Separator />

            {/* Tailwind Classes */}
            <div className="px-3 py-3 space-y-2">
              <span className="text-xs font-medium">Tailwind Classes</span>
              <div className="flex flex-wrap gap-1">
                {currentClasses.map((cls) => (
                  <span
                    key={cls}
                    className="inline-flex items-center gap-0.5 rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono group"
                  >
                    {cls}
                    <button
                      className="opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={() => handleRemoveClass(cls)}
                    >
                      <X className="h-2.5 w-2.5 text-muted-foreground hover:text-destructive" />
                    </button>
                  </span>
                ))}
                {currentClasses.length === 0 && (
                  <span className="text-[10px] text-muted-foreground italic">No classes</span>
                )}
              </div>
              <div className="flex items-center gap-1">
                <Input
                  className="h-6 text-[10px] font-mono flex-1"
                  placeholder="Add class..."
                  value={newClass}
                  onChange={(e) => setNewClass(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddClass();
                    }
                  }}
                />
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  onClick={handleAddClass}
                  disabled={!newClass.trim()}
                >
                  <Plus className="h-3 w-3" />
                </Button>
              </div>
            </div>

            <Separator />

            {/* Props (from backend) */}
            {elementProps && Object.keys(elementProps.props).length > 0 && (
              <>
                <div className="px-3 py-3 space-y-2">
                  <span className="text-xs font-medium">Props</span>
                  <div className="space-y-1.5">
                    {Object.entries(elementProps.props).map(([key, value]) => (
                      <div key={key} className="flex items-center gap-2">
                        <span className="text-[10px] font-mono text-muted-foreground shrink-0 w-16 truncate">
                          {key}
                        </span>
                        <span className="text-[10px] font-mono truncate flex-1 bg-muted rounded px-1 py-0.5">
                          {value}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                <Separator />
              </>
            )}

            {/* Actions */}
            <div className="px-3 py-3 space-y-1">
              <span className="text-xs font-medium">Actions</span>
              <div className="grid grid-cols-2 gap-1 mt-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-[10px] gap-1"
                  onClick={onEditText}
                >
                  <Type className="h-3 w-3" />
                  Edit Text
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-[10px] gap-1"
                  onClick={onAskAI}
                >
                  <Sparkles className="h-3 w-3" />
                  Ask AI
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-[10px] gap-1 text-destructive hover:text-destructive"
                  onClick={onDeleteElement}
                >
                  <Trash2 className="h-3 w-3" />
                  Delete
                </Button>
              </div>
            </div>
          </>
        )}

        {/* ── Data tab ── */}
        {tab === "data" && onAIEdit && (
          <DataTab
            projectId={projectId}
            componentName={elementProps?.component_name || selectedElement.source?.component}
            tagName={selectedElement.tagName}
            onAIEdit={onAIEdit}
          />
        )}
        {tab === "data" && !onAIEdit && (
          <div className="p-3 text-xs text-muted-foreground">
            AI editing not available in this context.
          </div>
        )}

        {/* ── Flows tab ── */}
        {tab === "flows" && onAIEdit && (
          <FlowsTab
            projectId={projectId}
            componentName={elementProps?.component_name || selectedElement.source?.component}
            tagName={selectedElement.tagName}
            onAIEdit={onAIEdit}
          />
        )}
        {tab === "flows" && !onAIEdit && (
          <div className="p-3 text-xs text-muted-foreground">
            AI editing not available in this context.
          </div>
        )}

        {/* ── Interactions tab ── */}
        {tab === "interactions" && (
          <InteractionsTab
            projectId={projectId}
            componentName={elementProps?.component_name || selectedElement.source?.component}
            tagName={selectedElement.tagName}
            pagePath={derivedPagePath}
          />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interactions tab — per-field authoring UI backed by
// POST /api/projects/{id}/field-interactions (same validator as Smith).
//
// This is the visual counterpart to Smith's `set_field_interaction` tool.
// Scoping: only shown for form elements — the interaction contract lives on
// form fields. Field list comes from the bound entity's registry columns.
// ---------------------------------------------------------------------------

interface InteractionsTabProps {
  projectId: string;
  componentName: string | null | undefined;
  tagName: string;
  pagePath: string | null;
}

function InteractionsTab({ projectId, componentName, tagName, pagePath }: InteractionsTabProps) {
  const { entities, loading } = useRegistryEntities(projectId);
  const kind = detectElementKind(tagName, componentName);
  const [entityName, setEntityName] = useState("");
  const [fieldName, setFieldName] = useState("");

  const selectedEntity = entities.find((e) => e.name === entityName);
  const selectedField = selectedEntity?.fields.find((f) => f.name === fieldName);

  if (kind !== "form") {
    return (
      <div className="p-3 text-xs text-muted-foreground">
        <p>Select a <strong>Form</strong> element to author field interactions.</p>
      </div>
    );
  }
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (!pagePath) {
    return (
      <div className="p-3 text-xs text-muted-foreground">
        <p>Can't derive the page path from this element.</p>
        <p className="text-[10px] mt-1">The Interactions editor needs a source file under <code>src/app/…/page.tsx</code>.</p>
      </div>
    );
  }
  if (entities.length === 0) {
    return (
      <div className="p-3 text-xs text-muted-foreground space-y-1">
        <p className="font-medium">No entities in registry</p>
        <p>Generate the project first to populate the data model.</p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
        <Zap className="h-3.5 w-3.5" />
        Field Interactions
      </div>
      <p className="text-[10px] text-muted-foreground">
        Author computed values, dependent options, conditional visibility, and other reactive
        behaviour. Same runtime as Smith uses via chat — mirrored to <code>plan.json</code>.
      </p>

      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Entity</Label>
        <Select value={entityName || "__none__"} onValueChange={(v) => {
          setEntityName(v === "__none__" ? "" : v);
          setFieldName("");
        }}>
          <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="Select entity…" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">— None —</SelectItem>
            {entities.map((e) => <SelectItem key={e.name} value={e.name}>{e.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {selectedEntity && (
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">Field</Label>
          <Select value={fieldName || "__none__"} onValueChange={(v) => setFieldName(v === "__none__" ? "" : v)}>
            <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="Pick a field…" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">— None —</SelectItem>
              {selectedEntity.fields.map((f) => (
                <SelectItem key={f.name} value={f.name}>
                  {f.name} <span className="text-muted-foreground">({f.type})</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {selectedEntity && selectedField && (
        <div className="pt-2">
          <InteractionEditor
            // Remount on selection change so the editor's internal draft
            // is reset from the fresh field's own baseline instead of
            // carrying over the previous field's edits.
            key={`${pagePath}::${selectedField.name}`}
            projectId={projectId}
            page={pagePath}
            field={{ name: selectedField.name, kind: selectedField.type }}
            siblings={selectedEntity.fields
              .filter((f) => f.name !== selectedField.name)
              .map((f) => ({ name: f.name, kind: f.type }))}
          />
        </div>
      )}
    </div>
  );
}
