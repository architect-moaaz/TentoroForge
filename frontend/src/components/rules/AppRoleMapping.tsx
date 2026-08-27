"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2, ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface AppRoleMappingProps {
  orgId: string;
}

interface OrgRole {
  id: string;
  name: string;
}

interface RoleMapping {
  orgRoleId: string;
  orgRoleName: string;
  appRole: string;
}

export function AppRoleMapping({ orgId }: AppRoleMappingProps) {
  const [mappings, setMappings] = useState<RoleMapping[]>([]);
  const [customAppRoles, setCustomAppRoles] = useState<string[]>([]);
  const [newAppRole, setNewAppRole] = useState("");

  const { data: orgRoles = [] } = useQuery({
    queryKey: ["org", orgId, "roles"],
    queryFn: () => api.get<OrgRole[]>(`/api/orgs/${orgId}/roles`),
  });

  // Auto-suggested app roles from org roles
  const suggestedAppRoles = [
    ...orgRoles.map((r) => r.name),
    "admin",
    "user",
    "viewer",
    ...customAppRoles,
  ];
  const uniqueAppRoles = [...new Set(suggestedAppRoles)];

  const addMapping = (orgRole: OrgRole) => {
    if (mappings.some((m) => m.orgRoleId === orgRole.id)) return;
    setMappings([
      ...mappings,
      {
        orgRoleId: orgRole.id,
        orgRoleName: orgRole.name,
        appRole: orgRole.name.toLowerCase(),
      },
    ]);
  };

  const updateMapping = (index: number, appRole: string) => {
    const updated = [...mappings];
    updated[index] = { ...updated[index], appRole };
    setMappings(updated);
  };

  const removeMapping = (index: number) => {
    setMappings(mappings.filter((_, i) => i !== index));
  };

  const addCustomAppRole = () => {
    const name = newAppRole.trim().toLowerCase();
    if (!name || customAppRoles.includes(name)) return;
    setCustomAppRoles([...customAppRoles, name]);
    setNewAppRole("");
  };

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-xs font-semibold">App Roles</Label>
        <p className="text-[10px] text-muted-foreground mb-2">
          Custom roles for the generated application.
        </p>
        <div className="flex flex-wrap gap-1 mb-2">
          {uniqueAppRoles.map((r) => (
            <span
              key={r}
              className="inline-flex items-center rounded-full border bg-muted/30 px-2 py-0.5 text-xs"
            >
              {r}
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <Input
            className="h-7 flex-1 text-xs"
            placeholder="New app role..."
            value={newAppRole}
            onChange={(e) => setNewAppRole(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addCustomAppRole()}
          />
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={addCustomAppRole}
          >
            <Plus className="h-3 w-3" />
          </Button>
        </div>
      </div>

      <div>
        <Label className="text-xs font-semibold">Role Mappings</Label>
        <p className="text-[10px] text-muted-foreground mb-2">
          Map org roles to app roles. Users will inherit app permissions from their org role.
        </p>

        <div className="space-y-2">
          {mappings.map((mapping, i) => (
            <div
              key={mapping.orgRoleId}
              className="flex items-center gap-2 rounded-md border p-2 text-xs"
            >
              <span className="font-medium w-[120px] truncate">
                {mapping.orgRoleName}
              </span>
              <ArrowRight className="h-3 w-3 text-muted-foreground shrink-0" />
              <Input
                className="h-7 flex-1 text-xs"
                value={mapping.appRole}
                onChange={(e) => updateMapping(i, e.target.value)}
                list={`app-roles-${i}`}
              />
              <datalist id={`app-roles-${i}`}>
                {uniqueAppRoles.map((r) => (
                  <option key={r} value={r} />
                ))}
              </datalist>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0"
                onClick={() => removeMapping(i)}
              >
                <Trash2 className="h-3 w-3 text-muted-foreground" />
              </Button>
            </div>
          ))}
        </div>

        {/* Unmapped org roles */}
        {orgRoles.filter((r) => !mappings.some((m) => m.orgRoleId === r.id)).length > 0 && (
          <div className="mt-3">
            <p className="text-[10px] text-muted-foreground mb-1">
              Unmapped org roles (click to add):
            </p>
            <div className="flex flex-wrap gap-1">
              {orgRoles
                .filter((r) => !mappings.some((m) => m.orgRoleId === r.id))
                .map((role) => (
                  <button
                    key={role.id}
                    type="button"
                    className="rounded-md border px-2 py-0.5 text-xs hover:bg-muted/50"
                    onClick={() => addMapping(role)}
                  >
                    <Plus className="mr-1 inline h-2.5 w-2.5" />
                    {role.name}
                  </button>
                ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
