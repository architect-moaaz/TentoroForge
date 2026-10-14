"use client";
import * as React from "react";
import { useRouter } from "next/navigation";
import { apiPath } from "@/lib/api-path";

type Member = { user_id: string; role: string; email: string; name?: string | null; is_active?: boolean };

export function MembersPanel({ members, canManage, me }: { members: Member[]; canManage: boolean; me: string }) {
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState(members[0]?.role ?? "");
  const [said, setSaid] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function call(method: string, body: Record<string, unknown>) {
    setBusy(true);
    setSaid(null);
    try {
      const res = await fetch(apiPath("/api/org/members"), { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) { setSaid(out.error ?? `Something went wrong (${res.status}).`); return; }
      if (out.setupPath) setSaid(`Invited. Their one-time setup link: ${out.setupPath}`);
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <ul className="divide-y divide-border rounded-md border border-border mb-4">
        {members.map((m) => (
          <li key={m.user_id} className="flex items-center justify-between p-3 text-sm">
            <div>
              <div className="font-medium">{m.name || m.email}</div>
              <div className="text-muted-foreground">{m.email} · {m.role}{m.is_active === false ? " · not set up yet" : ""}</div>
            </div>
            {canManage && m.user_id !== me && (
              <div className="flex gap-2">
                <button className="rounded border border-border px-2 py-1" disabled={busy}
                        onClick={() => { const next = prompt("New role", m.role); if (next) void call("PATCH", { userId: m.user_id, role: next }); }}>Change role</button>
                <button className="rounded border border-border px-2 py-1 text-destructive" disabled={busy}
                        onClick={() => { if (confirm(`Remove ${m.email} from this organisation?`)) void call("DELETE", { userId: m.user_id }); }}>Remove</button>
              </div>
            )}
          </li>
        ))}
        {members.length === 0 && <li className="p-6 text-center text-muted-foreground">Nobody here yet.</li>}
      </ul>
      {canManage && (
        <form className="flex flex-wrap gap-2 items-end" onSubmit={(e) => { e.preventDefault(); void call("POST", { email, role }); }}>
          <label className="text-sm">Email<br /><input className="rounded border border-border px-2 py-1" value={email} onChange={(e) => setEmail(e.target.value)} required type="email" /></label>
          <label className="text-sm">Role<br /><input className="rounded border border-border px-2 py-1" value={role} onChange={(e) => setRole(e.target.value)} required /></label>
          <button type="submit" disabled={busy} className="rounded bg-primary text-primary-foreground px-3 py-1">Invite</button>
        </form>
      )}
      {said && <p className="text-sm mt-3">{said}</p>}
    </div>
  );
}
