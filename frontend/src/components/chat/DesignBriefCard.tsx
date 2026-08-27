"use client";

import { Palette, Type, Layers, Sparkles } from "lucide-react";

// PHASE-3 chat card — renders the app's design brief inline. Two modes:
//   - metadata.brief_edit: Smith just applied an edit_brief patch. Show
//     the "after" summary + palette swatches + one-click tweaks.
//   - metadata.brief_snapshot: on-demand read (get_brief). Same shape,
//     no edit-latest badge.
// User clicks a tweak → sends a chat message describing the change,
// which Smith resolves into another edit_brief call.

interface Palette {
  brand: string;
  accent: string;
  neutrals_base: string;
  neutrals_tint: "warm" | "cool" | "neutral";
  surface_bg: string;
  surface_elevated: string;
  foreground_primary: string;
  foreground_muted: string;
}

interface Typography {
  display_family: string;
  display_weights: number[];
  body_family: string;
  body_weights: number[];
  utility_family?: string | null;
  scale: string;
}

interface Layout {
  density: "compact" | "comfortable" | "spacious" | "spacious_for_touch";
  radius: "sharp_2" | "soft_8" | "pill";
  grid: string;
  whitespace: string;
}

interface Identity {
  domain: string;
  register: string[];
  voice: string;
  modes: string[];
}

interface SignatureMove {
  kind: string;
  detail: string;
}

export interface DesignBriefPayload {
  identity: Identity;
  palette: Palette;
  typography: Typography;
  layout: Layout;
  signature_moves: SignatureMove[];
  anti_patterns: string[];
}

export interface BriefEditPayload {
  before?: { summary: string };
  after: { summary: string; brief: DesignBriefPayload };
}

interface Props {
  payload: DesignBriefPayload | BriefEditPayload;
  edited?: boolean;
  onSend: (message: string) => void;
  disabled?: boolean;
}

function isEdit(p: DesignBriefPayload | BriefEditPayload): p is BriefEditPayload {
  return "after" in p && "brief" in (p as BriefEditPayload).after;
}

const TWEAKS: Array<{ label: string; message: string }> = [
  { label: "More compact",    message: "Make the design more compact" },
  { label: "More spacious",   message: "Make the design more spacious" },
  { label: "Sharper corners", message: "Use sharper corners" },
  { label: "Softer corners",  message: "Use softer corners" },
  { label: "Different palette", message: "Try a different palette" },
  { label: "Different display font", message: "Try a different display font" },
];

export function DesignBriefCard({ payload, edited, onSend, disabled }: Props) {
  const brief = isEdit(payload) ? payload.after.brief : payload;
  const before = isEdit(payload) ? payload.before?.summary : undefined;
  const isEditView = isEdit(payload) || edited === true;

  const { palette, typography, layout, identity, signature_moves } = brief;

  return (
    <div className="mt-3 rounded-lg border border-border bg-background p-3 text-[13px]">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Palette className="h-3.5 w-3.5" />
        <span className="font-medium text-foreground">
          {isEditView ? "Brief updated" : "Design brief"}
        </span>
        <span className="text-[11px] text-muted-foreground">
          · {identity.domain}
        </span>
      </div>

      {before && (
        <div className="mt-1.5 text-[11px] text-muted-foreground line-through">
          {before}
        </div>
      )}

      {/* Palette swatches */}
      <div className="mt-2 flex items-center gap-1.5">
        {(
          [
            ["brand", palette.brand],
            ["accent", palette.accent],
            ["neutrals", palette.neutrals_base],
            ["surface", palette.surface_bg],
            ["fg", palette.foreground_primary],
          ] as const
        ).map(([label, hex]) => (
          <div key={label} className="flex flex-col items-center gap-0.5">
            <div
              className="h-6 w-6 rounded-md border border-border/60"
              style={{ backgroundColor: hex }}
              title={`${label} ${hex}`}
            />
            <span className="text-[9px] uppercase tracking-wide text-muted-foreground">
              {label}
            </span>
          </div>
        ))}
        <span className="ml-2 text-[10px] text-muted-foreground">
          {palette.neutrals_tint}
        </span>
      </div>

      {/* Type + layout row */}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <Type className="h-3 w-3" />
          {typography.display_family} / {typography.body_family}
        </span>
        <span className="inline-flex items-center gap-1">
          <Layers className="h-3 w-3" />
          {layout.density} · {layout.radius}
        </span>
        <span className="text-[10px]">
          {identity.voice}
        </span>
      </div>

      {/* Signature moves */}
      {signature_moves && signature_moves.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1">
          <Sparkles className="h-3 w-3 text-muted-foreground" />
          {signature_moves.map((m) => (
            <span
              key={m.kind}
              title={m.detail}
              className="rounded-full border border-border/60 bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground"
            >
              {m.kind}
            </span>
          ))}
        </div>
      )}

      {/* Tweak affordances */}
      {onSend && (
        <div className="mt-3 flex flex-wrap gap-1">
          {TWEAKS.map((t) => (
            <button
              key={t.label}
              type="button"
              disabled={disabled}
              onClick={() => onSend(t.message)}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-[11px] font-medium text-foreground transition hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
