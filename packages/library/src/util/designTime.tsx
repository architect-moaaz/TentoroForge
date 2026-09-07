"use client";
import * as React from "react";

/**
 * DESIGN TIME — the one signal that says "this tree is being authored, not run".
 *
 * WHY THIS EXISTS
 * ---------------
 * A whole class of components in this library is fed by a runtime the editor
 * does not run:
 *
 *   PresenceIndicator  ← `window.__forgePresenceHook__`, installed by the renderer
 *   UndoManager        ← `CustomEvent("forge:undo:push")` from the mutation queue
 *   TourOverlay        ← a tour that has to be *started* by the app
 *   CartBadge          ← `GET /api/cart`
 *
 * Every one of them ended its setup with `return null`. On the editor canvas
 * that produced a node with `childElementCount === 0`, a **0x0** rect and
 * `display: contents` — invisible, unselectable, and with no box for the
 * empty-node hint overlay to attach to. Three separate audit entries reported
 * it as three separate bugs (Lightbox/Dialog, CartBadge, then PresenceIndicator
 * and UndoManager) because it looks like a different bug each time. It is one:
 * *a component whose only data source is a runtime that is not running has
 * nothing to render, and "nothing" is indistinguishable from "broken".*
 *
 * WHY IT IS A CONTEXT AND NOT A PROP, A GLOBAL, OR A PER-COMPONENT FLAG
 * --------------------------------------------------------------------
 * - A prop would have to be authored on every node, and the author is exactly
 *   the person who cannot see the node to author it.
 * - A `window` global would leak into the generated app the moment one bundle
 *   set it, and the placeholder must NEVER ship: a toast bar that renders a
 *   dashed box in production is a worse bug than the one being fixed.
 * - A per-component `showPlaceholder` prop would be a registry default read as
 *   a command — the trap this codebase keeps falling into.
 *
 * A context defaults to `false`, so **every host that does not opt in keeps the
 * exact previous behaviour** (renders nothing). The editor canvas is the only
 * caller that wraps its tree in `DesignTimeProvider`, so the placeholder exists
 * only where a human is looking at a node they cannot otherwise see.
 */
const DesignTimeContext = React.createContext<boolean>(false);

export function DesignTimeProvider({
  value = true,
  children,
}: {
  value?: boolean;
  children: React.ReactNode;
}) {
  return (
    <DesignTimeContext.Provider value={value}>
      {children}
    </DesignTimeContext.Provider>
  );
}

/** True only inside an authoring surface (the editor canvas). */
export function useDesignTime(): boolean {
  return React.useContext(DesignTimeContext);
}

/**
 * The stand-in a runtime-fed component renders instead of `null` while it is
 * being authored.
 *
 * It is deliberately a real, in-flow, inline-block box rather than a portal or
 * a `position: fixed` overlay — even for UndoManager, whose live rendering IS
 * fixed. The point of the box is to be *where the node is* so the canvas can
 * measure it, select it and draw a hint on it; a fixed placeholder would repeat
 * the original defect one layer up (visible, but not where the node lives).
 *
 * `aria-hidden` + `role="presentation"`: it is scaffolding for the author, not
 * content, and it must not appear to a screen reader as if it were the
 * component's real output.
 */
export function DesignTimePlaceholder({
  component,
  reason,
  minWidth = 140,
}: {
  /** The component's own name, e.g. "UndoManager". */
  component: string;
  /** Why there is nothing to show, in the author's terms. */
  reason: string;
  minWidth?: number;
}) {
  return (
    <span
      data-design-time-placeholder={component}
      role="presentation"
      aria-hidden="true"
      style={{
        display: "inline-flex",
        flexDirection: "column",
        gap: 2,
        minWidth,
        minHeight: 32,
        padding: "6px 10px",
        border: "1px dashed var(--border, hsl(0 0% 80%))",
        borderRadius: "var(--radius-sm, 0.25rem)",
        background: "var(--muted, hsl(0 0% 96%))",
        color: "var(--muted-foreground, hsl(0 0% 45%))",
        fontSize: "0.75rem",
        lineHeight: 1.35,
        boxSizing: "border-box",
      }}
    >
      <span style={{ fontWeight: 600 }}>{component}</span>
      <span>{reason}</span>
    </span>
  );
}

/**
 * The whole pattern in one call, so a component never has to spell the
 * `useDesignTime()` / `return null` branch itself and the four call sites
 * cannot drift apart.
 *
 * Usage — replaces `if (nothingToShow) return null;`:
 *
 *   const idle = useIdleRender("UndoManager", "No undoable action yet…");
 *   if (entries.length === 0) return idle;
 *
 * Returns `null` outside an authoring surface, which is the pre-existing
 * behaviour of every component that adopts it.
 */
export function useIdleRender(
  component: string,
  reason: string,
  minWidth?: number,
): React.ReactElement | null {
  const designTime = useDesignTime();
  if (!designTime) return null;
  return (
    <DesignTimePlaceholder
      component={component}
      reason={reason}
      minWidth={minWidth}
    />
  );
}
