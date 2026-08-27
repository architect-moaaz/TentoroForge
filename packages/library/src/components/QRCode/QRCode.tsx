"use client";
import * as React from "react";
import { QRCodeSVG } from "qrcode.react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { QRCodePropsType } from "./QRCode.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface QRCodeProps extends QRCodePropsType { style?: StyleSlotT; }

export function QRCode({ value, size = 128, label, style }: QRCodeProps) {
  return (
    <div className="inline-flex flex-col items-center gap-2" data-qr-code="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <QRCodeSVG value={value ?? ""} size={size} />
      {label && <span className="text-xs text-muted-foreground">{label}</span>}
    </div>
  );
}
