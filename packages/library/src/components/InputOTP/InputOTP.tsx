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

const REQUIRED_MARK = "ms-0.5 text-destructive";

export function InputOTP({ name, label, length = 6, disabled, validators, style, value = "", onChange }: InputOTPProps) {
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
  // A partially-filled code is never valid, so `required` goes on EVERY digit
  // box: the browser then blocks submit on the first empty one and focuses it,
  // which is the behaviour an author asking for a required OTP expects.
  const required = validators?.required === true;
  return (
    <div className="flex flex-col gap-1" data-input-otp="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && (
        <span className="text-sm font-medium text-foreground">
          {label}
          {required && <span className={REQUIRED_MARK} aria-hidden="true">*</span>}
        </span>
      )}
      <div className="flex gap-2">
        {Array.from({ length }).map((_, i) => (
          <input key={i} ref={(el) => { refs.current[i] = el; }}
            aria-label={`${label ?? name} digit ${i + 1}`} inputMode="numeric" maxLength={1} disabled={disabled}
            required={required}
            value={chars[i] ?? ""} onChange={(e) => set(i, e.target.value)}
            onKeyDown={(e) => { if (e.key === "Backspace" && !chars[i] && i > 0) refs.current[i - 1]?.focus(); }}
            className="h-10 w-10 rounded-md border border-input bg-transparent text-center text-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        ))}
      </div>
    </div>
  );
}
