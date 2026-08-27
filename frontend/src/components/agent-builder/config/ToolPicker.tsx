"use client";

import { Plus, X, Wand2 } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import type {
  ToolConfig,
  ToolType,
  ToolParameter,
  DataEngineOperation,
} from "@/types/agent-builder";

/** Minimal shape the workflows list endpoint returns. Only the fields the
 *  picker needs — full workflow detail is fetched separately when the user
 *  picks one, so we can prefill parameters from the workflow's inputs[]. */
interface WorkflowListItem {
  id: string;
  name: string;
  description?: string | null;
}

interface WorkflowDetail {
  id: string;
  name: string;
  inputs?: Array<{ name: string; type?: string; required?: boolean; label?: string }>;
  processVariables?: Array<{ name: string; type?: string; required?: boolean }>;
}

interface AppModel {
  database?: { tables?: Array<{ name: string }> };
}

/** Minimal shape from GET /api/orgs/{id}/mcp-servers. */
interface McpServerListItem {
  id: string;
  name: string;
  server_url?: string;
  transport?: string;
  enabled?: boolean;
}

/** Minimal shape from GET /api/orgs/{id}/mcp-servers/{id}/tools — matches
 *  the MCP `tools/list` response. `inputSchema` is a JSON Schema object; we
 *  only reach for `properties` to render the args-mapping form. */
interface McpToolDescriptor {
  name: string;
  description?: string;
  inputSchema?: {
    type?: string;
    properties?: Record<string, { type?: string; description?: string }>;
    required?: string[];
  };
}

interface ToolPickerProps {
  config: ToolConfig;
  onUpdate: (config: Partial<ToolConfig>) => void;
  projectId?: string;
  orgId?: string;
}

// Map a data-engine operation to an HTTP method + relative path shape. Keeps
// the runtime side dumb — it just interpolates `entity` and (for get/update/
// delete) an `id` parameter the agent will supply at call time.
const DATA_ENGINE_METHOD: Record<DataEngineOperation, string> = {
  list: "GET", get: "GET", create: "POST", update: "PATCH", delete: "DELETE",
};
const dataEngineEndpoint = (entity: string, op: DataEngineOperation): string => {
  if (!entity) return "";
  return op === "list" || op === "create"
    ? `/api/data/${entity}`
    : `/api/data/${entity}/{id}`;
};

export function ToolPicker({ config, onUpdate, projectId, orgId }: ToolPickerProps) {
  // Real workflows for this project — powers the workflow-type dropdown.
  const { data: workflows = [] } = useQuery<WorkflowListItem[]>({
    queryKey: ["project", projectId, "workflows"],
    queryFn: () => api.get<WorkflowListItem[]>(`/api/projects/${projectId}/workflows`),
    enabled: !!projectId && config.tool_type === "workflow",
  });

  // Fetched on demand when a workflow is selected — used to prefill params.
  const { data: workflowDetail } = useQuery<WorkflowDetail>({
    queryKey: ["project", projectId, "workflows", config.workflow_id, "detail"],
    queryFn: () =>
      api.get<WorkflowDetail>(
        `/api/projects/${projectId}/workflows/${config.workflow_id}`,
      ),
    enabled:
      !!projectId && config.tool_type === "workflow" && !!config.workflow_id,
  });

  // Real entity list for the data_engine picker.
  const { data: appModel } = useQuery<AppModel>({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
    enabled: !!projectId && config.tool_type === "data_engine",
  });
  const entityNames = useMemo(
    () => (appModel?.database?.tables ?? []).map((t) => t.name),
    [appModel],
  );

  // Org-registered MCP servers — powers the server dropdown for tool_type=mcp.
  // Filtered to enabled-only so operators can pause a server without breaking
  // author-time flows silently.
  const { data: mcpServers = [] } = useQuery<McpServerListItem[]>({
    queryKey: ["mcpServers", orgId],
    queryFn: () => api.get<McpServerListItem[]>(`/api/orgs/${orgId}/mcp-servers`),
    enabled: !!orgId && config.tool_type === "mcp",
  });
  const enabledMcpServers = useMemo(
    () => mcpServers.filter((s) => s.enabled !== false),
    [mcpServers],
  );

  // Tools advertised by the selected server (result of MCP `tools/list`).
  const { data: mcpTools = [] } = useQuery<McpToolDescriptor[]>({
    queryKey: ["mcpTools", orgId, config.mcp_server_id],
    queryFn: () =>
      api.get<McpToolDescriptor[]>(
        `/api/orgs/${orgId}/mcp-servers/${config.mcp_server_id}/tools`,
      ),
    enabled: !!orgId && config.tool_type === "mcp" && !!config.mcp_server_id,
  });
  const selectedMcpTool = useMemo(
    () => mcpTools.find((t) => t.name === config.mcp_tool_name),
    [mcpTools, config.mcp_tool_name],
  );

  const addParameter = () => {
    const params = config.parameters || [];
    onUpdate({ parameters: [...params, { name: "", type: "string", required: true }] });
  };
  const updateParameter = (index: number, updates: Partial<ToolParameter>) => {
    const params = [...(config.parameters || [])];
    params[index] = { ...params[index], ...updates };
    onUpdate({ parameters: params });
  };
  const removeParameter = (index: number) => {
    const params = [...(config.parameters || [])];
    params.splice(index, 1);
    onUpdate({ parameters: params });
  };

  // When the tool type changes, clear the fields that no longer apply so the
  // saved shape stays clean. Runtime doesn't care but the JSON stays tidy.
  // Switching TO mcp clears the http/workflow/data-engine leftovers; switching
  // AWAY from mcp clears mcp_server_id/mcp_tool_name/args_mapping so a stale
  // server reference can't ride along on a workflow tool.
  const changeToolType = (t: ToolType) => {
    if (t === "mcp") {
      onUpdate({
        tool_type: t,
        endpoint: "", method: "", query: "", code: "",
        workflow_id: undefined, entity: undefined, operation: undefined,
        mcp_server_id: undefined, mcp_tool_name: undefined, args_mapping: undefined,
      });
    } else {
      onUpdate({
        tool_type: t,
        endpoint: "", method: "GET", query: "", code: "",
        workflow_id: undefined, entity: undefined, operation: undefined,
        mcp_server_id: undefined, mcp_tool_name: undefined, args_mapping: undefined,
      });
    }
  };

  // Populate the endpoint automatically whenever a workflow is picked.
  useEffect(() => {
    if (config.tool_type === "workflow" && config.workflow_id) {
      const desired = `/api/workflows/${config.workflow_id}/execute`;
      if (config.endpoint !== desired || config.method !== "POST") {
        onUpdate({ endpoint: desired, method: "POST" });
      }
    }
  }, [config.tool_type, config.workflow_id, config.endpoint, config.method, onUpdate]);

  // Populate the endpoint automatically for data-engine picks.
  useEffect(() => {
    if (config.tool_type === "data_engine" && config.entity && config.operation) {
      const desired = dataEngineEndpoint(config.entity, config.operation);
      const desiredMethod = DATA_ENGINE_METHOD[config.operation];
      if (config.endpoint !== desired || config.method !== desiredMethod) {
        onUpdate({ endpoint: desired, method: desiredMethod });
      }
    }
  }, [config.tool_type, config.entity, config.operation, config.endpoint, config.method, onUpdate]);

  const prefillFromWorkflow = () => {
    if (!workflowDetail?.inputs) return;
    const params: ToolParameter[] = workflowDetail.inputs.map((input) => ({
      name: input.name,
      type: input.type || "string",
      required: input.required !== false,
      description: input.label,
    }));
    onUpdate({ parameters: params });
  };

  return (
    <div className="space-y-3">
      {/* Tool name */}
      <div>
        <Label className="text-xs">Tool Name</Label>
        <Input
          className="mt-1 h-8 text-xs"
          placeholder="e.g. lookup_customer"
          value={config.tool_name || ""}
          onChange={(e) => onUpdate({ tool_name: e.target.value })}
        />
      </div>

      {/* Tool type — now includes workflow + data_engine as first-class */}
      <div>
        <Label className="text-xs">Type</Label>
        <Select
          value={config.tool_type || "workflow"}
          onValueChange={(v) => changeToolType(v as ToolType)}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="workflow" className="text-xs">Workflow — call one of this project's workflows</SelectItem>
            <SelectItem value="data_engine" className="text-xs">Data engine — read or write a database record</SelectItem>
            <SelectItem value="api_call" className="text-xs">API call — internal HTTP endpoint</SelectItem>
            <SelectItem value="external" className="text-xs">External service — third-party HTTP</SelectItem>
            <SelectItem value="mcp" className="text-xs">MCP Server Tool</SelectItem>
            <SelectItem value="db_query" className="text-xs">DB query — raw SQL (advanced)</SelectItem>
            <SelectItem value="function" className="text-xs">Function — inline code (advanced)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Description */}
      <div>
        <Label className="text-xs">Description</Label>
        <Input
          className="mt-1 h-8 text-xs"
          placeholder="What does this tool do? (the LLM reads this)"
          value={config.description || ""}
          onChange={(e) => onUpdate({ description: e.target.value })}
        />
      </div>

      {/* --- Type-specific fields ------------------------------------- */}

      {/* WORKFLOW — pick a real workflow; endpoint + parameters auto-populate */}
      {config.tool_type === "workflow" && (
        <>
          <div>
            <Label className="text-xs">Workflow</Label>
            <Select
              value={config.workflow_id || ""}
              onValueChange={(v) => onUpdate({ workflow_id: v })}
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue placeholder={
                  workflows.length ? "Pick a workflow…" : projectId ? "No workflows in this project" : "Save the agent first"
                } />
              </SelectTrigger>
              <SelectContent>
                {workflows.map((w) => (
                  <SelectItem key={w.id} value={w.id} className="text-xs">
                    {w.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {config.endpoint && (
              <p className="mt-1 text-[10px] text-muted-foreground font-mono">
                POST {config.endpoint}
              </p>
            )}
          </div>
          {workflowDetail?.inputs && workflowDetail.inputs.length > 0 && (
            <div className="rounded border border-dashed border-muted p-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-muted-foreground">
                  {workflowDetail.inputs.length} declared input(s) on <em>{workflowDetail.name}</em>
                </span>
                <Button
                  type="button" variant="ghost" size="sm"
                  className="h-6 px-2 text-[10px]"
                  onClick={prefillFromWorkflow}
                >
                  <Wand2 className="mr-1 h-3 w-3" />
                  Prefill parameters
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* DATA ENGINE — pick an entity + operation; endpoint auto-populates */}
      {config.tool_type === "data_engine" && (
        <>
          <div>
            <Label className="text-xs">Record type (table)</Label>
            <Select
              value={config.entity || ""}
              onValueChange={(v) => onUpdate({ entity: v })}
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue placeholder={
                  entityNames.length ? "Pick a table…" : projectId ? "No tables in this project yet" : "Save the agent first"
                } />
              </SelectTrigger>
              <SelectContent>
                {entityNames.map((n) => (
                  <SelectItem key={n} value={n} className="text-xs font-mono">
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Operation</Label>
            <Select
              value={config.operation || ""}
              onValueChange={(v) => onUpdate({ operation: v as DataEngineOperation })}
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue placeholder="What should the agent do?" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="list" className="text-xs">List records</SelectItem>
                <SelectItem value="get" className="text-xs">Get one by ID</SelectItem>
                <SelectItem value="create" className="text-xs">Create a record</SelectItem>
                <SelectItem value="update" className="text-xs">Update a record by ID</SelectItem>
                <SelectItem value="delete" className="text-xs">Delete a record by ID</SelectItem>
              </SelectContent>
            </Select>
            {config.endpoint && (
              <p className="mt-1 text-[10px] text-muted-foreground font-mono">
                {config.method} {config.endpoint}
              </p>
            )}
          </div>
        </>
      )}

      {/* MCP — pick an org-registered server, then a tool from its tools/list;
          optionally bind each declared arg to another node's output via a
          FEEL-lite expression like `{{scan_events.image_id}}`. */}
      {config.tool_type === "mcp" && (
        <>
          <div>
            <Label className="text-xs">MCP Server</Label>
            <Select
              value={config.mcp_server_id || ""}
              onValueChange={(v) =>
                onUpdate({
                  mcp_server_id: v,
                  // Reset the tool + arg bindings — the new server advertises
                  // its own tools/list and the old tool name is unlikely to
                  // exist there.
                  mcp_tool_name: undefined,
                  args_mapping: undefined,
                })
              }
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue
                  placeholder={
                    enabledMcpServers.length
                      ? "Pick a server…"
                      : orgId
                        ? "No MCP servers registered — add one in Settings"
                        : "Org context missing"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {enabledMcpServers.map((s) => (
                  <SelectItem key={s.id} value={s.id} className="text-xs">
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {config.mcp_server_id && (
            <div>
              <Label className="text-xs">Tool</Label>
              <Select
                value={config.mcp_tool_name || ""}
                onValueChange={(v) =>
                  onUpdate({
                    mcp_tool_name: v,
                    // Reset arg bindings — the new tool has its own input schema.
                    args_mapping: undefined,
                  })
                }
              >
                <SelectTrigger className="mt-1 h-8 text-xs">
                  <SelectValue
                    placeholder={
                      mcpTools.length ? "Pick a tool…" : "Loading tools…"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {mcpTools.map((t) => (
                    <SelectItem key={t.name} value={t.name} className="text-xs font-mono">
                      {t.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedMcpTool?.description && (
                <p className="mt-1 text-[10px] text-muted-foreground">
                  {selectedMcpTool.description}
                </p>
              )}
            </div>
          )}

          {selectedMcpTool?.inputSchema?.properties && (
            <div className="rounded border border-dashed border-muted p-2">
              <div className="mb-1 text-[10px] text-muted-foreground">
                Argument bindings — reference another node's output with
                <code className="mx-1 rounded bg-muted px-1">
                  {"{{node_id.field}}"}
                </code>
              </div>
              <div className="space-y-1.5">
                {Object.entries(selectedMcpTool.inputSchema.properties).map(
                  ([argName, argSpec]) => {
                    const isRequired =
                      selectedMcpTool.inputSchema?.required?.includes(argName);
                    return (
                      <div key={argName} className="grid grid-cols-[80px_1fr] items-center gap-1">
                        <Label className="text-[10px] font-mono truncate">
                          {argName}
                          {isRequired && (
                            <span className="text-red-500 ml-0.5">*</span>
                          )}
                        </Label>
                        <Input
                          className="h-7 text-[10px] font-mono"
                          placeholder={argSpec?.type ? `{{…}} — ${argSpec.type}` : "{{…}}"}
                          value={config.args_mapping?.[argName] ?? ""}
                          onChange={(e) =>
                            onUpdate({
                              args_mapping: {
                                ...(config.args_mapping ?? {}),
                                [argName]: e.target.value,
                              },
                            })
                          }
                        />
                      </div>
                    );
                  },
                )}
              </div>
            </div>
          )}
        </>
      )}

      {/* API CALL / EXTERNAL — free-text URL + method */}
      {(config.tool_type === "api_call" || config.tool_type === "external") && (
        <>
          <div>
            <Label className="text-xs">Endpoint</Label>
            <Input
              className="mt-1 h-8 text-xs font-mono"
              placeholder="https://api.example.com/search"
              value={config.endpoint || ""}
              onChange={(e) => onUpdate({ endpoint: e.target.value })}
            />
          </div>
          <div>
            <Label className="text-xs">Method</Label>
            <Select
              value={config.method || "GET"}
              onValueChange={(v) => onUpdate({ method: v })}
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => (
                  <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}

      {config.tool_type === "db_query" && (
        <div>
          <Label className="text-xs">Query Template</Label>
          <Textarea
            className="mt-1 text-xs font-mono min-h-[60px]"
            placeholder="SELECT * FROM articles WHERE topic = $1"
            value={config.query || ""}
            onChange={(e) => onUpdate({ query: e.target.value })}
          />
        </div>
      )}
      {config.tool_type === "function" && (
        <div>
          <Label className="text-xs">Function Body</Label>
          <Textarea
            className="mt-1 text-xs font-mono min-h-[60px]"
            placeholder="// Custom function logic..."
            value={config.code || ""}
            onChange={(e) => onUpdate({ code: e.target.value })}
          />
        </div>
      )}

      {/* Parameters — the agent binds these to call-time values */}
      <div>
        <div className="flex items-center justify-between">
          <Label className="text-xs">Parameters</Label>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]" onClick={addParameter}>
            <Plus className="h-3 w-3 mr-0.5" />
            Add
          </Button>
        </div>
        <div className="mt-1 space-y-2">
          {(config.parameters || []).map((param, i) => (
            <div key={i} className="flex items-center gap-1">
              <Input
                className="h-7 text-[10px] flex-1"
                placeholder="name"
                value={param.name}
                onChange={(e) => updateParameter(i, { name: e.target.value })}
              />
              <Select
                value={param.type}
                onValueChange={(v) => updateParameter(i, { type: v })}
              >
                <SelectTrigger className="h-7 text-[10px] w-[72px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["string", "number", "boolean", "object", "array", "uuid", "date"].map((t) => (
                    <SelectItem key={t} value={t} className="text-[10px]">{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="ghost" size="icon"
                className="h-6 w-6 shrink-0"
                onClick={() => removeParameter(i)}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
