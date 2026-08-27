"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AppModel } from "@/types/app-model";

interface RecordScopeEditorProps {
  projectId: string;
  orgId: string;
}

interface OrgRole {
  id: string;
  name: string;
}

interface ScopeRule {
  roleId: string;
  roleName: string;
  scopeType: string;
  scopeColumn: string;
}

const SCOPE_TYPES = [
  { value: "unrestricted", label: "Unrestricted" },
  { value: "own_department", label: "Own Department" },
  { value: "department_sub", label: "Department + Subordinates" },
  { value: "own_team", label: "Own Team" },
  { value: "owner", label: "Owner Only" },
  { value: "manager_chain", label: "Manager Chain" },
];

export function RecordScopeEditor({ projectId, orgId }: RecordScopeEditorProps) {
  const [selectedModel, setSelectedModel] = useState("");
  const [scopeRules, setScopeRules] = useState<ScopeRule[]>([]);

  const { data: appModel } = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
  });

  const { data: roles = [] } = useQuery({
    queryKey: ["org", orgId, "roles"],
    queryFn: () => api.get<OrgRole[]>(`/api/orgs/${orgId}/roles`),
  });

  const modelNames = appModel?.database?.tables?.map((t) => t.name) ?? [];
  const fieldNames =
    appModel?.database?.tables
      ?.find((t) => t.name === selectedModel)
      ?.columns?.map((c) => c.name) ?? [];

  useEffect(() => {
    if (modelNames.length > 0 && !selectedModel) {
      setSelectedModel(modelNames[0]);
    }
  }, [modelNames, selectedModel]);

  const addScopeRule = () => {
    if (roles.length === 0) return;
    setScopeRules([
      ...scopeRules,
      {
        roleId: roles[0].id,
        roleName: roles[0].name,
        scopeType: "unrestricted",
        scopeColumn: "",
      },
    ]);
  };

  const updateScopeRule = (index: number, updates: Partial<ScopeRule>) => {
    const updated = [...scopeRules];
    updated[index] = { ...updated[index], ...updates };
    setScopeRules(updated);
  };

  const removeScopeRule = (index: number) => {
    setScopeRules(scopeRules.filter((_, i) => i !== index));
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
          onClick={addScopeRule}
          disabled={roles.length === 0}
        >
          <Plus className="mr-1 h-3 w-3" />
          Add Scope Rule
        </Button>
      </div>

      {scopeRules.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted-foreground">
          No record scope rules defined. All roles have unrestricted access to all records.
        </p>
      ) : (
        <div className="space-y-2">
          {scopeRules.map((rule, i) => (
            <div
              key={i}
              className="flex items-center gap-2 rounded-md border p-2 text-xs"
            >
              <Select
                value={rule.roleId}
                onValueChange={(v) => {
                  const role = roles.find((r) => r.id === v);
                  updateScopeRule(i, {
                    roleId: v,
                    roleName: role?.name || "",
                  });
                }}
              >
                <SelectTrigger className="h-7 w-[130px] text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((r) => (
                    <SelectItem key={r.id} value={r.id} className="text-xs">
                      {r.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <span className="text-muted-foreground">can see</span>

              <Select
                value={rule.scopeType}
                onValueChange={(v) => updateScopeRule(i, { scopeType: v })}
              >
                <SelectTrigger className="h-7 w-[170px] text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SCOPE_TYPES.map((s) => (
                    <SelectItem key={s.value} value={s.value} className="text-xs">
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {rule.scopeType !== "unrestricted" && rule.scopeType !== "owner" && (
                <>
                  <span className="text-muted-foreground">via</span>
                  <Select
                    value={rule.scopeColumn || "__none__"}
                    onValueChange={(v) =>
                      updateScopeRule(i, { scopeColumn: v === "__none__" ? "" : v })
                    }
                  >
                    <SelectTrigger className="h-7 w-[130px] text-xs">
                      <SelectValue placeholder="Column..." />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__" className="text-xs">Select column...</SelectItem>
                      {fieldNames.map((f) => (
                        <SelectItem key={f} value={f} className="text-xs">{f}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </>
              )}

              <Button
                variant="ghost"
                size="icon"
                className="ml-auto h-6 w-6"
                onClick={() => removeScopeRule(i)}
              >
                <Trash2 className="h-3 w-3 text-muted-foreground" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
