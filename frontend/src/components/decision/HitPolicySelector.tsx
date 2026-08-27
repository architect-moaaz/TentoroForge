"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { HIT_POLICY_LABELS, type HitPolicy } from "@/types/decision";

interface HitPolicySelectorProps {
  value: HitPolicy;
  onChange: (value: HitPolicy) => void;
  compact?: boolean;
}

const POLICIES: HitPolicy[] = ["U", "F", "A", "P", "C", "R"];

export function HitPolicySelector({ value, onChange, compact }: HitPolicySelectorProps) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as HitPolicy)}>
      <SelectTrigger className={compact ? "h-7 w-[60px] text-xs" : "h-8 text-xs"}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {POLICIES.map((p) => (
          <SelectItem key={p} value={p} className="text-xs">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-indigo-100 text-[10px] font-bold text-indigo-700">
                {p}
              </span>
              <span>{HIT_POLICY_LABELS[p].label}</span>
              {!compact && (
                <span className="text-muted-foreground text-[10px] ml-1">
                  — {HIT_POLICY_LABELS[p].description}
                </span>
              )}
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
