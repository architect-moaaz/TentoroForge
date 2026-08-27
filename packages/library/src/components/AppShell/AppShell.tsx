import * as React from "react";

interface AppShellProps {
  sidebar?: React.ReactNode;
  topbar?: React.ReactNode;
  actions?: React.ReactNode;
  rightRail?: React.ReactNode;
  children?: React.ReactNode;
}

export function AppShell({ sidebar, topbar, actions, rightRail, children }: AppShellProps) {
  // On mobile (<md) sidebar + rightRail are hidden, collapsing the grid to a
  // single column so content fills the full viewport width with no overflow.
  const colsDesktop = sidebar
    ? (rightRail ? "240px 1fr 320px" : "240px 1fr")
    : (rightRail ? "1fr 320px" : "1fr");
  // CSS approach: use a responsive class for the aside and let the grid
  // flow naturally — the hidden aside still occupies a grid column on small
  // screens unless we also change gridTemplateColumns. We use a style tag
  // scoped to data-appshell so the responsive collapse works without JS.
  return (
    <>
      <style>{`
        [data-appshell] {
          grid-template-columns: 1fr;
          grid-template-rows: auto 1fr;
        }
        @media (min-width: 768px) {
          [data-appshell] {
            grid-template-columns: ${colsDesktop};
          }
        }
        [data-appshell] > [data-appshell-sidebar] {
          display: none;
        }
        @media (min-width: 768px) {
          [data-appshell] > [data-appshell-sidebar] {
            display: block;
          }
        }
        [data-appshell] > [data-appshell-right] {
          display: none;
        }
        @media (min-width: 1024px) {
          [data-appshell] > [data-appshell-right] {
            display: block;
          }
        }
      `}</style>
      <div
        data-appshell
        className="grid min-h-screen w-full overflow-x-hidden"
        style={{ gridTemplateRows: "auto 1fr" }}
      >
        {sidebar && (
          <aside
            data-appshell-sidebar
            className="row-span-2 border-r border-border bg-sidebar text-sidebar-foreground overflow-y-auto"
          >
            {sidebar}
          </aside>
        )}
        {(topbar || actions) && (
          <header className="border-b border-border bg-card flex items-center justify-between px-4 py-3 md:px-6">
            <div className="flex-1 min-w-0">{topbar}</div>
            {actions && <div className="flex-shrink-0 ml-4 flex items-center gap-2">{actions}</div>}
          </header>
        )}
        <main className="overflow-y-auto overflow-x-hidden bg-background">
          <div className="px-4 py-4 md:px-6 md:py-6">{children}</div>
        </main>
        {rightRail && (
          <aside
            data-appshell-right
            className="row-span-2 border-l border-border bg-card overflow-y-auto p-4"
          >
            {rightRail}
          </aside>
        )}
      </div>
    </>
  );
}
