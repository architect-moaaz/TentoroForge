"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RuleFormDialog } from "./RuleFormDialog";
import type { Rule } from "@/types/rules";
import type { AppModel } from "@/types/app-model";

/**
 * Record scope for one model: the `row_access` rules that decide which ROWS
 * each role reaches.
 *
 * This panel used to offer a closed list of scope kinds — own_department,
 * manager_chain, owner — held in `useState` and posted nowhere. Nothing in the
 * backend or the runtime had ever consumed those names, so the list was not
 * even a vocabulary the generated app could have honoured; adding a rule
 * changed a React array and the panel then rendered the array back, which is
 * indistinguishable from having saved it.
 *
 * What replaces them is not a longer list. `row_access` rules are stored
 * through the same rules API as every other rule, and their condition is
 * authored with the same visual builder — so "records in my department" is
 * `departmentId = user.departmentId` rather than an enum member somebody has
 * to teach the runtime about one scope at a time.
 *
 * The two semantics the data engine enforces are what this view is arranged
 * around, because neither is visible from a flat list of rules:
 *
 *   Grants UNION.  Rules on a model add up — a role reaches a row if ANY rule
 *                  granted to it admits that row. Narrowing a role's access
 *                  means editing its rule, never adding another one.
 *   Fail closed.   Once a model has any rule, a role that no rule addresses
 *                  reaches NO rows. That is a safe default and a confusing
 *                  one, so the roles in that position are named below rather
 *                  than left for someone to discover in production.
 */
interface RecordScopeEditorProps {
  projectId: string;
  orgId: string;
}

interface OrgRole {
  id: string;
  name: string;
}

/** The roles a rule grants to, or null when it grants to every role. */
function grantedRoles(rule: Rule): string[] | null {
  const roles = rule.config?.roles ?? [];
  return roles.length === 0 ? null : roles;
}

export function RecordScopeEditor({ projectId, orgId }: RecordScopeEditorProps) {
  const [selectedModel, setSelectedModel] = useState("");
  const [showDialog, setShowDialog] = useState(false);
  const [editingRule, setEditingRule] = useState<Rule | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const { data: appModel } = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
  });

  const { data: roles = [] } = useQuery({
    queryKey: ["org", orgId, "roles"],
    queryFn: () => api.get<OrgRole[]>(`/api/orgs/${orgId}/roles`),
  });

  // Only this model's row rules. Asking the server to filter keeps the list
  // honest when a project has hundreds of rules across every type.
  const {
    data: rules = [],
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["project", projectId, "rules", "row_access", selectedModel],
    queryFn: () =>
      api.get<Rule[]>(
        `/api/projects/${projectId}/rules?rule_type=row_access&model_name=${encodeURIComponent(selectedModel)}`,
      ),
    enabled: !!selectedModel,
  });

  const modelNames = appModel?.database?.tables?.map((t) => t.name) ?? [];

  useEffect(() => {
    if (modelNames.length > 0 && !selectedModel) {
      setSelectedModel(modelNames[0]);
    }
  }, [modelNames, selectedModel]);

  // A role no rule addresses reaches nothing — but only once the model has at
  // least one rule. A model with none is unrestricted, and warning there would
  // name every role in the org for a state that is not a problem.
  const unaddressed =
    rules.length === 0
      ? []
      : roles
          .map((r) => r.name)
          .filter(
            (name) =>
              !rules.some((rule) => {
                const granted = grantedRoles(rule);
                return granted === null || granted.includes(name);
              }),
          );

  const handleCreate = () => {
    setEditingRule(null);
    setShowDialog(true);
  };

  const handleEdit = (rule: Rule) => {
    setEditingRule(rule);
    setShowDialog(true);
  };

  const handleDelete = async (rule: Rule) => {
    setDeletingId(rule.id);
    setDeleteError(null);
    try {
      await api.delete(`/api/projects/${projectId}/rules/${rule.id}`);
      await refetch();
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete scope rule",
      );
    } finally {
      setDeletingId(null);
    }
  };

  const handleSaved = () => {
    refetch();
    setShowDialog(false);
    setEditingRule(null);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Select value={selectedModel} onValueChange={setSelectedModel}>
          <SelectTrigger className="h-8 w-[200px] text-xs">
            <SelectValue placeholder="Select model..." />
          </SelectTrigger>
          <SelectContent>
            {modelNames.map((m) => (
              <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto h-7 text-xs"
          onClick={handleCreate}
          disabled={!selectedModel}
          data-testid="scope-add"
        >
          <Plus className="mr-1 h-3 w-3" />
          Add Scope Rule
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-6 text-xs text-muted-foreground">
          <Loader2 className="mr-2 h-3 w-3 animate-spin" />
          Loading scope rules...
        </div>
      ) : error ? (
        <div className="flex flex-col items-center gap-2 py-6">
          <AlertCircle className="h-5 w-5 text-muted-foreground" />
          <p className="text-xs text-muted-foreground">
            Could not load scope rules
          </p>
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => refetch()}>
            <RefreshCw className="mr-1 h-3 w-3" />
            Retry
          </Button>
        </div>
      ) : rules.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted-foreground">
          No scope rules on {selectedModel || "this model"} — every role reads
          every row. The first rule you add starts restricting: from then on a
          role no rule names reads none.
        </p>
      ) : (
        <div className="space-y-2">
          {rules.map((rule) => {
            const granted = grantedRoles(rule);
            return (
              <div
                key={rule.id}
                data-testid={`scope-rule-${rule.id}`}
                className="cursor-pointer rounded-md border p-2 text-xs hover:bg-muted/30"
                onClick={() => handleEdit(rule)}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium">{rule.name}</span>
                  {!rule.is_active && (
                    <Badge variant="secondary" className="text-[10px]">
                      Inactive
                    </Badge>
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="ml-auto h-6 w-6"
                    data-testid={`scope-delete-${rule.id}`}
                    disabled={deletingId === rule.id}
                    onClick={(e) => {
                      // The row itself opens the editor; deleting from inside
                      // it must not also open the thing being deleted.
                      e.stopPropagation();
                      handleDelete(rule);
                    }}
                  >
                    {deletingId === rule.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3 text-muted-foreground" />
                    )}
                  </Button>
                </div>

                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <span className="text-muted-foreground">grants to</span>
                  {granted === null ? (
                    <Badge variant="outline" className="text-[10px]">
                      every role
                    </Badge>
                  ) : (
                    granted.map((name) => (
                      <Badge key={name} variant="default" className="text-[10px]">
                        {name}
                      </Badge>
                    ))
                  )}
                </div>

                <div className="mt-1.5 flex items-start gap-1.5">
                  <span className="shrink-0 text-muted-foreground">
                    the rows where
                  </span>
                  <code className="min-w-0 break-all text-[11px]">
                    {rule.config?.whenFeel || "true"}
                  </code>
                </div>
              </div>
            );
          })}

          <p className="pt-1 text-[11px] text-muted-foreground">
            Rules add up: a role reads a row if any rule granted to it admits
            that row. To narrow what a role reads, edit its rule — adding
            another one only ever widens it.
          </p>
        </div>
      )}

      {unaddressed.length > 0 && (
        <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <p>
            No rule names {unaddressed.join(", ")}, so{" "}
            {unaddressed.length === 1 ? "that role reads" : "those roles read"}{" "}
            no {selectedModel} rows at all. Give{" "}
            {unaddressed.length === 1 ? "it" : "them"} a rule — one with an
            empty condition reads every row.
          </p>
        </div>
      )}

      {deleteError && <p className="text-xs text-red-500">{deleteError}</p>}

      <RuleFormDialog
        open={showDialog}
        onOpenChange={(open) => {
          if (!open) {
            setShowDialog(false);
            setEditingRule(null);
          }
        }}
        projectId={projectId}
        orgId={orgId}
        rule={editingRule}
        modelNames={modelNames}
        defaultRuleType="row_access"
        defaultModelName={selectedModel}
        onSaved={handleSaved}
      />
    </div>
  );
}
