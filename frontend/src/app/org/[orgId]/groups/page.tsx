"use client";

import { use, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Users, Search, X, UserPlus } from "lucide-react";
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

interface Group {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
  created_at: string;
}

interface GroupMember {
  id: string;
  person_id: string;
  first_name: string;
  last_name: string;
  email: string;
  title: string | null;
}

interface Person {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  title: string | null;
}

function GroupForm({
  orgId,
  group,
  onClose,
}: {
  orgId: string;
  group?: Group;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    name: group?.name || "",
    description: group?.description || "",
  });

  const mutation = useMutation({
    mutationFn: (data: typeof form) =>
      group
        ? api.put(`/api/orgs/${orgId}/groups/${group.id}`, data)
        : api.post(`/api/orgs/${orgId}/groups`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "groups"] });
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
          {mutation.isPending ? "Saving..." : group ? "Update" : "Create"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function ManageMembersDialog({
  orgId,
  group,
  onClose,
}: {
  orgId: string;
  group: Group;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [memberSearch, setMemberSearch] = useState("");

  const { data: members = [] } = useQuery({
    queryKey: ["org", orgId, "groups", group.id, "members"],
    queryFn: () =>
      api.get<GroupMember[]>(
        `/api/orgs/${orgId}/groups/${group.id}/members`,
      ),
  });

  const { data: allPeople = [] } = useQuery({
    queryKey: ["org", orgId, "people", memberSearch],
    queryFn: () => {
      const params = new URLSearchParams();
      if (memberSearch) params.set("search", memberSearch);
      return api.get<Person[]>(
        `/api/orgs/${orgId}/people?${params.toString()}`,
      );
    },
  });

  const memberPersonIds = new Set(members.map((m) => m.person_id));

  const filteredPeople = allPeople.filter(
    (p) => !memberPersonIds.has(p.id),
  );

  const addMutation = useMutation({
    mutationFn: (personId: string) =>
      api.post(`/api/orgs/${orgId}/groups/${group.id}/members`, {
        person_id: personId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["org", orgId, "groups", group.id, "members"],
      });
      queryClient.invalidateQueries({
        queryKey: ["org", orgId, "groups"],
      });
    },
  });

  const removeMutation = useMutation({
    mutationFn: (memberId: string) =>
      api.delete(
        `/api/orgs/${orgId}/groups/${group.id}/members/${memberId}`,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["org", orgId, "groups", group.id, "members"],
      });
      queryClient.invalidateQueries({
        queryKey: ["org", orgId, "groups"],
      });
    },
  });

  return (
    <div className="space-y-6 py-4">
      {/* Current Members */}
      <div>
        <h4 className="mb-3 text-sm font-medium">
          Current Members ({members.length})
        </h4>
        {members.length === 0 ? (
          <p className="text-sm text-muted-foreground">No members in this group</p>
        ) : (
          <div className="max-h-48 space-y-2 overflow-y-auto">
            {members.map((member) => (
              <div
                key={member.id}
                className="flex items-center justify-between rounded-md border px-3 py-2"
              >
                <div>
                  <p className="text-sm font-medium">
                    {member.first_name} {member.last_name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {member.email}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-destructive"
                  disabled={removeMutation.isPending}
                  onClick={() => removeMutation.mutate(member.id)}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add Members */}
      <div>
        <h4 className="mb-3 text-sm font-medium">Add Members</h4>
        <div className="relative mb-3">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search people..."
            value={memberSearch}
            onChange={(e) => setMemberSearch(e.target.value)}
            className="pl-10"
          />
        </div>
        <div className="max-h-48 space-y-2 overflow-y-auto">
          {filteredPeople.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {memberSearch
                ? "No matching people found"
                : "All people are already members"}
            </p>
          ) : (
            filteredPeople.map((person) => (
              <div
                key={person.id}
                className="flex items-center justify-between rounded-md border px-3 py-2"
              >
                <div>
                  <p className="text-sm font-medium">
                    {person.first_name} {person.last_name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {person.email}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={addMutation.isPending}
                  onClick={() => addMutation.mutate(person.id)}
                >
                  <UserPlus className="mr-1 h-3 w-3" />
                  Add
                </Button>
              </div>
            ))
          )}
        </div>
      </div>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Close
        </Button>
      </DialogFooter>
    </div>
  );
}

function GroupsPage({ orgId }: { orgId: string }) {
  const [showForm, setShowForm] = useState(false);
  const [editGroup, setEditGroup] = useState<Group | undefined>();
  const [manageMembersGroup, setManageMembersGroup] = useState<
    Group | undefined
  >();

  const { data: groups = [] } = useQuery({
    queryKey: ["org", orgId, "groups"],
    queryFn: () => api.get<Group[]>(`/api/orgs/${orgId}/groups`),
  });

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">Groups</h1>
        <Button
          onClick={() => {
            setEditGroup(undefined);
            setShowForm(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          Add Group
        </Button>
      </div>

      {groups.length === 0 ? (
        <Card className="border-dashed">
          <CardHeader className="items-center text-center">
            <CardTitle>No groups yet</CardTitle>
            <CardDescription>
              Create groups for cross-functional teams
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {groups.map((group) => (
            <Card key={group.id}>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    <Users className="mt-0.5 h-5 w-5 text-muted-foreground" />
                    <div>
                      <CardTitle className="text-base">{group.name}</CardTitle>
                      {group.description && (
                        <CardDescription>{group.description}</CardDescription>
                      )}
                      <Badge variant="secondary" className="mt-2 text-xs">
                        {group.member_count} member
                        {group.member_count !== 1 ? "s" : ""}
                      </Badge>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      title="Manage Members"
                      onClick={() => setManageMembersGroup(group)}
                    >
                      <UserPlus className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => {
                        setEditGroup(group);
                        setShowForm(true);
                      }}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardHeader>
            </Card>
          ))}
        </div>
      )}

      {/* Create/Edit Group Dialog */}
      <Dialog
        open={showForm}
        onOpenChange={(open) => !open && setShowForm(false)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editGroup ? "Edit Group" : "Add Group"}
            </DialogTitle>
          </DialogHeader>
          <GroupForm
            orgId={orgId}
            group={editGroup}
            onClose={() => setShowForm(false)}
          />
        </DialogContent>
      </Dialog>

      {/* Manage Members Dialog */}
      <Dialog
        open={!!manageMembersGroup}
        onOpenChange={(open) => !open && setManageMembersGroup(undefined)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              Manage Members — {manageMembersGroup?.name}
            </DialogTitle>
          </DialogHeader>
          {manageMembersGroup && (
            <ManageMembersDialog
              orgId={orgId}
              group={manageMembersGroup}
              onClose={() => setManageMembersGroup(undefined)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function GroupsPageWrapper({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <GroupsPage orgId={orgId} />;
}
