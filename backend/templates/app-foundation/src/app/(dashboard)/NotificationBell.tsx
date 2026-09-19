"use client";
// The signed-in person's notifications — what workflows told them
// (`send_notification`: "A neighbour has requested to borrow your tool").
// The runtime wrote these rows from the start and nothing showed them: one
// chrome drew a bell with no handler, the others none at all. Rendered once
// beside the breadcrumb, so every shell has it.

import * as React from "react";
import { Bell, Check } from "lucide-react";

type Note = { id: string; title: string; message: string; type: string; read: boolean; createdAt: string | null };

function ago(iso: string | null): string {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(new Date(iso));
}

export function NotificationBell() {
  const [notes, setNotes] = React.useState<Note[]>([]);
  const [open, setOpen] = React.useState(false);
  const box = React.useRef<HTMLDivElement>(null);

  const load = React.useCallback(async () => {
    try {
      const r = await fetch("/api/notifications", { cache: "no-store" });
      if (r.ok) setNotes(await r.json());
    } catch { /* offline — keep what is shown */ }
  }, []);

  React.useEffect(() => {
    void load();
    const t = setInterval(load, 30_000);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    // A workflow that just ran may have told someone something.
    window.addEventListener("forge:workflow-done", onFocus);
    return () => { clearInterval(t); window.removeEventListener("focus", onFocus); window.removeEventListener("forge:workflow-done", onFocus); };
  }, [load]);

  React.useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const unread = notes.filter((n) => !n.read).length;
  const mark = async (body: Record<string, unknown>) => {
    setNotes((cur) => cur.map((n) => (body.all || n.id === body.id ? { ...n, read: true } : n)));
    try { await fetch("/api/notifications", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); } catch { /* retried on next load */ }
  };

  return (
    <div ref={box} className="relative shrink-0">
      <button type="button" onClick={() => setOpen((o) => !o)}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"} aria-expanded={open}
        className="relative grid h-9 w-9 place-items-center rounded-full border border-border bg-card text-foreground transition-colors hover:bg-muted">
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1 text-[11px] font-semibold text-accent-foreground">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications"
          className="absolute right-0 z-50 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border bg-popover text-popover-foreground shadow-xl">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <p className="text-sm font-semibold">Notifications</p>
            {unread > 0 && (
              <button type="button" onClick={() => void mark({ all: true })}
                className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
                <Check className="h-3.5 w-3.5" /> Mark all read
              </button>
            )}
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {notes.length === 0 && (
              <li className="px-4 py-8 text-center text-sm text-muted-foreground">Nothing yet — you'll see updates here.</li>
            )}
            {notes.map((n) => (
              <li key={n.id}>
                <button type="button" onClick={() => !n.read && void mark({ id: n.id })}
                  className={"flex w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-muted " + (n.read ? "" : "bg-accent-subtle/60")}>
                  <span aria-hidden="true" className={"mt-1.5 h-2 w-2 shrink-0 rounded-full " + (n.read ? "bg-transparent" : "bg-accent")} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{n.title}</span>
                    {n.message && <span className="mt-0.5 block text-sm text-muted-foreground">{n.message}</span>}
                    <span className="mt-1 block text-xs text-muted-foreground">{ago(n.createdAt)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
