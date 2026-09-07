"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ScannerPropsType } from "./Scanner.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useFieldValue } from "../../util/useFieldValue";

export interface ScannerProps extends ScannerPropsType {
  style?: StyleSlotT;
  /** Fired when the Scan button is pressed (or Enter in the entry field). */
  onScan?: (code: string) => void;
  onChange?: (value: string) => void;
}

const STATUS_COLORS = {
  success: "#16a34a",
  error:   "#dc2626",
} as const;

type Status = "idle" | "scanning" | "success" | "error";

/**
 * Scanner — an RFID / barcode / QR capture field.
 *
 * It used to be fully parent-controlled with ZERO state: the Scan button was
 * `onClick={onScan}` and `onScan` is not in the schema, not in the registry and
 * never passed by the renderer, so a Scanner dropped on a page was a static
 * mock — the button did nothing, forever, and only the *designer* could move
 * `status`. It now holds its value through the library's one state contract
 * (`useFieldValue`): `value` alone is a declarative seed, `value` + `onChange`
 * is genuinely controlled.
 *
 * Capture is a text entry plus a Scan button because that is what the hardware
 * actually does — RFID and barcode readers are HID devices that type the code
 * into the focused field and press Enter. `onScan` still fires for hosts that
 * drive a native bridge.
 */
export function Scanner({
  name,
  label,
  scanLabel,
  deviceType = "rfid",
  value,
  status,
  statusMessage,
  bind: _bind,
  className,
  style,
  onScan,
  onChange,
}: ScannerProps) {
  const [current, commit] = useFieldValue<string>(value, onChange, undefined, "");
  const [draft, setDraft] = React.useState("");
  // `null` = "the component has not moved the status yet", so the authored
  // `status` prop still shows on the canvas until the user actually scans.
  const [ownStatus, setOwnStatus] = React.useState<Status | null>(null);

  const effectiveStatus: Status = ownStatus ?? (status as Status | undefined) ?? "idle";
  const effectiveMessage = statusMessage;

  const scan = React.useCallback(() => {
    const code = draft.trim();
    // `onScan` still fires for hosts driving a native scanner bridge.
    onScan?.(code);
    if (!code) return;
    commit(code);
    setOwnStatus("success");
    setDraft("");
  }, [draft, commit, onScan]);

  return (
    <div
      data-scanner=""
      className={className}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {label && (
        <div className="text-sm font-medium text-foreground mb-2">{label}</div>
      )}

      {/* Carry the scanned code into the enclosing form's FormData under `name`.
          Same pattern as Switch.tsx. */}
      {name && <input type="hidden" name={name} value={current} readOnly />}

      <div className="flex items-center gap-2">
        <input
          type="text"
          value={draft}
          aria-label={`${deviceType} code`}
          placeholder={`Scan or type a ${deviceType} code`}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); scan(); }
          }}
          className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button
          type="button"
          aria-label={`Scan ${deviceType}`}
          onClick={scan}
          className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm font-medium text-foreground shadow-sm hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {scanLabel ?? "Scan"}
        </button>
      </div>

      <div
        data-testid="scan-result"
        data-status={effectiveStatus}
        className="mt-2 rounded-md border border-input bg-background p-3 text-sm min-h-[3rem]"
      >
        {effectiveStatus === "scanning" && (
          <span className="text-muted-foreground">Scanning…</span>
        )}

        {effectiveStatus === "success" && (
          <div style={{ color: STATUS_COLORS.success }}>
            <span className="me-1">✓</span>
            {current && <span className="font-mono font-semibold me-2">{current}</span>}
            {effectiveMessage && <span>{effectiveMessage}</span>}
          </div>
        )}

        {effectiveStatus === "error" && (
          <div style={{ color: STATUS_COLORS.error }}>
            <span className="me-1">✗</span>
            {effectiveMessage && <span>{effectiveMessage}</span>}
          </div>
        )}

        {effectiveStatus === "idle" && (
          <span className="text-muted-foreground">
            {current ? current : "Awaiting scan…"}
          </span>
        )}
      </div>
    </div>
  );
}
