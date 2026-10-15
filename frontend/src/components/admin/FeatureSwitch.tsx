"use client";

import { useState } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ReasonDialog } from "@/components/admin/ReasonDialog";

export type SwitchValue = "inherit" | "on" | "off";

/**
 * One feature's setting at one scope: inherit what is beneath, on, or off.
 * Every change asks for a reason first — the record is read later by
 * someone who was not there.
 */
export function FeatureSwitch({
  value, inheritLabel, featureName, pending, onChange,
}: {
  value: SwitchValue;
  inheritLabel: string;
  featureName: string;
  pending?: boolean;
  onChange: (enabled: boolean | null, reason: string) => void;
}) {
  const [asking, setAsking] = useState<SwitchValue | null>(null);
  const words = { inherit: inheritLabel, on: "On", off: "Off" } as const;
  return (
    <>
      <Select value={value} onValueChange={(v) => { if (v !== value) setAsking(v as SwitchValue); }} disabled={pending}>
        <SelectTrigger className="h-8 w-40 text-xs" data-testid={`switch-${featureName}`}><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="inherit">{inheritLabel}</SelectItem>
          <SelectItem value="on">On</SelectItem>
          <SelectItem value="off">Off</SelectItem>
        </SelectContent>
      </Select>
      <ReasonDialog open={!!asking} onOpenChange={(o) => !o && setAsking(null)}
                    title={`${featureName}: ${asking ? words[asking] : ""}`}
                    description={asking === "inherit" ? "Clears this setting; what is beneath it applies again." : asking === "off" ? "Members keep seeing it, locked, with a note to ask you. Its routes refuse." : "Members may use it from the next page load."}
                    confirmText="Save" danger={asking === "off"} pending={pending}
                    onConfirm={(reason) => { if (asking) onChange(asking === "inherit" ? null : asking === "on", reason); setAsking(null); }} />
    </>
  );
}

export function switchValue(row: { enabled: boolean } | null): SwitchValue {
  return row === null ? "inherit" : row.enabled ? "on" : "off";
}
