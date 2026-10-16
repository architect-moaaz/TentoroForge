"use client";

import { use, useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, X, Mail, Copy, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { describeInvite, type InviteOutcome } from "./invites";
import { ROLES, type MemberRole, badEmails, parseEmails } from "@/app/start/lib";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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
  user_id: string | null;
  email: string | null;
  name: string | null;
  role: string;
  /** "accepted" for a member, "pending" for somebody invited and not yet in. */
  invite_status: string;
  joined_at: string | null;
}


function InviteNotice({ outcome, onDismiss }: { outcome: InviteOutcome; onDismiss: () => void }) {
  const { text, link } = describeInvite(outcome);
  const [copied, setCopied] = useState(false);
  return (
    <div data-invite-notice="" className="mt-3 rounded-md border border-primary/30 bg-primary/5 p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <p>{text}</p>
        <Button type="button" variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={onDismiss} aria-label="Dismiss">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      {link && (
        <div className="mt-2 flex items-center gap-2">
          <code className="flex-1 truncate rounded bg-background px-2 py-1 text-xs">{link}</code>
          <Button type="button" size="sm" variant="outline" className="h-7"
                  onClick={() => { navigator.clipboard?.writeText(link).then(() => setCopied(true)).catch(() => undefined); }}>
            <Copy className="mr-1 h-3 w-3" />{copied ? "Copied" : "Copy"}
          </Button>
        </div>
      )}
    </div>
  );
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
  const [inviteRole, setInviteRole] = useState<MemberRole>("member");
  const [inviting, setInviting] = useState(false);
  const [sending, setSending] = useState(false);
  const [outcomes, setOutcomes] = useState<InviteOutcome[]>([]);
  const emailList = parseEmails(inviteEmail);
  const emailWarning = (() => { const bad = badEmails(emailList); return bad.length ? `Not an email address: ${bad.join(", ")}` : ""; })();
  // What the last invitation did: joined at once, emailed, or an address to pass on.
  const [invited, setInvited] = useState<InviteOutcome | null>(null);

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

  async function sendInvitations() {
    if (!emailList.length || emailWarning) return;
    setSending(true);
    const got: InviteOutcome[] = [];
    for (const email of emailList) {
      try { got.push(await api.post<InviteOutcome>(`/api/orgs/${orgId}/invite`, { email, role: inviteRole })); }
      catch (e) { got.push({ id: "", invite_email: `${email} — ${e instanceof Error ? e.message : "not invited"}`, role: inviteRole, invite_status: "failed", joined: false, emailed: false, invite_url: "" }); }
    }
    setOutcomes(got);
    setSending(false);
    setInviteEmail("");
    queryClient.invalidateQueries({ queryKey: ["org", orgId, "members"] });
  }
  const resendMutation = useMutation({
    mutationFn: (inviteId: string) => api.post<InviteOutcome>(`/api/orgs/${orgId}/invite/${inviteId}/resend`),
    onSuccess: (outcome) => setInvited(outcome),
  });
  const cancelMutation = useMutation({
    mutationFn: (inviteId: string) => api.delete(`/api/orgs/${orgId}/invite/${inviteId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "members"] }),
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

        {/* Invite Members — a dialog, like the one on the Members page people know:
            several addresses in one box, a role with what it allows beside it. */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Invite Members</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">Somebody with a Forge account joins at once; anyone else is sent the sign-up address.</p>
            </div>
            <Button type="button" onClick={() => { setOutcomes([]); setInviting(true); }}>
              <Mail className="mr-2 h-4 w-4" />Invite
            </Button>
          </CardHeader>
          {(invited || outcomes.length > 0) && (
            <CardContent>
              {invited && <InviteNotice outcome={invited} onDismiss={() => setInvited(null)} />}
              {outcomes.map((o, i) => (
                <InviteNotice key={`${o.invite_email}-${i}`} outcome={o} onDismiss={() => setOutcomes((all) => all.filter((_, j) => j !== i))} />
              ))}
            </CardContent>
          )}
        </Card>

        <Dialog open={inviting} onOpenChange={(open) => !open && setInviting(false)}>
          <DialogContent data-invite-dialog="">
            <DialogHeader>
              <DialogTitle>Invite a member</DialogTitle>
              <DialogDescription>Separate several emails with a comma.</DialogDescription>
            </DialogHeader>
            <div className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="invite-emails">Email</Label>
                <Input id="invite-emails" type="text" autoFocus placeholder="colleague@example.com, another@example.com"
                       value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} aria-invalid={Boolean(emailWarning)} />
                {emailWarning && <p className="text-sm text-amber-700">{emailWarning}</p>}
              </div>
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Role</legend>
                {ROLES.map((r) => (
                  <label key={r.value} className="flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2 text-sm has-[:checked]:border-primary">
                    <input type="radio" name="invite-role" className="mt-1 accent-primary" checked={inviteRole === r.value} onChange={() => setInviteRole(r.value)} />
                    <span><span className="font-medium">{r.title}</span><span className="block text-muted-foreground">{r.hint}</span></span>
                  </label>
                ))}
              </fieldset>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setInviting(false)}>Cancel</Button>
              <Button type="button" disabled={sending || !emailList.length || Boolean(emailWarning)} onClick={async () => { await sendInvitations(); setInviting(false); }}>
                {sending ? "Sending…" : emailList.length > 1 ? `Send ${emailList.length} invitations` : "Send invitation"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

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
                {members.map((member) => {
                  const pending = member.invite_status === "pending";
                  return (
                  <div
                    key={member.id}
                    data-member-row={pending ? "invited" : "member"}
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
                      {pending && (
                        <p className="text-xs text-muted-foreground">Invited · not signed up yet</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {pending && (
                        <>
                          <Button variant="ghost" size="icon" className="h-7 w-7" title="Send the invitation again"
                                  onClick={() => resendMutation.mutate(member.id)}>
                            <RefreshCw className="h-3.5 w-3.5" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" title="Withdraw the invitation"
                                  onClick={() => { if (confirm("Withdraw this invitation?")) cancelMutation.mutate(member.id); }}>
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </>
                      )}
                      <Badge variant={pending ? "outline" : member.role === "owner" ? "default" : "secondary"}>
                        {pending ? `invited as ${member.role}` : member.role}
                      </Badge>
                    </div>
                  </div>
                  );
                })}
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
