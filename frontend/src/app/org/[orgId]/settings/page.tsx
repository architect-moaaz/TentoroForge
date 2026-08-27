"use client";

import { use, useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, X, Mail } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Org {
  id: string;
  name: string;
  slug: string;
  logo_url: string | null;
}

interface OrgMember {
  id: string;
  user_id: string;
  email: string;
  name: string | null;
  role: string;
  joined_at: string;
}

function OrgSettings({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: org } = useQuery({
    queryKey: ["org", orgId],
    queryFn: () => api.get<Org>(`/api/orgs/${orgId}`),
  });

  const { data: members = [] } = useQuery({
    queryKey: ["org", orgId, "members"],
    queryFn: () => api.get<OrgMember[]>(`/api/orgs/${orgId}/members`),
  });

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [initialized, setInitialized] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");

  if (org && !initialized) {
    setName(org.name);
    setSlug(org.slug);
    setInitialized(true);
  }

  const mutation = useMutation({
    mutationFn: (data: { name: string; slug: string }) =>
      api.put(`/api/orgs/${orgId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId] });
    },
  });

  const logoMutation = useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return api.upload<Org>(`/api/orgs/${orgId}/logo`, formData);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId] });
    },
  });

  const inviteMutation = useMutation({
    mutationFn: (data: { email: string; role: string }) =>
      api.post(`/api/orgs/${orgId}/invite`, data),
    onSuccess: () => {
      setInviteEmail("");
      setInviteRole("member");
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "members"] });
    },
  });

  const handleLogoSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      logoMutation.mutate(file);
    }
  };

  return (
    <div className="p-8">
      <h1 className="mb-6 text-2xl font-semibold text-foreground">Settings</h1>

      <div className="max-w-lg space-y-6">
        {/* Organization Details */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Organization Details</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                mutation.mutate({ name, slug });
              }}
            >
              <div className="space-y-2">
                <Label>Name</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>Slug</Label>
                <Input value={slug} onChange={(e) => setSlug(e.target.value)} />
              </div>
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? "Saving..." : "Save Changes"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Logo Upload */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Organization Logo</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-4">
              {org?.logo_url ? (
                <div className="relative">
                  <img
                    src={org.logo_url}
                    alt="Organization logo"
                    className="h-16 w-16 rounded-md border object-cover"
                  />
                </div>
              ) : (
                <div className="flex h-16 w-16 items-center justify-center rounded-md border border-dashed bg-muted">
                  <Upload className="h-6 w-6 text-muted-foreground" />
                </div>
              )}
              <div className="space-y-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={handleLogoSelect}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={logoMutation.isPending}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {logoMutation.isPending ? "Uploading..." : "Upload Logo"}
                </Button>
                <p className="text-xs text-muted-foreground">
                  PNG, JPG, or SVG. Max 2MB.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Invite Members */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Invite Members</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="flex items-end gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (inviteEmail.trim()) {
                  inviteMutation.mutate({
                    email: inviteEmail.trim(),
                    role: inviteRole,
                  });
                }
              }}
            >
              <div className="flex-1 space-y-2">
                <Label>Email address</Label>
                <Input
                  type="email"
                  placeholder="colleague@example.com"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label>Role</Label>
                <Select value={inviteRole} onValueChange={setInviteRole}>
                  <SelectTrigger className="w-[120px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="member">Member</SelectItem>
                    <SelectItem value="admin">Admin</SelectItem>
                    <SelectItem value="owner">Owner</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button type="submit" disabled={inviteMutation.isPending}>
                <Mail className="mr-2 h-4 w-4" />
                {inviteMutation.isPending ? "Sending..." : "Invite"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Members List */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Members</CardTitle>
          </CardHeader>
          <CardContent>
            {members.length === 0 ? (
              <p className="text-sm text-muted-foreground">No members yet</p>
            ) : (
              <div className="space-y-3">
                {members.map((member) => (
                  <div
                    key={member.id}
                    className="flex items-center justify-between rounded-md border px-3 py-2"
                  >
                    <div>
                      <p className="text-sm font-medium">
                        {member.name || member.email}
                      </p>
                      {member.name && (
                        <p className="text-xs text-muted-foreground">
                          {member.email}
                        </p>
                      )}
                    </div>
                    <Badge
                      variant={member.role === "owner" ? "default" : "secondary"}
                    >
                      {member.role}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function SettingsPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <OrgSettings orgId={orgId} />;
}
