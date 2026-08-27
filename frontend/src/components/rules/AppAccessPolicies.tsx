"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Loader2, Shield } from "lucide-react";
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
import { Separator } from "@/components/ui/separator";
import { AppRoleMapping } from "./AppRoleMapping";
import type { AccessPolicy } from "@/types/rules";

interface AppAccessPoliciesProps {
  projectId: string;
  orgId: string;
}

interface OrgRole {
  id: string;
  name: string;
}

interface OrgGroup {
  id: string;
  name: string;
}

interface Department {
  id: string;
  name: string;
}

export function AppAccessPolicies({ projectId, orgId }: AppAccessPoliciesProps) {
  const queryClient = useQueryClient();
  const [targetType, setTargetType] = useState<string>("role");
  const [targetId, setTargetId] = useState<string>("");
  const [accessLevel, setAccessLevel] = useState<string>("user");
  const [isAdding, setIsAdding] = useState(false);

  const { data: policies = [], isLoading } = useQuery({
    queryKey: ["project", projectId, "access-policies"],
    queryFn: () =>
      api.get<AccessPolicy[]>(`/api/projects/${projectId}/access-policies`),
  });

  const { data: roles = [] } = useQuery({
    queryKey: ["org", orgId, "roles"],
    queryFn: () => api.get<OrgRole[]>(`/api/orgs/${orgId}/roles`),
  });

  const { data: groups = [] } = useQuery({
    queryKey: ["org", orgId, "groups"],
    queryFn: () => api.get<OrgGroup[]>(`/api/orgs/${orgId}/groups`),
  });

  const { data: departments = [] } = useQuery({
    queryKey: ["org", orgId, "departments"],
    queryFn: () => api.get<Department[]>(`/api/orgs/${orgId}/departments`),
  });

  const getTargets = () => {
    switch (targetType) {
      case "role":
        return roles.map((r) => ({ id: r.id, name: r.name }));
      case "group":
        return groups.map((g) => ({ id: g.id, name: g.name }));
      case "department":
        return departments.map((d) => ({ id: d.id, name: d.name }));
      default:
        return [];
    }
  };

  const getTargetName = (policy: AccessPolicy): string => {
    switch (policy.target_type) {
      case "role":
        return roles.find((r) => r.id === policy.target_id)?.name || policy.target_id;
      case "group":
        return groups.find((g) => g.id === policy.target_id)?.name || policy.target_id;
      case "department":
        return departments.find((d) => d.id === policy.target_id)?.name || policy.target_id;
      default:
        return policy.target_id;
    }
  };

  const handleAdd = async () => {
    if (!targetId) return;
    setIsAdding(true);
    try {
      await api.post(`/api/projects/${projectId}/access-policies`, {
        target_type: targetType,
        target_id: targetId,
        access_level: accessLevel,
      });
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "access-policies"],
      });
      setTargetId("");
    } catch (err) {
      console.error("Failed to add policy:", err);
    } finally {
      setIsAdding(false);
    }
  };

  const handleDelete = async (policyId: string) => {
    try {
      await api.delete(
        `/api/projects/${projectId}/access-policies/${policyId}`,
      );
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "access-policies"],
      });
    } catch (err) {
      console.error("Failed to delete policy:", err);
    }
  };

  const targets = getTargets();

  const LEVEL_COLORS: Record<string, string> = {
    admin: "bg-purple-100 text-purple-700",
    user: "bg-blue-100 text-blue-700",
    none: "bg-gray-100 text-gray-500",
  };

  return (
    <div className="flex-1 overflow-auto p-4 space-y-6">
      {/* App Access Policies */}
      <div>
        <h3 className="text-sm font-semibold">App Access Policies</h3>
        <p className="text-xs text-muted-foreground mb-3">
          Control which org roles, groups, or departments can access this app.
        </p>

        {/* Add policy form */}
        <div className="flex items-center gap-2 mb-3">
          <Select value={targetType} onValueChange={setTargetType}>
            <SelectTrigger className="h-8 w-[120px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="role" className="text-xs">Role</SelectItem>
              <SelectItem value="group" className="text-xs">Group</SelectItem>
              <SelectItem value="department" className="text-xs">Department</SelectItem>
            </SelectContent>
          </Select>

          <Select value={targetId || "__none__"} onValueChange={(v) => setTargetId(v === "__none__" ? "" : v)}>
            <SelectTrigger className="h-8 w-[180px] text-xs">
              <SelectValue placeholder="Select..." />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__" className="text-xs">Select {targetType}...</SelectItem>
              {targets.map((t) => (
                <SelectItem key={t.id} value={t.id} className="text-xs">
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={accessLevel} onValueChange={setAccessLevel}>
            <SelectTrigger className="h-8 w-[100px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="admin" className="text-xs">Admin</SelectItem>
              <SelectItem value="user" className="text-xs">User</SelectItem>
              <SelectItem value="none" className="text-xs">None</SelectItem>
            </SelectContent>
          </Select>

          <Button
            size="sm"
            className="h-8 text-xs"
            onClick={handleAdd}
            disabled={!targetId || isAdding}
          >
            {isAdding ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <Plus className="mr-1 h-3 w-3" />
            )}
            Add
          </Button>
        </div>

        {/* Policies list */}
        {isLoading ? (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : policies.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <Shield className="h-6 w-6 text-muted-foreground mb-2" />
            <p className="text-xs text-muted-foreground">
              No access policies defined. All org members can access this app.
            </p>
          </div>
        ) : (
          <div className="space-y-1">
            {policies.map((policy) => (
              <div
                key={policy.id}
                className="flex items-center gap-2 rounded-md border p-2 text-xs"
              >
                <Badge variant="secondary" className="text-[10px]">
                  {policy.target_type}
                </Badge>
                <span className="font-medium">{getTargetName(policy)}</span>
                <Badge
                  variant="secondary"
                  className={`ml-auto text-[10px] ${LEVEL_COLORS[policy.access_level] || ""}`}
                >
                  {policy.access_level}
                </Badge>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  onClick={() => handleDelete(policy.id)}
                >
                  <Trash2 className="h-3 w-3 text-muted-foreground" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>

      <Separator />

      {/* Role Mapping */}
      <div>
        <h3 className="text-sm font-semibold">Role Mapping</h3>
        <p className="text-xs text-muted-foreground mb-3">
          Map org roles to app roles for the generated application.
        </p>
        <AppRoleMapping orgId={orgId} />
      </div>
    </div>
  );
}
