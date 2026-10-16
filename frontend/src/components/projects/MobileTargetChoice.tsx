"use client";

import { Globe, Smartphone } from "lucide-react";
import { Label } from "@/components/ui/label";

/** What the app is for. `responsive`: a website that also works on phones. `native`: that website AND a real
 *  mobile app (iPhone and Android) made from the same app. Chosen when the app is created; the backend turns
 *  it into the Blueprint's `mobile.native.enabled`. */
export type MobileTarget = "responsive" | "native";

const OPTIONS: ReadonlyArray<{ value: MobileTarget; title: string; hint: string; icon: typeof Globe }> = [
  { value: "responsive", title: "Web + responsive mobile", hint: "One website that works well on phones too.", icon: Globe },
  { value: "native", title: "Web + mobile app", hint: "The website, plus a native iPhone and Android app that shares its data.", icon: Smartphone },
];

export function MobileTargetChoice({
  value,
  onChange,
  idPrefix = "mobile-target",
}: {
  value: MobileTarget;
  onChange: (next: MobileTarget) => void;
  idPrefix?: string;
}) {
  return (
    <div>
      <Label id={`${idPrefix}-label`}>Where will people use it?</Label>
      <div className="mt-1 grid gap-2" role="radiogroup" aria-labelledby={`${idPrefix}-label`}>
        {OPTIONS.map(({ value: v, title, hint, icon: Icon }) => (
          <button
            key={v}
            type="button"
            role="radio"
            aria-checked={value === v}
            onClick={() => onChange(v)}
            className={`flex items-start gap-3 rounded-md border px-3 py-2 text-left transition-colors ${
              value === v ? "border-foreground bg-accent" : "hover:bg-accent"
            }`}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span>
              <span className="block text-sm font-medium">{title}</span>
              <span className="block text-xs text-muted-foreground">{hint}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
