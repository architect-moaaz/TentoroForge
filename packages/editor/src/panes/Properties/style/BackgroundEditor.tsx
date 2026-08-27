// packages/editor/src/panes/Properties/style/BackgroundEditor.tsx
//
// Discriminated-union editor for the StyleSlot `background` field.
// Renders a type switcher and variant-specific controls. Does NOT
// call into Zod — shape correctness is enforced by the store.

import type { BackgroundT } from "@tentoroforge/schema";
import type { TokenGroups } from "@tentoroforge/library";
import { TokenPicker } from "./TokenPicker";

// Seeded defaults for each variant when the user switches type.
const SOLID_DEFAULT: BackgroundT = {
  type: "solid",
  value: "tokens.color.primary.500",
};

const GRADIENT_DEFAULT: BackgroundT = {
  type: "gradient",
  from: "tokens.color.primary.400",
  to: "tokens.color.primary.600",
  angle: 90,
};

const IMAGE_DEFAULT: BackgroundT = {
  type: "image",
  url: "",
};

const PATTERN_DEFAULT: BackgroundT = {
  type: "pattern",
  name: "dots",
};

function defaultFor(t: BackgroundT["type"]): BackgroundT {
  switch (t) {
    case "solid":    return SOLID_DEFAULT;
    case "gradient": return GRADIENT_DEFAULT;
    case "image":    return IMAGE_DEFAULT;
    case "pattern":  return PATTERN_DEFAULT;
  }
}

/** Merge a partial update into the current value while preserving other fields. */
function mergeVariant<T extends BackgroundT>(current: T, patch: Partial<T>): T {
  return { ...current, ...patch };
}

const FALLBACK_COLOR = "tokens.color.primary.500";

export function BackgroundEditor({
  value,
  onChange,
  theme,
}: {
  value: BackgroundT | undefined;
  onChange: (v: BackgroundT | undefined) => void;
  theme: TokenGroups | null;
}): React.ReactElement {
  const currentType = value?.type ?? "(none)";

  function handleTypeChange(newType: string) {
    if (newType === "(none)") {
      onChange(undefined);
    } else {
      onChange(defaultFor(newType as BackgroundT["type"]));
    }
  }

  return (
    <div data-background-editor style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {/* Type switcher */}
      <select
        aria-label="background type"
        value={currentType}
        onChange={(e) => handleTypeChange(e.target.value)}
        style={{ width: "100%" }}
      >
        <option value="(none)">(none)</option>
        <option value="solid">solid</option>
        <option value="gradient">gradient</option>
        <option value="image">image</option>
        <option value="pattern">pattern</option>
      </select>

      {/* Variant controls */}
      {value?.type === "solid" && (
        <div data-bg-variant="solid" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 12 }}>Color</label>
          <TokenPicker
            scope="color"
            value={value.value}
            onChange={(v) => onChange(mergeVariant(value, { value: v ?? FALLBACK_COLOR }))}
            theme={theme}
            ariaLabel="solid color"
          />
        </div>
      )}

      {value?.type === "gradient" && (
        <div data-bg-variant="gradient" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 12 }}>From</label>
          <TokenPicker
            scope="color"
            value={value.from}
            onChange={(v) => onChange(mergeVariant(value, { from: v ?? FALLBACK_COLOR }))}
            theme={theme}
            ariaLabel="gradient from"
          />
          <label style={{ fontSize: 12 }}>To</label>
          <TokenPicker
            scope="color"
            value={value.to}
            onChange={(v) => onChange(mergeVariant(value, { to: v ?? FALLBACK_COLOR }))}
            theme={theme}
            ariaLabel="gradient to"
          />
          <label style={{ fontSize: 12 }}>Angle (0–360)</label>
          <input
            type="number"
            aria-label="gradient angle"
            min={0}
            max={360}
            step={1}
            value={value.angle ?? ""}
            onChange={(e) => {
              const raw = e.target.value;
              const n = Number(raw);
              const angle = raw === "" || Number.isNaN(n) ? undefined : Math.round(n);
              onChange(mergeVariant(value, { angle }));
            }}
            style={{ width: "100%" }}
          />
        </div>
      )}

      {value?.type === "image" && (
        <div data-bg-variant="image" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 12 }}>URL</label>
          <input
            type="url"
            aria-label="image url"
            value={value.url}
            onChange={(e) => onChange(mergeVariant(value, { url: e.target.value }))}
            placeholder="https://... or /path/to/image"
            style={{ width: "100%" }}
          />
          <label style={{ fontSize: 12 }}>Overlay (optional)</label>
          <TokenPicker
            scope="color"
            value={value.overlay}
            onChange={(v) => onChange(mergeVariant(value, { overlay: v }))}
            theme={theme}
            ariaLabel="image overlay"
          />
          <label style={{ fontSize: 12 }}>Position (optional)</label>
          <input
            type="text"
            aria-label="image position"
            value={value.position ?? ""}
            onChange={(e) =>
              onChange(mergeVariant(value, { position: e.target.value || undefined }))
            }
            placeholder="center center"
            style={{ width: "100%" }}
          />
        </div>
      )}

      {value?.type === "pattern" && (
        <div data-bg-variant="pattern" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 12 }}>Pattern</label>
          <select
            aria-label="pattern name"
            value={value.name}
            onChange={(e) =>
              onChange(
                mergeVariant(value, {
                  name: e.target.value as "dots" | "grid" | "noise" | "mesh",
                })
              )
            }
            style={{ width: "100%" }}
          >
            <option value="dots">dots</option>
            <option value="grid">grid</option>
            <option value="noise">noise</option>
            <option value="mesh">mesh</option>
          </select>
          <label style={{ fontSize: 12 }}>Color (optional)</label>
          <TokenPicker
            scope="color"
            value={value.color}
            onChange={(v) => onChange(mergeVariant(value, { color: v }))}
            theme={theme}
            ariaLabel="pattern color"
          />
        </div>
      )}
    </div>
  );
}
