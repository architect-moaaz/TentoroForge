// packages/editor/src/panes/Properties/style/TokenPicker.tsx
//
// Scope-aware token picker for the StyleSlot editor world.
// Walks a TokenGroups-shaped tree to leaf level and emits full
// "tokens.<scope>.<path>" refs. The legacy TokenPicker.tsx in the parent
// directory remains unchanged — the two coexist.

import type { TokenGroups } from "@tentoroforge/library";

export type Scope = "color" | "spacing" | "radius" | "shadow" | "typography";

interface TokenLeaf {
  ref: string;   // e.g. "tokens.color.primary.500"
  value: string; // e.g. "#3b82f6" or "1rem"
}

/** Recursively collect leaf nodes from an arbitrary nested token tree. */
function collectLeaves(node: unknown, prefix: string): TokenLeaf[] {
  if (node === null || node === undefined) return [];
  if (typeof node === "string" || typeof node === "number") {
    return [{ ref: prefix, value: String(node) }];
  }
  if (typeof node === "object") {
    const results: TokenLeaf[] = [];
    for (const [key, child] of Object.entries(node as Record<string, unknown>)) {
      results.push(...collectLeaves(child, `${prefix}.${key}`));
    }
    return results;
  }
  return [];
}

function buildLeaves(scope: Scope, theme: TokenGroups): TokenLeaf[] {
  const subtree: unknown = (theme as Record<string, unknown>)[scope];
  if (!subtree) return [];
  const raw = collectLeaves(subtree, `tokens.${scope}`);
  return raw.sort((a, b) => a.ref.localeCompare(b.ref));
}

export function TokenPicker({
  scope,
  value,
  onChange,
  theme,
  placeholder,
  ariaLabel,
}: {
  scope: Scope;
  value: string | undefined;
  onChange: (v: string | undefined) => void;
  theme: TokenGroups | null;
  placeholder?: string;
  ariaLabel?: string;
}): React.ReactElement {
  const leaves: TokenLeaf[] = theme === null ? [] : buildLeaves(scope, theme);
  const isDisabled = theme === null || leaves.length === 0;

  // Resolve the current color value for the swatch
  const selectedLeaf = value ? leaves.find((l) => l.ref === value) : undefined;
  const swatchColor = selectedLeaf?.value ?? "transparent";

  // Strip the "tokens.<scope>." prefix for display
  const prefixToStrip = `tokens.${scope}.`;

  if (isDisabled) {
    return (
      <div
        data-token-picker={scope}
        style={{ display: "flex", alignItems: "center", gap: 4 }}
      >
        <select
          aria-label={ariaLabel ?? scope}
          disabled
          style={{ flex: 1 }}
        >
          <option>{placeholder ?? "(no theme loaded)"}</option>
        </select>
      </div>
    );
  }

  return (
    <div
      data-token-picker={scope}
      style={{ display: "flex", alignItems: "center", gap: 4 }}
    >
      <select
        aria-label={ariaLabel ?? scope}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
        style={{ flex: 1 }}
      >
        <option value="">—</option>
        {leaves.map((leaf) => {
          const display = leaf.ref.slice(prefixToStrip.length);
          return (
            <option key={leaf.ref} value={leaf.ref}>
              {display}  ·  {leaf.value}
            </option>
          );
        })}
      </select>
      {scope === "color" && (
        <div
          aria-hidden="true"
          style={{
            width: 16,
            height: 16,
            background: swatchColor,
            border: "1px solid #e4e4e7",
            borderRadius: 3,
            flexShrink: 0,
          }}
        />
      )}
    </div>
  );
}
