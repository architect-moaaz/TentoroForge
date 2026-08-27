// packages/editor/src/panes/Properties/style/MotionEditor.tsx
//
// Simple enum select for the StyleSlot `motion` field.
// "(unset)" sentinel maps to undefined; all other values pass through as-is.

import type { MotionT } from "@tentoroforge/schema";

const MOTION_VALUES: MotionT[] = ["none", "fade-in", "fade-up", "stagger", "slide-in"];

export function MotionEditor({
  value,
  onChange,
}: {
  value: MotionT | undefined;
  onChange: (v: MotionT | undefined) => void;
}): React.ReactElement {
  return (
    <div data-motion-editor>
      <select
        aria-label="motion"
        value={value ?? ""}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "" ? undefined : (v as MotionT));
        }}
        style={{ width: "100%" }}
      >
        <option value="">(unset)</option>
        {MOTION_VALUES.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </div>
  );
}
