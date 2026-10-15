"use client";

import { use, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardDescription, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
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

interface Person {
  id: string;
  first_name: string;
  last_name: string;
  title: string | null;
  email: string;
  team_ids?: string[];
}

/** Who is in the team, and the way to take somebody in or let them go. A
 *  person may be in more than one team, so taking them in here leaves their
 *  other teams alone. */
function TeamMembers({ orgId, team }: { orgId: string; team: Team }) {
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState("");
  const { data: members = [] } = useQuery({
    queryKey: ["org", orgId, "teams", team.id, "members"],
    queryFn: () => api.get<Person[]>(`/api/orgs/${orgId}/teams/${team.id}/members`),
  });
  const { data: everyone = [] } = useQuery({
    queryKey: ["org", orgId, "people", "", "all"],
    queryFn: () => api.get<Person[]>(`/api/orgs/${orgId}/people?limit=200`),
  });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["org", orgId, "teams", team.id, "members"] });
    queryClient.invalidateQueries({ queryKey: ["org", orgId, "people"] });
    queryClient.invalidateQueries({ queryKey: ["org", orgId, "org-chart"] });
  };
  const add = useMutation({
    mutationFn: (person_id: string) => api.post(`/api/orgs/${orgId}/teams/${team.id}/members`, { person_id }),
    onSuccess: () => { setAdding(""); refresh(); },
  });
  const remove = useMutation({
    mutationFn: (person_id: string) => api.delete(`/api/orgs/${orgId}/teams/${team.id}/members/${person_id}`),
    onSuccess: refresh,
  });
  const inTeam = new Set(members.map((m) => m.id));
  const candidates = everyone.filter((p) => !inTeam.has(p.id));
  return (
    <div data-team-members="" className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {members.length} member{members.length !== 1 ? "s" : ""}
      </p>
      {members.length > 0 && (
        <ul className="space-y-1">
          {members.map((m) => (
            <li key={m.id} className="flex items-center justify-between rounded-md border px-2 py-1 text-sm">
              <span>
                {m.first_name} {m.last_name}
                {m.title && <span className="text-xs text-muted-foreground"> · {m.title}</span>}
              </span>
              <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground" title="Remove from this team"
                      onClick={() => remove.mutate(m.id)}>
                <X className="h-3.5 w-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {candidates.length > 0 && (
        <div className="flex items-center gap-2">
          <Select value={adding || "none"} onValueChange={(v) => setAdding(v === "none" ? "" : v)}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Add a person" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Add a person…</SelectItem>
              {candidates.map((p) => (
                <SelectItem key={p.id} value={p.id}>{p.first_name} {p.last_name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button size="sm" variant="outline" className="h-8" disabled={!adding || add.isPending} onClick={() => adding && add.mutate(adding)}>
            Add
          </Button>
        </div>
      )}
    </div>
  );
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
              <CardContent>
                <TeamMembers orgId={orgId} team={team} />
              </CardContent>
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
