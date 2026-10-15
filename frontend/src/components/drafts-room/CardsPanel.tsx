"use client";

/**
 * The feature cards: one feature of a reference each, in Forge's terms —
 * records and fields, the process, screens, rules, roles — every line with
 * the standing of the evidence it rests on, the unknowns kept visible, and
 * what each needs of the platform with whether Forge can do it yet.
 */
import { useState } from "react";
import { StandingCounts } from "./StandingDot";
import type { Card, Reference } from "./types";

export const NEED_STATUS: Record<string, "proven" | "unproven" | "not_yet"> = {
  roles: "proven", workflows: "proven", analytics: "proven", file_upload: "proven", email: "proven", audit: "proven",
  encryption: "proven", scheduling: "proven", public_pages: "proven", guest: "proven", mobile_pwa: "proven",
  push: "unproven", sso: "unproven", tenancy: "unproven", payments: "unproven", other_integration: "unproven",
  realtime: "unproven", maps: "unproven", image_search: "unproven", ai_extraction: "unproven", i18n: "unproven",
  offline: "not_yet", collaboration: "not_yet", store_app: "not_yet", video: "not_yet", native_desktop: "not_yet",
};
const NEED_CLASS = { proven: "border-emerald-300 text-emerald-800", unproven: "border-amber-300 text-amber-800", not_yet: "border-red-300 text-red-800" };

export function NeedChip({ need, status }: { need: string; status?: "proven" | "unproven" | "not_yet" }) {
  const st = status ?? NEED_STATUS[need] ?? "not_yet";
  return (
    <span className={`inline-flex items-center rounded-full border px-1.5 py-0 text-[11px] ${NEED_CLASS[st]}`}
      title={st === "proven" ? "built and seen working" : st === "unproven" ? "built, not yet seen working end to end" : "not built yet"}>
      {need.replace(/_/g, " ")}{st !== "proven" ? ` · ${st === "not_yet" ? "not yet" : st}` : ""}
    </span>
  );
}

export function CardsPanel({ cards, references }: { cards: Card[]; references: Reference[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const refName = (id: string) => references.find((r) => r.id === id)?.name ?? "";
  if (cards.length === 0) {
    return <p className="text-sm text-muted-foreground py-6 text-center">No cards yet. They are written from the evidence when a deep study ends.</p>;
  }
  return (
    <div className="space-y-3 text-sm">
      {cards.map((c) => {
        const shown = open === c.id;
        return (
          <article key={c.id} className="rounded-lg border p-3 space-y-2" data-testid="card">
            <header className="flex items-start justify-between gap-2 cursor-pointer" onClick={() => setOpen(shown ? null : c.id)}>
              <div>
                <div className="font-medium">{c.feature}</div>
                <div className="text-xs text-muted-foreground">{refName(c.reference)}</div>
              </div>
              <StandingCounts counts={c.standing} />
            </header>
            {c.summary && <p className="text-xs">{c.summary}</p>}
            {c.needs?.length > 0 && <div className="flex flex-wrap gap-1">{c.needs.map((n) => <NeedChip key={n} need={n} />)}</div>}
            {shown && (
              <div className="space-y-2 text-xs">
                {c.records.length > 0 && (
                  <section><div className="font-semibold uppercase text-muted-foreground">Records</div>
                    <ul className="space-y-0.5">{c.records.map((r) => (
                      <li key={r.name}><span className="font-medium">{r.name}</span>: {r.fields.map((f) => `${f.name}${f.type ? `: ${f.type}` : ""}`).join(", ")}</li>
                    ))}</ul></section>
                )}
                {c.steps.length > 0 && (
                  <section><div className="font-semibold uppercase text-muted-foreground">Process</div>
                    <ol className="list-decimal pl-4 space-y-0.5">{c.steps.map((s, i) => <li key={i}>{s.does}{s.screen ? <span className="text-muted-foreground"> — {s.screen}</span> : null}</li>)}</ol></section>
                )}
                {c.screens.length > 0 && (
                  <section><div className="font-semibold uppercase text-muted-foreground">Screens</div>
                    <ul className="space-y-0.5">{c.screens.map((s) => (
                      <li key={s.name}><span className="font-medium">{s.name}</span>{s.device ? <span className="text-muted-foreground"> ({s.device})</span> : null}
                        {s.purpose ? ` — ${s.purpose}` : ""}{s.shows?.length ? <span className="text-muted-foreground">; shows {s.shows.join(", ")}</span> : null}</li>
                    ))}</ul></section>
                )}
                {c.rules.length > 0 && (
                  <section><div className="font-semibold uppercase text-muted-foreground">Rules</div>
                    <ul className="list-disc pl-4">{c.rules.map((r, i) => <li key={i}>{r.text}</li>)}</ul></section>
                )}
                {c.roles.length > 0 && (
                  <section><div className="font-semibold uppercase text-muted-foreground">Roles</div>
                    <ul className="list-disc pl-4">{c.roles.map((r) => <li key={r.name}>{r.name}{r.does ? ` — ${r.does}` : ""}</li>)}</ul></section>
                )}
                {c.unknowns.length > 0 && (
                  <section><div className="font-semibold uppercase text-muted-foreground">Unknown</div>
                    <ul className="list-disc pl-4 text-amber-800">{c.unknowns.map((u, i) => <li key={i}>{u}</li>)}</ul></section>
                )}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
