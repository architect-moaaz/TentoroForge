import { z } from "zod";
import { StyleSlot } from "../style-slot";

// ── Wave 6 — device & capture components ─────────────────────────────────

export const CameraCaptureNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("CameraCapture"),
  props: z.object({
    name:         z.string().min(1),
    label:        z.string().optional(),
    captureLabel: z.string().optional(),
    bind:         z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type CameraCaptureNodeT = z.infer<typeof CameraCaptureNode>;

export const ScannerNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Scanner"),
  props: z.object({
    label:         z.string().optional(),
    scanLabel:     z.string().optional(),
    deviceType:    z.enum(["rfid", "barcode", "qr"]).optional(),
    value:         z.string().optional(),
    status:        z.enum(["idle", "scanning", "success", "error"]).optional(),
    statusMessage: z.string().optional(),
    bind:          z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type ScannerNodeT = z.infer<typeof ScannerNode>;

export const ValidationChecklistNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("ValidationChecklist"),
  props: z.object({
    items: z.array(z.object({
      label: z.string(),
      valid: z.boolean(),
    }).strict()).min(1),
    orientation: z.enum(["horizontal", "vertical"]).optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type ValidationChecklistNodeT = z.infer<typeof ValidationChecklistNode>;

export const BarcodeScannerNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("BarcodeScanner"),
  props: z.object({
    name:    z.string().min(1),
    label:   z.string().optional(),
    hint:    z.string().optional(),
    // BarcodeDetector format ids, e.g. ["ean_13","upc_a","qr_code"]. Empty = all.
    formats: z.array(z.string()).optional(),
    bind:    z.string().optional(),
    // Submit the enclosing Form as soon as a code is decoded (scan-to-search).
    autoSubmit: z.boolean().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type BarcodeScannerNodeT = z.infer<typeof BarcodeScannerNode>;
