import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { useMotion } from "../../style/useMotion";
import { resolveStyle } from "../../style/resolveStyle";

type Shortcut = { keys: string; label: string; group?: string };
type Props = {
  shortcuts: Shortcut[];
  triggerKey?: string;
  style?: StyleSlotT;
};

/**
 * KeyboardShortcuts — Spec C Slice 7 shortcut legend.
 *
 * Renders a floating panel of keyboard shortcuts grouped by section.
 * Opens on `triggerKey` (default "?") pressed anywhere; closes on
 * Escape or on click outside. Escape re-focuses the previous element.
 */
export function KeyboardShortcuts({
  shortcuts, triggerKey = "?", style,
}: Props): React.ReactElement {
  const [open, setOpen] = React.useState(false);
  const anchorRef = React.useRef<HTMLSpanElement | null>(null);
  const motion = useMotion(style?.motion);
  const styleProps = resolveStyle(style);

  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't intercept while typing in an input/textarea.
      const target = e.target as HTMLElement | null;
      const isTyping =
        target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" ||
                   target.isContentEditable);
      if (isTyping) return;
      // Bail when the keystroke came from outside this component's page. In the
      // editor the designed page lives inside [data-canvas-root] and everything
      // else is editor chrome, so a stray "?" typed while designing no longer
      // drops a full-canvas scrim over the design surface. A generated app has
      // no canvas root, `scope` is null, and "?" still works from anywhere.
      const scope = anchorRef.current?.closest("[data-canvas-root]");
      if (scope && !scope.contains(target as Node)) return;
      if (e.key === triggerKey) { e.preventDefault(); setOpen((v) => !v); }
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [triggerKey]);

  // The anchor is always mounted, even while closed: it is what tells the
  // listener above which document region this instance belongs to.
  const anchor = (
    <span ref={anchorRef} hidden aria-hidden="true" data-forge-keyboard-shortcuts-anchor />
  );

  if (!open) return anchor;

  // Group shortcuts.
  const grouped: Record<string, Shortcut[]> = {};
  for (const s of shortcuts) {
    const g = s.group || "General";
    (grouped[g] ||= []).push(s);
  }

  return (
    <>
    {anchor}
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      data-forge-keyboard-shortcuts
      {...motion}
      onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div style={{
        width: "min(520px, 90vw)",
        maxHeight: "80vh",
        overflow: "auto",
        padding: 20,
        background: "var(--card, white)",
        color: "var(--card-foreground, hsl(0 0% 15%))",
        borderRadius: "var(--radius-lg, 0.5rem)",
        boxShadow: "0 20px 25px -5px rgba(0,0,0,0.1)",
        ...styleProps,
      }}>
        <div style={{ fontWeight: 600, fontSize: "1rem", marginBottom: 16 }}>
          Keyboard shortcuts
        </div>
        {Object.entries(grouped).map(([group, items]) => (
          <div key={group} style={{ marginBottom: 16 }}>
            <div style={{
              fontSize: "0.75rem",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              color: "var(--muted-foreground, hsl(0 0% 45%))",
              marginBottom: 8,
            }}>
              {group}
            </div>
            {items.map((s, i) => (
              <div key={i} style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "6px 0",
                fontSize: "0.875rem",
              }}>
                <span>{s.label}</span>
                <kbd style={{
                  fontSize: "0.75rem",
                  padding: "2px 8px",
                  border: "1px solid var(--border, hsl(0 0% 90%))",
                  borderRadius: 3,
                  background: "var(--muted, hsl(0 0% 96%))",
                }}>
                  {s.keys}
                </kbd>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
    </>
  );
}
