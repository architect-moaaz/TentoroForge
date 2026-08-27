"use client";

import { use, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Pencil, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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

interface Person {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  title: string | null;
  department_id: string | null;
  team_id: string | null;
  is_active: boolean;
  created_at: string;
}

interface Department {
  id: string;
  name: string;
}

interface Team {
  id: string;
  name: string;
  department_id: string | null;
}

function PersonForm({
  orgId,
  person,
  departments,
  teams,
  onClose,
}: {
  orgId: string;
  person?: Person;
  departments: Department[];
  teams: Team[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    email: person?.email || "",
    first_name: person?.first_name || "",
    last_name: person?.last_name || "",
    title: person?.title || "",
    department_id: person?.department_id || "",
    team_id: person?.team_id || "",
  });

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      person
        ? api.put(`/api/orgs/${orgId}/people/${person.id}`, data)
        : api.post(`/api/orgs/${orgId}/people`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "people"] });
      onClose();
    },
  });

  // Filter teams by selected department (if any)
  const filteredTeams = form.department_id
    ? teams.filter(
        (t) => t.department_id === form.department_id || !t.department_id,
      )
    : teams;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate({
          email: form.email,
          first_name: form.first_name,
          last_name: form.last_name,
          title: form.title || null,
          department_id: form.department_id || null,
          team_id: form.team_id || null,
        });
      }}
    >
      <div className="space-y-4 py-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>First name</Label>
            <Input
              value={form.first_name}
              onChange={(e) =>
                setForm({ ...form, first_name: e.target.value })
              }
              required
            />
          </div>
          <div className="space-y-2">
            <Label>Last name</Label>
            <Input
              value={form.last_name}
              onChange={(e) =>
                setForm({ ...form, last_name: e.target.value })
              }
              required
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label>Email</Label>
          <Input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            required
          />
        </div>
        <div className="space-y-2">
          <Label>Title</Label>
          <Input
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="e.g. Software Engineer"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Department</Label>
            <Select
              value={form.department_id}
              onValueChange={(v) =>
                setForm({
                  ...form,
                  department_id: v === "none" ? "" : v,
                  // Reset team if department changes and team doesn't belong
                  team_id:
                    v === "none"
                      ? form.team_id
                      : teams.find((t) => t.id === form.team_id)
                            ?.department_id === v ||
                          !teams.find((t) => t.id === form.team_id)
                            ?.department_id
                        ? form.team_id
                        : "",
                })
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
          <div className="space-y-2">
            <Label>Team</Label>
            <Select
              value={form.team_id}
              onValueChange={(v) =>
                setForm({ ...form, team_id: v === "none" ? "" : v })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="Select team" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No team</SelectItem>
                {filteredTeams.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending
            ? "Saving..."
            : person
              ? "Update"
              : "Add Person"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function PeopleDirectory({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editPerson, setEditPerson] = useState<Person | undefined>();

  const { data: people = [] } = useQuery({
    queryKey: ["org", orgId, "people", search],
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      return api.get<Person[]>(
        `/api/orgs/${orgId}/people?${params.toString()}`,
      );
    },
  });

  const { data: departments = [] } = useQuery({
    queryKey: ["org", orgId, "departments"],
    queryFn: () => api.get<Department[]>(`/api/orgs/${orgId}/departments`),
  });

  const { data: teams = [] } = useQuery({
    queryKey: ["org", orgId, "teams"],
    queryFn: () => api.get<Team[]>(`/api/orgs/${orgId}/teams`),
  });

  const deptMap = Object.fromEntries(departments.map((d) => [d.id, d.name]));
  const teamMap = Object.fromEntries(teams.map((t) => [t.id, t.name]));

  const deleteMutation = useMutation({
    mutationFn: (personId: string) =>
      api.delete(`/api/orgs/${orgId}/people/${personId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "people"] });
    },
  });

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">People</h1>
        <Button
          onClick={() => {
            setEditPerson(undefined);
            setShowForm(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          Add Person
        </Button>
      </div>

      <div className="mb-4 flex items-center gap-2">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search by name or email..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10"
          />
        </div>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Department</TableHead>
              <TableHead>Team</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-[100px]">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {people.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="py-8 text-center text-muted-foreground"
                >
                  No people found
                </TableCell>
              </TableRow>
            ) : (
              people.map((person) => (
                <TableRow key={person.id}>
                  <TableCell className="font-medium">
                    {person.first_name} {person.last_name}
                  </TableCell>
                  <TableCell>{person.email}</TableCell>
                  <TableCell>{person.title || "\u2014"}</TableCell>
                  <TableCell>
                    {person.department_id
                      ? deptMap[person.department_id] || "\u2014"
                      : "\u2014"}
                  </TableCell>
                  <TableCell>
                    {person.team_id ? teamMap[person.team_id] || "\u2014" : "\u2014"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={person.is_active ? "default" : "secondary"}>
                      {person.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => {
                          setEditPerson(person);
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
                          if (confirm("Delete this person?")) {
                            deleteMutation.mutate(person.id);
                          }
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog
        open={showForm}
        onOpenChange={(open) => {
          if (!open) setShowForm(false);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editPerson ? "Edit Person" : "Add Person"}
            </DialogTitle>
          </DialogHeader>
          <PersonForm
            orgId={orgId}
            person={editPerson}
            departments={departments}
            teams={teams}
            onClose={() => setShowForm(false)}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function PeoplePage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <PeopleDirectory orgId={orgId} />;
}
