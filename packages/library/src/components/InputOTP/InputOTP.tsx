"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { InputOTPPropsType } from "./InputOTP.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface InputOTPProps extends InputOTPPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function InputOTP({ name, label, length = 6, disabled, style, value = "", onChange }: InputOTPProps) {
  const [chars, setChars] = React.useState<string[]>(() => Array.from({ length }, (_, i) => value[i] ?? ""));
  const refs = React.useRef<(HTMLInputElement | null)[]>([]);
  const set = (i: number, raw: string) => {
    const ch = raw.slice(-1);
    setChars((prev) => {
      const next = [...prev];
      next[i] = ch;
      onChange?.(next.join(""));
      return next;
    });
    if (ch && i < length - 1) refs.current[i + 1]?.focus();
  };
  return (
    <div className="flex flex-col gap-1" data-input-otp="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <span className="text-sm font-medium text-foreground">{label}</span>}
      <div className="flex gap-2">
        {Array.from({ length }).map((_, i) => (
          <input key={i} ref={(el) => { refs.current[i] = el; }}
            aria-label={`${label ?? name} digit ${i + 1}`} inputMode="numeric" maxLength={1} disabled={disabled}
            value={chars[i] ?? ""} onChange={(e) => set(i, e.target.value)}
            onKeyDown={(e) => { if (e.key === "Backspace" && !chars[i] && i > 0) refs.current[i - 1]?.focus(); }}
            className="h-10 w-10 rounded-md border border-input bg-transparent text-center text-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        ))}
      </div>
    </div>
  );
}
