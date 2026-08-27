"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { RuleConfig } from "@/types/rules";

interface AccessControlRuleFormProps {
  orgId: string;
  modelNames: string[];
  config: RuleConfig;
  modelName: string;
  onConfigChange: (config: RuleConfig) => void;
  onModelChange: (model: string) => void;
}

interface OrgRole {
  id: string;
  name: string;
}

const ACTIONS = ["create", "read", "update", "delete"] as const;
type Action = (typeof ACTIONS)[number];
type Permission = "allow" | "deny";

export function AccessControlRuleForm({
  orgId,
  modelNames,
  config,
  modelName,
  onConfigChange,
  onModelChange,
}: AccessControlRuleFormProps) {
  const { data: roles = [] } = useQuery({
    queryKey: ["org", orgId, "roles"],
    queryFn: () => api.get<OrgRole[]>(`/api/orgs/${orgId}/roles`),
  });

  const actions = config.actions || {};

  const getPermission = (roleId: string, action: Action): Permission => {
    return actions[roleId]?.[action] || "allow";
  };

  const togglePermission = (roleId: string, action: Action) => {
    const current = getPermission(roleId, action);
    const next: Permission = current === "allow" ? "deny" : "allow";
    const rolePerms: Record<string, "allow" | "deny"> = {
      ...(actions[roleId] || {}),
      [action]: next,
    };
    onConfigChange({
      ...config,
      actions: { ...actions, [roleId]: rolePerms },
    });
  };

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-xs">Model</Label>
        <Select value={modelName} onValueChange={onModelChange}>
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue placeholder="Select model..." />
          </SelectTrigger>
          <SelectContent>
            {modelNames.map((m) => (
              <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label className="text-xs">Role x Action Matrix</Label>
        <div className="mt-2 overflow-auto rounded-md border">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/30">
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">Role</th>
                {ACTIONS.map((a) => (
                  <th key={a} className="px-3 py-2 text-center font-medium text-muted-foreground capitalize">
                    {a}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {roles.map((role) => (
                <tr key={role.id} className="border-b">
                  <td className="px-3 py-2 font-medium">{role.name}</td>
                  {ACTIONS.map((action) => {
                    const perm = getPermission(role.id, action);
                    return (
                      <td key={action} className="px-3 py-2 text-center">
                        <button
                          type="button"
                          className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                            perm === "allow"
                              ? "bg-green-100 text-green-700"
                              : "bg-red-100 text-red-700"
                          }`}
                          onClick={() => togglePermission(role.id, action)}
                        >
                          {perm}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
              {roles.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-4 text-center text-muted-foreground">
                    No org roles found. Create roles in org settings first.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
