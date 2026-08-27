"use client";

const BREAKPOINTS = [
  { id: "default", label: "All" },
  { id: "sm", label: "sm" },
  { id: "md", label: "md" },
  { id: "lg", label: "lg" },
  { id: "xl", label: "xl" },
] as const;

export type EditorBreakpoint = typeof BREAKPOINTS[number]["id"];

interface Props {
  value: EditorBreakpoint;
  onChange: (bp: EditorBreakpoint) => void;
  hasOverridesByBp?: Set<EditorBreakpoint>; // optional indication of which bp has overrides
}

export function BreakpointSwitcher({ value, onChange, hasOverridesByBp }: Props) {
  return (
    <div className="flex gap-0.5 border rounded-md p-0.5 bg-muted/40">
      {BREAKPOINTS.map(bp => {
        const isActive = value === bp.id;
        const hasOverride = hasOverridesByBp?.has(bp.id) ?? false;
        return (
          <button
            key={bp.id}
            onClick={() => onChange(bp.id)}
            className={`flex-1 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded ${
              isActive ? "bg-primary text-primary-foreground" : "hover:bg-background"
            }`}
            title={bp.id === "default" ? "Base value (all breakpoints)" : `Override for ${bp.id.toUpperCase()}+`}
          >
            {bp.label}{hasOverride && bp.id !== "default" ? "•" : ""}
          </button>
        );
      })}
    </div>
  );
}
