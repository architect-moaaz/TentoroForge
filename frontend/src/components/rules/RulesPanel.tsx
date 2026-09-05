"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Shield,
  Filter,
  Loader2,
  AlertCircle,
  RefreshCw,
  Search,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRulesStore } from "@/stores/rules";
import { useChatStore } from "@/stores/chat";
import { RULE_TYPES, type Rule, type RuleType } from "@/types/rules";
import type { AppModel } from "@/types/app-model";
import { RuleFormDialog } from "./RuleFormDialog";
import { AccessSubPanel } from "./AccessSubPanel";
import { AppAccessPolicies } from "./AppAccessPolicies";
import { RuleCrossReferences } from "./RuleCrossReferences";

type SubTab = "rules" | "access" | "policies";

interface RulesPanelProps {
  projectId: string;
  orgId: string;
}

const TYPE_BADGE_COLORS: Record<RuleType, string> = {
  validation: "bg-amber-100 text-amber-700",
  access: "bg-blue-100 text-blue-700",
  row_access: "bg-sky-100 text-sky-700",
  business: "bg-green-100 text-green-700",
  computed: "bg-purple-100 text-purple-700",
  state_machine: "bg-rose-100 text-rose-700",
  trigger: "bg-orange-100 text-orange-700",
  content_moderation: "bg-red-100 text-red-700",
  similarity_check: "bg-teal-100 text-teal-700",
  ai_validation: "bg-violet-100 text-violet-700",
  ai_enrichment: "bg-cyan-100 text-cyan-700",
};

/**
 * Whether this rule is the Blueprint's rather than a hand-authored row.
 *
 * `config.blueprintId` is set by services/blueprint_to_editor.py for exactly
 * this question, so the answer travels with the record instead of costing a
 * second request.
 */
function fromBlueprint(rule: Rule): boolean {
  return Boolean((rule.config as { blueprintId?: string })?.blueprintId);
}

export function RulesPanel({ projectId, orgId }: RulesPanelProps) {
  const [subTab, setSubTab] = useState<SubTab>("rules");
  const [search, setSearch] = useState("");
  const [showDialog, setShowDialog] = useState(false);
  const [editingRule, setEditingRule] = useState<Rule | null>(null);

  const queryClient = useQueryClient();
  const filterType = useRulesStore((s) => s.filterType);
  const setFilterType = useRulesStore((s) => s.setFilterType);
  const filterModel = useRulesStore((s) => s.filterModel);
  const setFilterModel = useRulesStore((s) => s.setFilterModel);
  const setRules = useRulesStore((s) => s.setRules);
  const lastCommitHash = useChatStore((s) => s.lastCommitHash);

  // Fetch rules
  const {
    data: rules = [],
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["project", projectId, "rules", filterType, filterModel],
    queryFn: () => {
      let path = `/api/projects/${projectId}/rules`;
      const params = new URLSearchParams();
      if (filterType) params.set("rule_type", filterType);
      if (filterModel) params.set("model_name", filterModel);
      const qs = params.toString();
      return api.get<Rule[]>(qs ? `${path}?${qs}` : path);
    },
  });

  // Fetch app model for model names
  const { data: appModel } = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
  });

  useEffect(() => {
    // condition_action / decision_table rows belong to the Business Rules tab —
    // keep them out of the classic Rules store/list so they don't render with
    // raw badges or open a bodyless RuleFormDialog.
    setRules(
      rules.filter(
        (r) =>
          (r.rule_type as string) !== "condition_action" &&
          (r.rule_type as string) !== "decision_table",
      ),
    );
  }, [rules, setRules]);

  // Auto-refresh on commits
  useEffect(() => {
    if (lastCommitHash) {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "rules"],
      });
    }
  }, [lastCommitHash, projectId, queryClient]);

  const modelNames = appModel?.database?.tables?.map((t) => t.name) ?? [];

  const filteredRules = rules.filter((r) => {
    if ((r.rule_type as string) === "condition_action" || (r.rule_type as string) === "decision_table") return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        r.name.toLowerCase().includes(q) ||
        r.model_name?.toLowerCase().includes(q) ||
        r.rule_type.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const handleEdit = (rule: Rule) => {
    setEditingRule(rule);
    setShowDialog(true);
  };

  const handleCreate = () => {
    setEditingRule(null);
    setShowDialog(true);
  };

  const handleDialogClose = () => {
    setShowDialog(false);
    setEditingRule(null);
  };

  const handleSaved = () => {
    refetch();
    handleDialogClose();
  };

  const subTabs = [
    { id: "rules" as SubTab, label: "Rules" },
    { id: "access" as SubTab, label: "Access" },
    { id: "policies" as SubTab, label: "Access Policies" },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Sub-tab bar */}
      <div className="flex items-center gap-1 border-b px-3 py-1.5">
        {subTabs.map(({ id, label }) => (
          <Button
            key={id}
            variant={subTab === id ? "secondary" : "ghost"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => setSubTab(id)}
          >
            <Shield className="mr-1 h-3 w-3" />
            {label}
          </Button>
        ))}
      </div>

      {subTab === "rules" && (
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Toolbar */}
          <div className="flex items-center gap-2 border-b px-3 py-2">
            <div className="relative flex-1">
              <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="h-8 pl-7 text-xs"
                placeholder="Search rules..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <Select
              value={filterType ?? "all"}
              onValueChange={(v: string) => setFilterType(v === "all" ? null : (v as RuleType))}
            >
              <SelectTrigger className="h-8 w-[140px] text-xs">
                <Filter className="mr-1 h-3 w-3" />
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all" className="text-xs">All types</SelectItem>
                {RULE_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value} className="text-xs">
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={filterModel ?? "all"}
              onValueChange={(v: string) => setFilterModel(v === "all" ? null : v)}
            >
              <SelectTrigger className="h-8 w-[140px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all" className="text-xs">All models</SelectItem>
                {modelNames.map((m) => (
                  <SelectItem key={m} value={m} className="text-xs">
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button size="sm" className="h-8 text-xs" onClick={handleCreate}>
              <Plus className="mr-1 h-3 w-3" />
              Add Rule
            </Button>
          </div>

          {/* Rules table */}
          <div className="flex-1 overflow-auto">
            {isLoading ? (
              <div className="flex h-full items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                <span className="ml-2 text-sm text-muted-foreground">
                  Loading rules...
                </span>
              </div>
            ) : error ? (
              <div className="flex h-full flex-col items-center justify-center gap-3">
                <AlertCircle className="h-6 w-6 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">Could not load rules</p>
                <Button variant="outline" size="sm" onClick={() => refetch()}>
                  <RefreshCw className="mr-1 h-3 w-3" />
                  Retry
                </Button>
              </div>
            ) : filteredRules.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-3">
                <Shield className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  {search || filterType || filterModel
                    ? "No rules match your filters"
                    : "No rules yet"}
                </p>
                {!search && !filterType && !filterModel && (
                  <Button variant="outline" size="sm" onClick={handleCreate}>
                    <Plus className="mr-1 h-3 w-3" />
                    Create your first rule
                  </Button>
                )}
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/30 text-left">
                    <th className="px-3 py-2 font-medium text-muted-foreground">Name</th>
                    <th className="px-3 py-2 font-medium text-muted-foreground">Type</th>
                    <th className="px-3 py-2 font-medium text-muted-foreground">Attached To</th>
                    <th className="px-3 py-2 font-medium text-muted-foreground">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRules.map((rule) => (
                    <tr
                      key={rule.id}
                      // OWNED BY THE BLUEPRINT, SO NOT EDITABLE HERE. The row
                      // exists because the Blueprint declares it, not because
                      // anything wrote it to project_rules — so opening the
                      // dialog would collect an edit that has nowhere to go
                      // and fail on save. The backend refuses it with a 409;
                      // this stops it being offered in the first place.
                      className={
                        fromBlueprint(rule)
                          ? "border-b"
                          : "cursor-pointer border-b hover:bg-muted/30"
                      }
                      onClick={
                        fromBlueprint(rule)
                          ? undefined
                          : () => handleEdit(rule)
                      }
                    >
                      <td className="px-3 py-2 font-medium">
                        {rule.name}
                        {fromBlueprint(rule) && (
                          <Badge
                            variant="outline"
                            className="ml-2 text-[10px] font-normal"
                            title="Defined in the Blueprint — ask Smith to change it"
                          >
                            Blueprint
                          </Badge>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <Badge
                          variant="secondary"
                          className={`text-[10px] ${TYPE_BADGE_COLORS[rule.rule_type] || ""}`}
                        >
                          {RULE_TYPES.find((t) => t.value === rule.rule_type)?.label || rule.rule_type}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {rule.model_name || "—"}
                        {rule.field_name ? `.${rule.field_name}` : ""}
                      </td>
                      <td className="px-3 py-2">
                        <Badge
                          variant={rule.is_active ? "default" : "secondary"}
                          className="text-[10px]"
                        >
                          {rule.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* Cross-references sidebar when filter is active */}
      {subTab === "rules" && (filterModel || filterType) && (
        <div className="border-t px-3 py-2">
          <RuleCrossReferences
            rules={rules}
            appModel={appModel ?? null}
            selectedModel={filterModel}
            selectedField={null}
            selectedComponent={null}
            onRuleClick={handleEdit}
          />
        </div>
      )}

      {subTab === "access" && (
        <AccessSubPanel projectId={projectId} orgId={orgId} />
      )}

      {subTab === "policies" && (
        <AppAccessPolicies projectId={projectId} orgId={orgId} />
      )}

      {/* Rule form dialog */}
      <RuleFormDialog
        open={showDialog}
        onOpenChange={(open) => {
          if (!open) handleDialogClose();
        }}
        projectId={projectId}
        orgId={orgId}
        rule={editingRule}
        modelNames={modelNames}
        onSaved={handleSaved}
      />
    </div>
  );
}
