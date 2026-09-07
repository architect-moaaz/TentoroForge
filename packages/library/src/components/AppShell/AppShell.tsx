import * as React from "react";

interface AppShellProps {
  sidebar?: React.ReactNode;
  topbar?: React.ReactNode;
  actions?: React.ReactNode;
  rightRail?: React.ReactNode;
  breakpoint?: "sm" | "md" | "lg" | "none";
  children?: React.ReactNode;
}

// Same table as Split.tsx / Sidebar.tsx so every container in the group agrees
// on what "md" means.
const BP_MIN_PX: Record<"sm" | "md" | "lg", number> = { sm: 640, md: 768, lg: 1024 };

/**
 * AppShell — full-page frame: nav rail, topbar, main, optional right rail.
 *
 * Two fixes over the original (docs/editor-audit/containment.md, responsive
 * finding #8):
 *
 * 1. THE STYLE BLOCK IS SCOPED. It used to be written against a bare
 *    `[data-appshell]` selector while interpolating THIS instance's column
 *    template into it. Two AppShells on one page (a preview shell wrapping a
 *    schema that also uses one — which is exactly what the scaffold does)
 *    therefore emitted two conflicting global rules and the last one mounted
 *    silently decided the layout for both. Scoping to a `useId` makes each
 *    instance own its own columns.
 *
 * 2. `breakpoint` IS A PROP. The rail collapse was hard-coded at 768px (and
 *    the right rail at 1024px) with no way to change it, so the three-column
 *    app the user arranged became a single column on every tablet. `none`
 *    keeps every rail visible at all widths.
 */
/**
 * Scope key for the instance's style block.
 *
 * Deliberately a hash of the layout inputs rather than `useId()`: AppShell has
 * no other reason to be a hook-using component, and it is mounted from the
 * scaffold's own server-rendered shell as well as from schema dispatch. Two
 * AppShells that resolve to the SAME columns and breakpoint can share one rule
 * safely — collision was never the bug; two DIFFERENT configurations writing
 * the same bare `[data-appshell]` selector was.
 */
function scopeKey(input: string): string {
  let h = 5381;
  for (let i = 0; i < input.length; i++) h = ((h << 5) + h + input.charCodeAt(i)) | 0;
  return `s${(h >>> 0).toString(36)}`;
}

export function AppShell({ sidebar, topbar, actions, rightRail, breakpoint, children }: AppShellProps) {
  const bp = breakpoint ?? "md";
  const minPx = bp === "none" ? 0 : (BP_MIN_PX[bp as "sm" | "md" | "lg"] ?? 768);
  // The right rail needs more room than the nav rail, so it has always
  // collapsed one step later. Keep that relationship relative to the chosen
  // breakpoint instead of pinning it to 1024px.
  const railPx = bp === "none" ? 0 : Math.max(minPx + 256, 1024);
  // On mobile (< breakpoint) sidebar + rightRail are hidden, collapsing the grid
  // to a single column so content fills the full viewport width with no overflow.
  const colsDesktop = sidebar
    ? (rightRail ? "240px 1fr 320px" : "240px 1fr")
    : (rightRail ? "1fr 320px" : "1fr");
  const id = scopeKey(`${colsDesktop}|${bp}|${minPx}|${railPx}`);
  // A hidden aside still occupies a grid column unless gridTemplateColumns
  // changes too, so both live in the same scoped style block and the whole
  // responsive collapse works without JS.
  const collapsed = `
        [data-appshell="${id}"] {
          grid-template-columns: 1fr;
          grid-template-rows: auto 1fr;
        }
        [data-appshell="${id}"] > [data-appshell-sidebar] { display: none; }
        [data-appshell="${id}"] > [data-appshell-right] { display: none; }`;
  const expanded = `
        [data-appshell="${id}"] { grid-template-columns: ${colsDesktop}; }
        [data-appshell="${id}"] > [data-appshell-sidebar] { display: block; }`;
  return (
    <>
      <style>{bp === "none" ? `
        [data-appshell="${id}"] {
          grid-template-columns: ${colsDesktop};
          grid-template-rows: auto 1fr;
        }
      ` : `${collapsed}
        @media (min-width: ${minPx}px) {${expanded}
        }
        @media (min-width: ${railPx}px) {
          [data-appshell="${id}"] > [data-appshell-right] { display: block; }
        }
      `}</style>
      <div
        data-appshell={id}
        data-appshell-breakpoint={bp}
        className="grid min-h-screen w-full overflow-x-hidden"
        style={{ gridTemplateRows: "auto 1fr" }}
      >
        {sidebar && (
          <aside
            data-appshell-sidebar
            className="row-span-2 border-e border-border bg-sidebar text-sidebar-foreground overflow-y-auto"
          >
            {sidebar}
          </aside>
        )}
        {(topbar || actions) && (
          <header className="border-b border-border bg-card flex items-center justify-between px-4 py-3 md:px-6">
            <div className="flex-1 min-w-0">{topbar}</div>
            {actions && <div className="flex-shrink-0 ms-4 flex items-center gap-2">{actions}</div>}
          </header>
        )}
        <main className="overflow-y-auto overflow-x-hidden bg-background">
          <div className="px-4 py-4 md:px-6 md:py-6">{children}</div>
        </main>
        {rightRail && (
          <aside
            data-appshell-right
            className="row-span-2 border-s border-border bg-card overflow-y-auto p-4"
          >
            {rightRail}
          </aside>
        )}
      </div>
    </>
  );
}
