// packages/editor/src/panes/Properties/StyleSlotEditor.tsx
//
// Composes the Task 30 sub-controls (TokenPicker, BackgroundEditor,
// MotionEditor) into a single, section-based editor for the StyleSlot mixin.
// Pure controlled component — reads no store, writes nothing. Parent wires it.
//
// Wave 2: optional `designSystem` prop surfaces density / elevation /
// radius.scale selectors. These are token-system-level knobs (not per-node
// style props) so they are written back via the `onDesignSystemChange`
// callback — the parent (Properties.tsx) wires this to store.setTokenValue().

import type { StyleSlotT } from "@tentoroforge/schema";
import type { TokenGroups } from "@tentoroforge/library";
import { BackgroundEditor } from "./style/BackgroundEditor";
import { TokenPicker } from "./style/TokenPicker";
import { MotionEditor } from "./style/MotionEditor";

const sectionHeadingStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  textTransform: "uppercase",
  color: "#6b7280",
  margin: "12px 0 6px",
};

// ---------------------------------------------------------------------------
// Wave 2 design-system knob selectors
// ---------------------------------------------------------------------------

const selectStyle: React.CSSProperties = {
  width: "100%",
  fontFamily: "monospace",
  fontSize: 12,
  padding: "3px 6px",
  border: "1px solid #e5e7eb",
  borderRadius: 4,
  background: "#fff",
  marginBottom: 4,
};

/** Values allowed for each knob — kept in sync with TOKENS_NEW_GROUPS_GUIDANCE. */
const DENSITY_OPTIONS   = ["compact", "comfortable", "spacious"] as const;
const ELEVATION_OPTIONS = ["flat", "bordered", "layered", "floating"] as const;
const RADIUS_SCALE_OPTIONS = ["sharp", "soft", "round"] as const;

export type DesignSystemKnobs = {
  density?: string;
  elevation?: string;
  radiusScale?: string;
};

function EnumSelect({
  label,
  value,
  options,
  onChange,
  ariaLabel,
}: {
  label: string;
  value: string | undefined;
  options: readonly string[];
  onChange: (v: string) => void;
  ariaLabel: string;
}): React.ReactElement {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 2 }}>{label}</div>
      <select
        aria-label={ariaLabel}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        style={selectStyle}
      >
        <option value="">— inherit —</option>
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function StyleSlotEditor({
  value,
  onChange,
  theme,
  designSystem,
  onDesignSystemChange,
}: {
  value: StyleSlotT | undefined;
  // `next` is `any` because each StyleSlotT key carries a distinct value type
  // (BackgroundT | string ref | MotionT). A distributive mapped type would add
  // more complexity than it removes at this single boundary.
  onChange: (key: keyof StyleSlotT, next: any) => void;
  theme: TokenGroups | null;
  /** Wave 2 — current values for the system-level token knobs. */
  designSystem?: DesignSystemKnobs;
  /** Wave 2 — called when the user changes a system-level knob. */
  onDesignSystemChange?: (knob: keyof DesignSystemKnobs, value: string) => void;
}): React.ReactElement {
  return (
    <section
      data-style-slot-editor
      role="group"
      aria-label="Style slot editor"
      style={{ padding: 12 }}
    >
      {/* Background */}
      <h3 style={sectionHeadingStyle}>Background</h3>
      <BackgroundEditor
        value={
          value?.background && typeof value.background === "object"
            ? (value.background as any)
            : undefined
        }
        onChange={(v) => onChange("background", v)}
        theme={theme}
      />

      {/* Padding */}
      <h3 style={sectionHeadingStyle}>Padding</h3>
      <TokenPicker
        scope="spacing"
        value={value?.padding}
        onChange={(v) => onChange("padding", v)}
        theme={theme}
        ariaLabel="padding"
      />

      {/* Radius */}
      <h3 style={sectionHeadingStyle}>Radius</h3>
      <TokenPicker
        scope="radius"
        value={value?.radius}
        onChange={(v) => onChange("radius", v)}
        theme={theme}
        ariaLabel="radius"
      />

      {/* Shadow */}
      <h3 style={sectionHeadingStyle}>Shadow</h3>
      <TokenPicker
        scope="shadow"
        value={value?.shadow}
        onChange={(v) => onChange("shadow", v)}
        theme={theme}
        ariaLabel="shadow"
      />

      {/* Motion */}
      <h3 style={sectionHeadingStyle}>Motion</h3>
      <MotionEditor
        value={value?.motion}
        onChange={(v) => onChange("motion", v)}
      />

      {/* ── Wave 2: Design system knobs ──────────────────────────────────── */}
      {onDesignSystemChange && (
        <>
          <h3 style={{ ...sectionHeadingStyle, marginTop: 16 }}>Design system</h3>
          <div
            data-design-system-knobs
            style={{ fontSize: 11, color: "#6b7280", marginBottom: 8 }}
          >
            System-wide · cascades from root node
          </div>

          <EnumSelect
            label="Density"
            value={designSystem?.density}
            options={DENSITY_OPTIONS}
            onChange={(v) => onDesignSystemChange("density", v)}
            ariaLabel="density"
          />

          <EnumSelect
            label="Elevation"
            value={designSystem?.elevation}
            options={ELEVATION_OPTIONS}
            onChange={(v) => onDesignSystemChange("elevation", v)}
            ariaLabel="elevation"
          />

          <EnumSelect
            label="Radius scale"
            value={designSystem?.radiusScale}
            options={RADIUS_SCALE_OPTIONS}
            onChange={(v) => onDesignSystemChange("radiusScale", v)}
            ariaLabel="radius scale"
          />
        </>
      )}
    </section>
  );
}
