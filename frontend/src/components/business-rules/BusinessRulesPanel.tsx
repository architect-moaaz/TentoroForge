"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, ChevronLeft, Save, Trash2, Scale, Table2, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useProjectDataModel } from "@/hooks/useProjectDataModel";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { RuleEditor, emptyDraft, type ConditionActionDraft } from "./RuleEditor";
import { DecisionTableMode, emptyDecisionTable } from "./DecisionTableMode";
import { conditionToFeel } from "@/lib/condition-to-feel";
import {
  validateConditionActionRule,
  validateDecisionTableRule,
} from "@/lib/business-rule-validation";
import type { BusinessRule, ConditionActionConfig } from "@/types/business-rules";
import type { DecisionTableDefinition } from "@/types/decision";

interface BusinessRulesPanelProps {
  projectId: string;
  orgId: string;
}

interface DecisionTableDraft {
  id?: string;
  name: string;
  is_active: boolean;
  table: DecisionTableDefinition;
}

type Draft =
  | { kind: "condition_action"; ca: ConditionActionDraft }
  | { kind: "decision_table"; dt: DecisionTableDraft };

const BUSINESS_TYPES = new Set(["condition_action", "decision_table"]);

function toConditionDraft(rule: BusinessRule): ConditionActionDraft {
  const c = (rule.config ?? {}) as Partial<ConditionActionConfig>;
  return {
    id: rule.id,
    name: rule.name,
    model_name: rule.model_name,
    is_active: rule.is_active,
    config: {
      source: "manual",
      when: c.when ?? null,
      whenFeel: c.whenFeel ?? conditionToFeel(c.when ?? null),
      then: Array.isArray(c.then) ? c.then : [],
      otherwise: Array.isArray(c.otherwise) ? c.otherwise : [],
      scope: c.scope ?? "entity",
      salience: typeof c.salience === "number" ? c.salience : 0,
    },
  };
}

function toTableDraft(rule: BusinessRule): DecisionTableDraft {
  const c = (rule.config ?? {}) as { table?: DecisionTableDefinition };
  return {
    id: rule.id,
    name: rule.name,
    is_active: rule.is_active,
    table: c.table ?? emptyDecisionTable(),
  };
}

export function BusinessRulesPanel({ projectId }: BusinessRulesPanelProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);

  const rulesQuery = useQuery({
    queryKey: ["project", projectId, "business-rules"],
    queryFn: () => api.get<BusinessRule[]>(`/api/projects/${projectId}/rules`),
  });

  // Canonical data model (same /app-model source as the Data Model editor).
  const dataModel = useProjectDataModel(projectId);

  const rules = useMemo(
    () => (rulesQuery.data ?? []).filter((r) => BUSINESS_TYPES.has(r.rule_type)),
    [rulesQuery.data],
  );

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["project", projectId, "business-rules"] });

  const saveMutation = useMutation({
    mutationFn: async (d: Draft) => {
      const id = d.kind === "condition_action" ? d.ca.id : d.dt.id;
      const common =
        d.kind === "condition_action"
          ? {
              name: d.ca.name.trim(),
              model_name: d.ca.model_name,
              field_name: null,
              config: { ...d.ca.config, source: "manual" as const },
              is_active: d.ca.is_active,
            }
          : {
              name: d.dt.name.trim(),
              model_name: null,
              field_name: null,
              config: { source: "manual" as const, table: d.dt.table },
              is_active: d.dt.is_active,
            };
      if (id) {
        return api.put<BusinessRule>(`/api/projects/${projectId}/rules/${id}`, common);
      }
      return api.post<BusinessRule>(`/api/projects/${projectId}/rules`, {
        ...common,
        rule_type: d.kind,
      });
    },
    onSuccess: () => {
      toast.success("Rule saved");
      invalidate();
      setDraft(null);
    },
    onError: (e: Error) => toast.error(`Save failed: ${e.message}`),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/api/projects/${projectId}/rules/${id}`),
    onSuccess: () => {
      toast.success("Rule deleted");
      invalidate();
      setDraft(null);
    },
    onError: (e: Error) => toast.error(`Delete failed: ${e.message}`),
  });

  const draftName = draft?.kind === "condition_action" ? draft.ca.name : draft?.dt.name ?? "";
  const draftId = draft?.kind === "condition_action" ? draft.ca.id : draft?.dt.id;
  // Every action's required params must be filled before a rule can be saved —
  // otherwise a set_field with no field, or a rule with no actions, persists and
  // silently no-ops at runtime.
  const validationErrors =
    draft === null
      ? []
      : draft.kind === "condition_action"
        ? validateConditionActionRule(draft.ca.name, draft.ca.model_name, draft.ca.config)
        : validateDecisionTableRule(draft.dt.name, draft.dt.table);
  const canSave = draft !== null && validationErrors.length === 0 && !saveMutation.isPending;

  // ---- Editor view ----
  if (draft) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b bg-background px-4 py-2.5">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" className="h-7" onClick={() => setDraft(null)}>
              <ChevronLeft className="mr-1 h-4 w-4" />
              Rules
            </Button>
            <span className="text-sm font-medium">
              {draftId ? "Edit" : "New"}{" "}
              {draft.kind === "condition_action" ? "business rule" : "decision table"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {draftId && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-rose-500 hover:text-rose-600"
                onClick={() => draftId && deleteMutation.mutate(draftId)}
                disabled={deleteMutation.isPending}
              >
                <Trash2 className="mr-1 h-3.5 w-3.5" />
                Delete
              </Button>
            )}
            <Button
              size="sm"
              className="h-7"
              onClick={() => canSave && saveMutation.mutate(draft)}
              disabled={!canSave}
            >
              {saveMutation.isPending ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="mr-1 h-3.5 w-3.5" />
              )}
              Save
            </Button>
          </div>
        </div>
        {validationErrors.length > 0 && (
          <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 dark:border-amber-900/50 dark:bg-amber-950/30">
            <ul className="list-inside list-disc space-y-0.5 text-[11px] text-amber-800 dark:text-amber-300">
              {validationErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="flex-1 overflow-auto p-4">
          {draft.kind === "condition_action" ? (
            <RuleEditor
              draft={draft.ca}
              onChange={(ca) => setDraft({ kind: "condition_action", ca })}
              models={dataModel.models}
              getFields={dataModel.getFields}
              enumValuesForType={dataModel.enumValuesForType}
              hasModel={dataModel.hasModel}
            />
          ) : (
            <DecisionTableMode
              name={draft.dt.name}
              onNameChange={(name) => setDraft({ kind: "decision_table", dt: { ...draft.dt, name } })}
              table={draft.dt.table}
              onTableChange={(table) =>
                setDraft({ kind: "decision_table", dt: { ...draft.dt, table } })
              }
              appModel={dataModel.appModel}
              models={dataModel.models}
              getFields={dataModel.getFields}
              enumValuesForType={dataModel.enumValuesForType}
            />
          )}
        </div>
      </div>
    );
  }

  // ---- List view ----
  const newConditionAction = () => setDraft({ kind: "condition_action", ca: emptyDraft() });
  const newDecisionTable = () =>
    setDraft({
      kind: "decision_table",
      dt: { name: "", is_active: true, table: emptyDecisionTable() },
    });

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b bg-background px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Scale className="h-4 w-4 text-indigo-500" />
          <span className="text-sm font-medium">Business Rules</span>
          <span className="hidden text-xs text-muted-foreground md:inline">
            Condition → action rules &amp; decision tables, evaluated at request time
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-7" onClick={newDecisionTable}>
            <Table2 className="mr-1 h-3.5 w-3.5" />
            Decision table
          </Button>
          <Button size="sm" className="h-7" onClick={newConditionAction}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            New rule
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {rulesQuery.isLoading ? (
          <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading rules…
          </div>
        ) : rules.length === 0 ? (
          <div className="mx-auto max-w-md rounded-lg border border-dashed py-12 text-center">
            <Scale className="mx-auto h-8 w-8 text-muted-foreground/50" />
            <p className="mt-3 text-sm font-medium">No business rules yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Create a condition → action rule (“when amount &gt; 1000, require an approver”) or a
              decision table.
            </p>
            <div className="mt-4 flex justify-center gap-2">
              <Button size="sm" className="h-7" onClick={newConditionAction}>
                <Plus className="mr-1 h-3.5 w-3.5" />
                New rule
              </Button>
              <Button variant="outline" size="sm" className="h-7" onClick={newDecisionTable}>
                <Table2 className="mr-1 h-3.5 w-3.5" />
                Decision table
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {rules.map((rule) => {
              const isTable = rule.rule_type === "decision_table";
              const cfg = (rule.config ?? {}) as Partial<ConditionActionConfig> & {
                table?: DecisionTableDefinition;
              };
              const summary = isTable
                ? `decision table · ${cfg.table?.rules?.length ?? 0} rows · hit ${
                    cfg.table?.hitPolicy ?? "U"
                  }`
                : `${rule.model_name ? `${rule.model_name}: ` : ""}${cfg.whenFeel || "true"}`;
              // OWNED BY THE BLUEPRINT. Opening the editor for one of these
              // collects an edit with nowhere to land — no project_rules row
              // exists, so saving 409s. Not offered rather than offered and
              // refused.
              const owned = Boolean(
                (rule.config as { blueprintId?: string } | null)?.blueprintId,
              );
              return (
                <button
                  key={rule.id}
                  disabled={owned}
                  onClick={
                    owned
                      ? undefined
                      : () =>
                          setDraft(
                            isTable
                              ? { kind: "decision_table", dt: toTableDraft(rule) }
                              : {
                                  kind: "condition_action",
                                  ca: toConditionDraft(rule),
                                },
                          )
                  }
                  className={
                    owned
                      ? "flex w-full items-center justify-between rounded-md border bg-card px-3 py-2.5 text-left"
                      : "flex w-full items-center justify-between rounded-md border bg-card px-3 py-2.5 text-left transition-colors hover:bg-accent"
                  }
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      {isTable ? (
                        <Table2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      ) : (
                        <Scale className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      )}
                      <span className="truncate text-sm font-medium">{rule.name}</span>
                      {!rule.is_active && (
                        <Badge variant="secondary" className="text-[10px]">
                          inactive
                        </Badge>
                      )}
                      {owned && (
                        <Badge
                          variant="outline"
                          className="text-[10px] font-normal"
                          title="Defined in the Blueprint — ask Smith to change it"
                        >
                          Blueprint
                        </Badge>
                      )}
                    </div>
                    <p className="mt-0.5 truncate pl-5 font-mono text-[11px] text-muted-foreground">
                      {summary}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
