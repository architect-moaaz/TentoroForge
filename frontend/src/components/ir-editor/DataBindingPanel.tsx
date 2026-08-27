"use client";

/**
 * DataBindingPanel — shows entity/field binding controls for Form and DataTable nodes.
 *
 * Renders inside the "Data" tab of the IR editor Properties panel.
 * Fetches entities from GET /api/projects/:id/registry/entities and
 * lets the user wire a Form to a registry entity (create/edit mode) and
 * map form fields to entity fields.
 */

import { useEffect, useState, useCallback } from "react";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Loader2, Link2, Link2Off, Database } from "lucide-react";
import { useIREditorStore, type IRNode, type NodePath } from "@/stores/ir-editor";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

// ---------------------------------------------------------------------------
// Types (mirror backend schema)
// ---------------------------------------------------------------------------

interface EntityFieldSchema {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

interface EntitySchema {
  name: string;
  fields: EntityFieldSchema[];
  apiRoutes: string[];
}

interface WorkflowSchema {
  id: string;
  name: string;
  description: string;
  trigger: string;
  inputs: Array<{ name: string; type: string }>;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

function useRegistryEntities(projectId: string | null) {
  const [entities, setEntities] = useState<EntitySchema[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    fetch(`${API_BASE}/api/projects/${projectId}/registry/entities`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setEntities(Array.isArray(data) ? data : []))
      .catch(() => setEntities([]))
      .finally(() => setLoading(false));
  }, [projectId]);

  return { entities, loading };
}

function useRegistryWorkflows(projectId: string | null) {
  const [workflows, setWorkflows] = useState<WorkflowSchema[]>([]);

  useEffect(() => {
    if (!projectId) return;
    fetch(`${API_BASE}/api/projects/${projectId}/registry/workflows`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setWorkflows(Array.isArray(data) ? data : []))
      .catch(() => setWorkflows([]));
  }, [projectId]);

  return { workflows };
}

// ---------------------------------------------------------------------------
// Section: Form entity binding
// ---------------------------------------------------------------------------

interface FormBindingProps {
  node: IRNode;
  selectedPath: NodePath;
  entities: EntitySchema[];
  workflows: WorkflowSchema[];
}

function FormBindingSection({ node, selectedPath, entities, workflows }: FormBindingProps) {
  const applyOps = useIREditorStore((s) => s.applyOps);
  const binding = node.entityBinding as Record<string, unknown> | undefined;

  const setBinding = useCallback(
    (patch: Record<string, unknown> | null) => {
      applyOps([{
        type: "setProp",
        path: selectedPath,
        prop: "entityBinding",
        value: patch === null ? undefined : { ...(binding || {}), ...patch },
      }]);
    },
    [applyOps, selectedPath, binding],
  );

  const selectedEntity = entities.find((e) => e.name === binding?.entity);

  // Auto-suggest submitRoute when entity is selected
  const handleEntityChange = (entityName: string) => {
    if (!entityName || entityName === "__none__") {
      setBinding(null);
      return;
    }
    const entity = entities.find((e) => e.name === entityName);
    const postRoute = entity?.apiRoutes.find((r) => r.includes("POST")) ||
      entity?.apiRoutes[0] ||
      `/api/${entityName.toLowerCase()}s`;
    setBinding({ entity: entityName, mode: "create", submitRoute: postRoute });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
        <Database className="h-3.5 w-3.5" />
        Form → Entity Binding
      </div>

      {/* Entity picker */}
      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Entity</Label>
        <Select
          value={(binding?.entity as string) || "__none__"}
          onValueChange={handleEntityChange}
        >
          <SelectTrigger className="h-7 text-xs">
            <SelectValue placeholder="Select entity…" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">— None —</SelectItem>
            {entities.map((e) => (
              <SelectItem key={e.name} value={e.name}>{e.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {!!binding?.entity && (
        <>
          {/* Mode */}
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Mode</Label>
            <Select
              value={(binding.mode as string) || "create"}
              onValueChange={(v) => setBinding({ mode: v })}
            >
              <SelectTrigger className="h-7 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="create">Create new record</SelectItem>
                <SelectItem value="edit">Edit existing record</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Submit route */}
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Submit route</Label>
            <Select
              value={(binding.submitRoute as string) || ""}
              onValueChange={(v) => setBinding({ submitRoute: v })}
            >
              <SelectTrigger className="h-7 text-xs">
                <SelectValue placeholder="Pick route…" />
              </SelectTrigger>
              <SelectContent>
                {selectedEntity?.apiRoutes.map((r) => (
                  <SelectItem key={r} value={r}>{r}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={(binding.submitRoute as string) || ""}
              onChange={(e) => setBinding({ submitRoute: e.target.value })}
              className="h-7 text-xs mt-1"
              placeholder="/api/entity"
            />
          </div>

          {/* Prefill route (edit mode only) */}
          {binding.mode === "edit" && (
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Prefill route (edit)</Label>
              <Input
                value={(binding.prefillRoute as string) || ""}
                onChange={(e) => setBinding({ prefillRoute: e.target.value || undefined })}
                className="h-7 text-xs"
                placeholder="/api/entity/:id"
              />
            </div>
          )}

          {/* On-success workflow */}
          {workflows.length > 0 && (
            <div className="space-y-1 pt-1 border-t">
              <Label className="text-xs text-muted-foreground">Trigger workflow on success</Label>
              <Select
                value={(binding.onSuccessWorkflow as Record<string, unknown>)?.workflowId as string || "__none__"}
                onValueChange={(wfId) => {
                  if (wfId === "__none__") {
                    setBinding({ onSuccessWorkflow: undefined });
                  } else {
                    setBinding({ onSuccessWorkflow: { workflowId: wfId, inputMapping: {} } });
                  }
                }}
              >
                <SelectTrigger className="h-7 text-xs">
                  <SelectValue placeholder="— None —" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">— None —</SelectItem>
                  {workflows.map((wf) => (
                    <SelectItem key={wf.id} value={wf.id}>{wf.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Entity field list (informational) */}
          {selectedEntity && selectedEntity.fields.length > 0 && (
            <div className="pt-1 border-t">
              <p className="text-[10px] text-muted-foreground mb-1.5 font-medium uppercase tracking-wide">
                Entity fields
              </p>
              <div className="space-y-0.5">
                {selectedEntity.fields.map((f) => (
                  <div key={f.name} className="flex items-center justify-between text-[10px]">
                    <span className="font-mono text-foreground">{f.name}</span>
                    <span className="text-muted-foreground">{f.type}{f.required ? " *" : ""}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Clear binding */}
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-xs text-muted-foreground w-full"
            onClick={() => setBinding(null)}
          >
            <Link2Off className="h-3 w-3 mr-1" />
            Clear binding
          </Button>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: DataTable entity binding
// ---------------------------------------------------------------------------

interface TableBindingProps {
  node: IRNode;
  selectedPath: NodePath;
  entities: EntitySchema[];
}

function TableBindingSection({ node, selectedPath, entities }: TableBindingProps) {
  const applyOps = useIREditorStore((s) => s.applyOps);
  const binding = node.entityBinding as { entity: string; columns?: string[] } | undefined;

  const setEntityBinding = useCallback(
    (patch: { entity: string; columns?: string[] } | null) => {
      applyOps([{
        type: "setProp",
        path: selectedPath,
        prop: "entityBinding",
        value: patch === null ? undefined : { ...(binding || {}), ...patch },
      }]);
    },
    [applyOps, selectedPath, binding],
  );

  const selectedEntity = entities.find((e) => e.name === binding?.entity);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
        <Database className="h-3.5 w-3.5" />
        Table → Entity Binding
      </div>

      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Entity</Label>
        <Select
          value={binding?.entity || "__none__"}
          onValueChange={(v) => {
            if (v === "__none__") setEntityBinding(null);
            else setEntityBinding({ entity: v });
          }}
        >
          <SelectTrigger className="h-7 text-xs">
            <SelectValue placeholder="Select entity…" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">— None —</SelectItem>
            {entities.map((e) => (
              <SelectItem key={e.name} value={e.name}>{e.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {binding?.entity && selectedEntity && (
        <>
          <div className="pt-1 border-t">
            <p className="text-[10px] text-muted-foreground mb-1.5 font-medium uppercase tracking-wide">
              Available columns
            </p>
            <div className="space-y-0.5">
              {selectedEntity.fields.map((f) => (
                <div key={f.name} className="flex items-center justify-between text-[10px]">
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!binding.columns || binding.columns.includes(f.name)}
                      onChange={(e) => {
                        const current = binding.columns || selectedEntity.fields.map((x) => x.name);
                        const next = e.target.checked
                          ? [...current, f.name]
                          : current.filter((c) => c !== f.name);
                        setEntityBinding({ entity: binding.entity, columns: next });
                      }}
                      className="h-3 w-3"
                    />
                    <span className="font-mono text-foreground">{f.name}</span>
                  </label>
                  <span className="text-muted-foreground">{f.type}</span>
                </div>
              ))}
            </div>
          </div>

          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-xs text-muted-foreground w-full"
            onClick={() => setEntityBinding(null)}
          >
            <Link2Off className="h-3 w-3 mr-1" />
            Clear binding
          </Button>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface DataBindingPanelProps {
  node: IRNode;
  selectedPath: NodePath;
}

export function DataBindingPanel({ node, selectedPath }: DataBindingPanelProps) {
  const projectId = useIREditorStore((s) => s.projectId);
  const { entities, loading } = useRegistryEntities(projectId);
  const { workflows } = useRegistryWorkflows(projectId);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-6">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (entities.length === 0) {
    return (
      <div className="p-3 text-xs text-muted-foreground space-y-1">
        <p className="font-medium">No entities found</p>
        <p>Generate the project first to populate the registry, then come back here to bind this component to an entity.</p>
      </div>
    );
  }

  if (node.node === "Form") {
    return (
      <div className="p-3">
        <FormBindingSection
          node={node}
          selectedPath={selectedPath}
          entities={entities}
          workflows={workflows}
        />
      </div>
    );
  }

  if (node.node === "DataTable") {
    return (
      <div className="p-3">
        <TableBindingSection
          node={node}
          selectedPath={selectedPath}
          entities={entities}
        />
      </div>
    );
  }

  return (
    <div className="p-3 text-xs text-muted-foreground">
      <div className="flex items-center gap-1.5 mb-2">
        <Link2 className="h-3.5 w-3.5" />
        <span>Data binding is available for Form and DataTable nodes.</span>
      </div>
      <p>Select a Form or DataTable to bind it to a backend entity.</p>
    </div>
  );
}
