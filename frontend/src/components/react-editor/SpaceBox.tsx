"use client";
/** The margin and padding of the part that was picked: a size or a number for each side. Saved into the plan like any other change. */
import { useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

import { KINDS, marginOf, readSpace, SIDES, SIZES, sizeNamed, spaceOp, type Margins, type SideKey } from "./phoneSpace";
import type { PhonePart } from "./types";
import type { PhoneSession } from "./usePhoneScreen";

export function SpaceBox({ part, session }: { part: PhonePart; session: PhoneSession }) {
  const { busy, run } = session;
  const space = useMemo(() => readSpace(part), [part]);
  const had = (k: SideKey) => (space.margins[k] === undefined ? "" : String(space.margins[k]));
  const [typed, setTyped] = useState<Partial<Record<SideKey, string>>>({});
  const [seen, setSeen] = useState(part.id);
  if (seen !== part.id) { setSeen(part.id); setTyped({}); }

  if (space.fromCode) {
    return <p className="text-[11px] text-muted-foreground" data-testid="space-from-code">The space around this part is decided by the screen's own code. Ask Smith to change it.</p>;
  }
  const text = (k: SideKey) => typed[k] ?? had(k);
  const parsed = SIDES.map((s) => [s.key, marginOf(text(s.key))] as const);
  const bad = parsed.some(([, v]) => v === "bad");
  const changed = SIDES.some((s) => text(s.key) !== had(s.key));
  const save = () => {
    const margins: Margins = {};
    for (const [k, v] of parsed) if (typeof v === "number") margins[k] = v;
    void run([spaceOp(part, margins, space.rest)], "Change the margin and padding", "Saved.").then((ok) => { if (ok) setTyped({}); });
  };

  return (
    <div className="space-y-1.5" data-testid="part-space">
      {KINDS.map((k) => (
        <div key={k.kind} className="space-y-1.5" data-testid={`part-${k.kind}`}>
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{k.kind === "margin" ? "Margin (space around)" : "Padding (space inside)"}</p>
      {SIDES.filter((s) => s.kind === k.kind).map((s) => {
        const value = marginOf(text(s.key));
        return (
          <div key={s.key} className="flex items-center gap-1.5">
            <label className="w-12 text-[11px] text-muted-foreground" htmlFor={`space-${s.key}`}>{s.label}</label>
            <select
              aria-label={`${s.kind} ${s.label} size`}
              disabled={busy}
              value={typeof value === "number" ? sizeNamed(value) ?? "" : ""}
              onChange={(e) => { const size = SIZES.find((z) => z.name === e.target.value); setTyped((t) => ({ ...t, [s.key]: size ? String(size.value) : "" })); }}
              className="w-16 rounded-md border bg-background px-1 py-1 text-xs"
            >
              <option value="">{typeof value === "number" ? "custom" : "none"}</option>
              {SIZES.map((z) => <option key={z.name} value={z.name}>{z.name}</option>)}
            </select>
            <input
              id={`space-${s.key}`}
              inputMode="decimal"
              value={text(s.key)}
              disabled={busy}
              placeholder="0"
              aria-invalid={value === "bad"}
              onChange={(e) => setTyped((t) => ({ ...t, [s.key]: e.target.value }))}
              onKeyDown={(e) => { if (e.key === "Enter" && changed && !bad) { e.preventDefault(); save(); } }}
              className={`min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm ${value === "bad" ? "border-red-500" : ""}`}
            />
            <span className="text-[11px] text-muted-foreground">pt</span>
          </div>
        );
      })}
        </div>
      ))}
      {bad && <p className="text-[11px] text-red-600">A margin or padding is a number of points, like 16.</p>}
      {changed && (
        <Button size="sm" className="h-7 w-full text-xs" disabled={busy || bad} onClick={save}>
          {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null} Save space
        </Button>
      )}
    </div>
  );
}
