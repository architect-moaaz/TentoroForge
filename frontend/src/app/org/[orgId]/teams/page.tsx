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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Team {
  id: string;
  name: string;
  description: string | null;
  department_id: string | null;
  created_at: string;
}

interface Department {
  id: string;
  name: string;
}

function TeamForm({
  orgId,
  team,
  departments,
  onClose,
}: {
  orgId: string;
  team?: Team;
  departments: Department[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    name: team?.name || "",
    description: team?.description || "",
    department_id: team?.department_id || "",
  });

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      team
        ? api.put(`/api/orgs/${orgId}/teams/${team.id}`, data)
        : api.post(`/api/orgs/${orgId}/teams`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "teams"] });
      onClose();
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate({
          name: form.name,
          description: form.description || null,
          department_id: form.department_id || null,
        });
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
        <div className="space-y-2">
          <Label>Department</Label>
          <Select
            value={form.department_id}
            onValueChange={(v) =>
              setForm({ ...form, department_id: v === "none" ? "" : v })
            }
          >
            <SelectTrigger>
              <SelectValue placeholder="Select department" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No department</SelectItem>
              {departments.map((d) => (
                <SelectItem key={d.id} value={d.id}>
                  {d.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving..." : team ? "Update" : "Create"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function TeamsPage({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editTeam, setEditTeam] = useState<Team | undefined>();

  const { data: teams = [] } = useQuery({
    queryKey: ["org", orgId, "teams"],
    queryFn: () => api.get<Team[]>(`/api/orgs/${orgId}/teams`),
  });

  const { data: departments = [] } = useQuery({
    queryKey: ["org", orgId, "departments"],
    queryFn: () => api.get<Department[]>(`/api/orgs/${orgId}/departments`),
  });

  const deptMap = Object.fromEntries(departments.map((d) => [d.id, d.name]));

  const deleteMutation = useMutation({
    mutationFn: (teamId: string) =>
      api.delete(`/api/orgs/${orgId}/teams/${teamId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "teams"] });
    },
  });

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">Teams</h1>
        <Button
          onClick={() => {
            setEditTeam(undefined);
            setShowForm(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          Add Team
        </Button>
      </div>

      {teams.length === 0 ? (
        <Card className="border-dashed">
          <CardHeader className="items-center text-center">
            <CardTitle>No teams yet</CardTitle>
            <CardDescription>Create teams within your departments</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {teams.map((team) => (
            <Card key={team.id}>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-base">{team.name}</CardTitle>
                    {team.description && (
                      <CardDescription>{team.description}</CardDescription>
                    )}
                    {team.department_id && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {deptMap[team.department_id]}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => {
                        setEditTeam(team);
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
                        if (confirm("Delete this team?")) {
                          deleteMutation.mutate(team.id);
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
            <DialogTitle>{editTeam ? "Edit Team" : "Add Team"}</DialogTitle>
          </DialogHeader>
          <TeamForm
            orgId={orgId}
            team={editTeam}
            departments={departments}
            onClose={() => setShowForm(false)}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function TeamsPageWrapper({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <TeamsPage orgId={orgId} />;
}
