"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ScannerPropsType } from "./Scanner.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface ScannerProps extends ScannerPropsType {
  style?: StyleSlotT;
  onScan?: () => void;
}

const STATUS_COLORS = {
  success: "#16a34a",
  error:   "#dc2626",
} as const;

export function Scanner({
  label,
  scanLabel,
  deviceType = "rfid",
  value,
  status = "idle",
  statusMessage,
  bind: _bind,
  className,
  style,
  onScan,
}: ScannerProps) {
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

      <button
        type="button"
        aria-label={`Scan ${deviceType}`}
        onClick={onScan}
        className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm font-medium text-foreground shadow-sm hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {scanLabel ?? "Scan"}
      </button>

      <div
        data-testid="scan-result"
        data-status={status}
        className="mt-2 rounded-md border border-input bg-background p-3 text-sm min-h-[3rem]"
      >
        {status === "scanning" && (
          <span className="text-muted-foreground">Scanning…</span>
        )}

        {status === "success" && (
          <div style={{ color: STATUS_COLORS.success }}>
            <span className="me-1">✓</span>
            {value && <span className="font-mono font-semibold me-2">{value}</span>}
            {statusMessage && <span>{statusMessage}</span>}
          </div>
        )}

        {status === "error" && (
          <div style={{ color: STATUS_COLORS.error }}>
            <span className="me-1">✗</span>
            {statusMessage && <span>{statusMessage}</span>}
          </div>
        )}

        {status === "idle" && (
          <span className="text-muted-foreground">
            {value ? value : "Awaiting scan…"}
          </span>
        )}
      </div>
    </div>
  );
}
