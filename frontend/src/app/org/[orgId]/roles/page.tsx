"use client";

import { use, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Shield } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Role {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
  permissions: Record<string, unknown> | null;
  created_at: string;
}

function RoleForm({
  orgId,
  role,
  onClose,
}: {
  orgId: string;
  role?: Role;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    name: role?.name || "",
    description: role?.description || "",
  });

  const mutation = useMutation({
    mutationFn: (data: typeof form) =>
      role
        ? api.put(`/api/orgs/${orgId}/roles/${role.id}`, data)
        : api.post(`/api/orgs/${orgId}/roles`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "roles"] });
      onClose();
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate(form);
      }}
    >
      <div className="space-y-4 py-4">
        <div className="space-y-2">
          <Label>Name</Label>
          <Input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
        </div>
        <div className="space-y-2">
          <Label>Description</Label>
          <Input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </div>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving..." : role ? "Update" : "Create"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function RolesPage({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editRole, setEditRole] = useState<Role | undefined>();

  const { data: roles = [] } = useQuery({
    queryKey: ["org", orgId, "roles"],
    queryFn: () => api.get<Role[]>(`/api/orgs/${orgId}/roles`),
  });

  const deleteMutation = useMutation({
    mutationFn: (roleId: string) =>
      api.delete(`/api/orgs/${orgId}/roles/${roleId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "roles"] });
    },
  });

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">Roles</h1>
        <Button
          onClick={() => {
            setEditRole(undefined);
            setShowForm(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          Add Role
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {roles.map((role) => (
          <Card key={role.id}>
            <CardHeader>
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3">
                  <Shield className="mt-0.5 h-5 w-5 text-muted-foreground" />
                  <div>
                    <div className="flex items-center gap-2">
                      <CardTitle className="text-base">{role.name}</CardTitle>
                      {role.is_default && (
                        <Badge variant="secondary" className="text-xs">
                          Default
                        </Badge>
                      )}
                    </div>
                    {role.description && (
                      <CardDescription>{role.description}</CardDescription>
                    )}
                  </div>
                </div>
                {!role.is_default && (
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => {
                        setEditRole(role);
                        setShowForm(true);
                      }}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-destructive"
                      onClick={() => {
                        if (confirm("Delete this role?")) {
                          deleteMutation.mutate(role.id);
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </div>
            </CardHeader>
          </Card>
        ))}
      </div>

      <Dialog open={showForm} onOpenChange={(open) => !open && setShowForm(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editRole ? "Edit Role" : "Add Role"}</DialogTitle>
          </DialogHeader>
          <RoleForm
            orgId={orgId}
            role={editRole}
            onClose={() => setShowForm(false)}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function RolesPageWrapper({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <RolesPage orgId={orgId} />;
}
