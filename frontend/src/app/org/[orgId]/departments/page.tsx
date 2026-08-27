"use client";

import { use, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
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

interface Department {
  id: string;
  name: string;
  description: string | null;
  parent_id: string | null;
  created_at: string;
}

function DepartmentForm({
  orgId,
  dept,
  onClose,
}: {
  orgId: string;
  dept?: Department;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    name: dept?.name || "",
    description: dept?.description || "",
  });

  const mutation = useMutation({
    mutationFn: (data: typeof form) =>
      dept
        ? api.put(`/api/orgs/${orgId}/departments/${dept.id}`, data)
        : api.post(`/api/orgs/${orgId}/departments`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["org", orgId, "departments"],
      });
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
            onChange={(e) =>
              setForm({ ...form, description: e.target.value })
            }
          />
        </div>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving..." : dept ? "Update" : "Create"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function DepartmentsPage({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editDept, setEditDept] = useState<Department | undefined>();

  const { data: departments = [] } = useQuery({
    queryKey: ["org", orgId, "departments"],
    queryFn: () => api.get<Department[]>(`/api/orgs/${orgId}/departments`),
  });

  const deleteMutation = useMutation({
    mutationFn: (deptId: string) =>
      api.delete(`/api/orgs/${orgId}/departments/${deptId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["org", orgId, "departments"],
      });
    },
  });

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">Departments</h1>
        <Button
          onClick={() => {
            setEditDept(undefined);
            setShowForm(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          Add Department
        </Button>
      </div>

      {departments.length === 0 ? (
        <Card className="border-dashed">
          <CardHeader className="items-center text-center">
            <CardTitle>No departments yet</CardTitle>
            <CardDescription>
              Create departments to organize your team
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {departments.map((dept) => (
            <Card key={dept.id}>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-base">{dept.name}</CardTitle>
                    {dept.description && (
                      <CardDescription>{dept.description}</CardDescription>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => {
                        setEditDept(dept);
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
                        if (confirm("Delete this department?")) {
                          deleteMutation.mutate(dept.id);
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardHeader>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={showForm} onOpenChange={(open) => !open && setShowForm(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editDept ? "Edit Department" : "Add Department"}
            </DialogTitle>
          </DialogHeader>
          <DepartmentForm
            orgId={orgId}
            dept={editDept}
            onClose={() => setShowForm(false)}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function DepartmentsPageWrapper({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <DepartmentsPage orgId={orgId} />;
}
