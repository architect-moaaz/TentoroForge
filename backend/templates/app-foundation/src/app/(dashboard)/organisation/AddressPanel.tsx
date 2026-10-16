"use client";
/**
 * The address the organisation answers at, and — for its admin — renaming
 * it. Shown when organisations have addresses of their own. Forge runtime.
 */
import * as React from "react";
import { apiPath } from "@/lib/api-path";

export function AddressPanel({ slug, domain, canManage }: { slug: string; domain: string; canManage: boolean }) {
  const [value, setValue] = React.useState(slug);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(apiPath("/api/org/address"), { method: "PUT", headers: { "Content-Type": "application/json" },
                                                             body: JSON.stringify({ slug: value }) });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) { setError(String(body?.error ?? "That did not work.")); return; }
      // The old address stops answering: go to the new one.
      window.location.href = `${body.address}/organisation`;
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="mb-8 rounded-lg border border-border p-4">
      <h2 className="mb-1 text-base font-semibold">Address</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Members open the organisation at <a className="font-mono underline" href={`https://${slug}.${domain}`}>{slug}.{domain}</a>.
      </p>
      {canManage && (
        <form onSubmit={save} className="flex flex-wrap items-center gap-2">
          <label htmlFor="org-address" className="sr-only">Address</label>
          <input id="org-address" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" spellCheck={false}
                 className="min-w-0 flex-1 rounded border border-border bg-background px-2 py-1 font-mono text-sm" />
          <span className="font-mono text-sm text-muted-foreground">.{domain}</span>
          <button type="submit" disabled={busy || !value.trim() || value === slug}
                  className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50">
            Change
          </button>
          {error && <p role="alert" className="w-full text-sm text-destructive">{error}</p>}
          <p className="w-full text-xs text-muted-foreground">The old address stops working; members use the new one.</p>
        </form>
      )}
    </section>
  );
}
