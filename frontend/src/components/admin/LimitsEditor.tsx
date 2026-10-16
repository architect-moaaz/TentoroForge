"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Limits, Period } from "@/lib/admin-types";

const PERIODS: Period[] = ["day", "week", "month", "year"];

/** One amount per period; empty clears the limit for that period. */
export function LimitsEditor({
  title, initial, pending, onSave,
}: {
  title: string;
  initial: Limits;
  pending?: boolean;
  onSave: (limits: Limits) => void;
}) {
  const [values, setValues] = useState<Record<Period, string>>({ day: "", week: "", month: "", year: "" });
  useEffect(() => {
    setValues({
      day: initial.day != null ? String(initial.day) : "",
      week: initial.week != null ? String(initial.week) : "",
      month: initial.month != null ? String(initial.month) : "",
      year: initial.year != null ? String(initial.year) : "",
    });
  }, [initial.day, initial.week, initial.month, initial.year]);

  function save() {
    const out: Limits = {};
    for (const p of PERIODS) {
      const v = values[p].trim();
      out[p] = v === "" ? undefined : Number(v);
    }
    onSave(out);
  }

  return (
    <div className="rounded-lg border p-3">
      <p className="mb-2 text-sm font-medium">{title}</p>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {PERIODS.map((p) => (
          <div key={p} className="space-y-1">
            <Label htmlFor={`limit-${p}`} className="text-xs capitalize">{p}</Label>
            <Input id={`limit-${p}`} type="number" min="0" step="1" placeholder="none" value={values[p]}
                   onChange={(e) => setValues({ ...values, [p]: e.target.value })} />
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-end">
        <Button size="sm" disabled={pending} onClick={save}>Save limits</Button>
      </div>
    </div>
  );
}
