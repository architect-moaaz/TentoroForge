"use client";

/**
 * /org/[orgId]/settings — General: the organisation itself and who is in it.
 *
 * Two cards: the organisation's identity (mark, name, address) with a save
 * that only lights up when something changed, and the people — members with
 * their role said in one line, invitations still waiting with resend and
 * withdraw, and an Invite dialog that takes several emails, explains each
 * role before it is chosen, and says per address what happened (joined at
 * once, emailed, or an address to pass on when no mail service is set up).
 */

import { use, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Building2, Copy, Mail, RefreshCw, Upload, Users, X as XIcon } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ROLES, type MemberRole, badEmails, parseEmails, slugProblem } from "@/app/start/lib";
import { describeInvite, type InviteOutcome } from "./invites";

interface Org { id: string; name: string; slug: string; logo_url: string | null }
interface OrgMember {
  id: string; user_id: string | null; email: string | null; name: string | null;
  role: string; invite_status: string; joined_at: string | null; created_at: string | null;
}

const ROLE_STYLE: Record<string, string> = {
  owner: "bg-slate-900 text-white dark:bg-white dark:text-slate-900",
  admin: "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20 dark:bg-blue-950/40 dark:text-blue-300",
  member: "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-500/20 dark:bg-slate-800 dark:text-slate-200",
};

function initials(name: string | null, email: string | null): string {
  const base = (name || email || "?").trim();
  const parts = base.split(/[\s@._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : base.slice(0, 2)).toUpperCase();
}
function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** What an invitation did, with the address to pass on when nobody was emailed. */
function InviteNotice({ outcome, onDismiss }: { outcome: InviteOutcome; onDismiss: () => void }) {
  const { text, link } = describeInvite(outcome);
  const [copied, setCopied] = useState(false);
  return (
    <div data-invite-notice="" className="rounded-md border border-primary/30 bg-primary/5 p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <p>{text}</p>
        <Button type="button" variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={onDismiss} aria-label="Dismiss"><XIcon className="h-3.5 w-3.5" /></Button>
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
  const { data: org } = useQuery({ queryKey: ["org", orgId], queryFn: () => api.get<Org>(`/api/orgs/${orgId}`) });
  const { data: members = [], isLoading: membersLoading } = useQuery({
    queryKey: ["org", orgId, "members"], queryFn: () => api.get<OrgMember[]>(`/api/orgs/${orgId}/members`),
  });

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  useEffect(() => { if (org) { setName(org.name); setSlug(org.slug); } }, [org]);
  const changed = Boolean(org) && (name.trim() !== org?.name || slug !== org?.slug);
  const slugWarning = useMemo(() => (org ? slugProblem(slug) : ""), [slug, org]);

  const save = useMutation({
    mutationFn: (data: { name: string; slug: string }) => api.put<Org>(`/api/orgs/${orgId}`, data),
    onSuccess: () => { toast.success("Organisation saved."); queryClient.invalidateQueries({ queryKey: ["org", orgId] }); },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Could not save."),
  });
  const logo = useMutation({
    mutationFn: (file: File) => { const fd = new FormData(); fd.append("file", file); return api.upload<Org>(`/api/orgs/${orgId}/logo`, fd); },
    onSuccess: () => { toast.success("Logo updated."); queryClient.invalidateQueries({ queryKey: ["org", orgId] }); },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Could not upload the logo."),
  });
  const refreshMembers = () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "members"] });
  const [outcomes, setOutcomes] = useState<InviteOutcome[]>([]);
  const resend = useMutation({
    mutationFn: (inviteId: string) => api.post<InviteOutcome>(`/api/orgs/${orgId}/invite/${inviteId}/resend`),
    onSuccess: (outcome) => setOutcomes((all) => [outcome, ...all]),
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Could not resend it."),
  });
  const withdraw = useMutation({
    mutationFn: (inviteId: string) => api.delete(`/api/orgs/${orgId}/invite/${inviteId}`),
    onSuccess: () => { toast.success("Invitation withdrawn."); refreshMembers(); },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Could not withdraw it."),
  });
  const [inviting, setInviting] = useState(false);

  const accepted = members.filter((m) => m.invite_status === "accepted");
  const pending = members.filter((m) => m.invite_status === "pending");
  const card = "rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900";

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight"><Building2 className="h-6 w-6" /> General</h1>
        <p className="mt-2 max-w-2xl text-[15px] text-muted-foreground">The organisation itself, and who is in it.</p>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <section className={`${card} p-6`} aria-label="Organisation">
          <h2 className="text-base font-semibold">Organisation</h2>
          <p className="mt-1 text-sm text-muted-foreground">The name people see and the address the workspace lives at.</p>
          <form className="mt-5 space-y-5" onSubmit={(e) => { e.preventDefault(); if (!slugWarning && changed) save.mutate({ name: name.trim(), slug }); }}>
            <div className="flex items-center gap-4">
              {org?.logo_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={org.logo_url} alt="Organisation logo" className="h-16 w-16 rounded-xl border object-cover" />
              ) : (
                <div className="grid h-16 w-16 place-items-center rounded-xl border border-dashed bg-muted text-xl font-semibold text-muted-foreground">{org ? initials(org.name, null) : ""}</div>
              )}
              <div className="space-y-1.5">
                <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) logo.mutate(f); }} />
                <Button type="button" variant="outline" size="sm" disabled={logo.isPending} onClick={() => fileInputRef.current?.click()}>
                  <Upload className="mr-2 h-4 w-4" />{logo.isPending ? "Uploading…" : org?.logo_url ? "Replace logo" : "Upload logo"}
                </Button>
                <p className="text-xs text-muted-foreground">PNG, JPG or SVG, up to 2 MB. Shown in the rail of every app you build.</p>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="org-name">Name</Label>
              <Input id="org-name" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="org-slug">Address</Label>
              <div className="flex items-center rounded-md border border-input bg-background focus-within:ring-2 focus-within:ring-ring">
                <span className="pl-3 text-sm text-muted-foreground">/</span>
                <Input id="org-slug" value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())}
                       className="border-0 pl-1 font-mono text-sm shadow-none focus-visible:ring-0" aria-invalid={Boolean(slugWarning)} />
              </div>
              {slugWarning
                ? <p className="text-sm text-amber-700 dark:text-amber-400">{slugWarning}</p>
                : org && slug !== org.slug && <p className="text-xs text-muted-foreground">Changing the address changes every link to this workspace.</p>}
            </div>
            <div className="flex items-center gap-3">
              <Button type="submit" disabled={!changed || Boolean(slugWarning) || save.isPending}>{save.isPending ? "Saving…" : changed ? "Save changes" : "Saved"}</Button>
              {changed && <Button type="button" variant="ghost" onClick={() => { if (org) { setName(org.name); setSlug(org.slug); } }}>Discard</Button>}
            </div>
          </form>
        </section>

        <section className={`${card} p-6`} aria-label="Members">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-base font-semibold"><Users className="h-4 w-4" /> Members</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {accepted.length} member{accepted.length === 1 ? "" : "s"}{pending.length ? ` · ${pending.length} invited` : ""}. Somebody with a Forge account joins the moment they are invited; anyone else is sent the sign-up address.
              </p>
            </div>
            <Button type="button" onClick={() => setInviting(true)}><Mail className="mr-2 h-4 w-4" />Invite</Button>
          </div>

          {outcomes.length > 0 && (
            <div className="mt-4 space-y-2">
              {outcomes.map((o, i) => <InviteNotice key={`${o.invite_email}-${i}`} outcome={o} onDismiss={() => setOutcomes((all) => all.filter((_, j) => j !== i))} />)}
            </div>
          )}

          <ul className="mt-5 divide-y divide-slate-100 dark:divide-slate-800" data-members="">
            {membersLoading && <li className="py-3 text-sm text-muted-foreground">Loading…</li>}
            {!membersLoading && members.length === 0 && <li className="py-3 text-sm text-muted-foreground">No members yet.</li>}
            {accepted.map((m) => (
              <li key={m.id} data-member-row="member" className="flex items-center gap-3 py-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">{initials(m.name, m.email)}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{m.name || m.email}</span>
                  <span className="block truncate text-xs text-muted-foreground">{m.name ? m.email : ""}{m.joined_at ? `${m.name ? " · " : ""}joined ${when(m.joined_at)}` : ""}</span>
                </span>
                <span title={ROLES.find((r) => r.value === m.role)?.hint} className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${ROLE_STYLE[m.role] ?? ROLE_STYLE.member}`}>{m.role}</span>
              </li>
            ))}
            {pending.map((m) => (
              <li key={m.id} data-member-row="invited" className="flex items-center gap-3 py-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-dashed border-slate-300 text-xs font-semibold text-slate-400 dark:border-slate-600">{initials(null, m.email)}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{m.email}</span>
                  <span className="block text-xs text-muted-foreground">Invited{m.created_at ? ` ${when(m.created_at)}` : ""} · not signed up yet</span>
                </span>
                <span className="rounded-full border border-dashed px-2.5 py-0.5 text-xs text-muted-foreground">invited as {m.role}</span>
                <Button type="button" variant="ghost" size="icon" className="h-7 w-7" title="Send the invitation again" onClick={() => resend.mutate(m.id)} disabled={resend.isPending}>
                  <RefreshCw className="h-3.5 w-3.5" />
                </Button>
                <Button type="button" variant="ghost" size="icon" className="h-7 w-7 text-destructive" title="Withdraw the invitation"
                        onClick={() => { if (window.confirm(`Withdraw the invitation to ${m.email}?`)) withdraw.mutate(m.id); }}>
                  <XIcon className="h-3.5 w-3.5" />
                </Button>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {inviting && <InviteDialog orgId={orgId} onClose={() => setInviting(false)} onDone={(got) => { setOutcomes((all) => [...got, ...all]); refreshMembers(); }} />}
    </div>
  );
}

function InviteDialog({ orgId, onClose, onDone }: { orgId: string; onClose: () => void; onDone: (outcomes: InviteOutcome[]) => void }) {
  const [text, setText] = useState("");
  const [role, setRole] = useState<MemberRole>("member");
  const [sending, setSending] = useState(false);
  const emails = parseEmails(text);
  const bad = badEmails(emails);

  async function send() {
    setSending(true);
    const got: InviteOutcome[] = [];
    for (const email of emails) {
      try { got.push(await api.post<InviteOutcome>(`/api/orgs/${orgId}/invite`, { email, role })); }
      catch (e) { got.push({ id: "", invite_email: `${email} — ${e instanceof Error ? e.message : "not invited"}`, role, invite_status: "failed", joined: false, emailed: false, invite_url: "" }); }
    }
    setSending(false);
    onDone(got);
    onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-invite-dialog="">
        <DialogHeader>
          <DialogTitle>Invite members</DialogTitle>
          <DialogDescription>Separate several emails with a comma.</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="invite-emails">Email</Label>
            <Input id="invite-emails" autoFocus placeholder="colleague@example.com, another@example.com" value={text} onChange={(e) => setText(e.target.value)} aria-invalid={bad.length > 0} />
            {bad.length > 0 && <p className="text-sm text-amber-700">Not an email address: {bad.join(", ")}</p>}
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Role</legend>
            {ROLES.map((r) => (
              <label key={r.value} className="flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2 text-sm has-[:checked]:border-primary">
                <input type="radio" name="invite-role" className="mt-1 accent-primary" checked={role === r.value} onChange={() => setRole(r.value)} />
                <span><span className="font-medium">{r.title}</span><span className="block text-muted-foreground">{r.hint}</span></span>
              </label>
            ))}
          </fieldset>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="button" disabled={sending || emails.length === 0 || bad.length > 0} onClick={send}>
            {sending ? "Sending…" : emails.length > 1 ? `Send ${emails.length} invitations` : "Send invitation"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function SettingsPage({ params }: { params: Promise<{ orgId: string }> }) {
  const { orgId } = use(params);
  return <OrgSettings orgId={orgId} />;
}
