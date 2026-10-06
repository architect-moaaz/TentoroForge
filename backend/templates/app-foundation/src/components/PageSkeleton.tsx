import * as React from "react";

/**
 * The shape of a page while it loads, so the content area shimmers and
 * nothing else moves.
 *
 * A route's `loading.tsx` renders inside the layout above it. The root one
 * (`app/loading.tsx`) sits outside the signed-in shell, so every navigation
 * replaced the whole window — sidebar included — with a full-screen card. The
 * shell's own `loading.tsx` and each coded page's use this instead: the rail
 * stays where it is and only the page area is a placeholder, drawn in the
 * shape of what is coming (a list is rows, a dashboard is tiles and charts,
 * a record is a header and two columns, a form is fields).
 *
 * A server component with no data and no client code: it must render
 * instantly, which is its entire job. Token classes only.
 */
export type SkeletonPattern = "list" | "dashboard" | "record" | "form" | "default";

function Bar({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={"animate-pulse rounded-md bg-muted " + className} />;
}

function Heading({ action = true }: { action?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="space-y-2">
        <Bar className="h-9 w-56" />
        <Bar className="h-4 w-72" />
      </div>
      {action && <Bar className="h-10 w-32 rounded-lg" />}
    </div>
  );
}

function Card({ children, className = "" }: { children?: React.ReactNode; className?: string }) {
  return <div className={"rounded-xl border bg-card p-5 shadow-sm " + className}>{children}</div>;
}

function Body({ pattern }: { pattern: SkeletonPattern }) {
  switch (pattern) {
    case "list":
      return (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <Bar className="h-10 w-full max-w-sm rounded-lg" />
            {[0, 1, 2, 3].map((i) => <Bar key={i} className="h-9 w-28 rounded-full" />)}
          </div>
          <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
            <div className="border-b bg-muted px-5 py-3"><Bar className="h-3 w-1/3 bg-border" /></div>
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-center gap-6 border-b px-5 py-4 last:border-0">
                <Bar className="h-5 w-1/4" />
                <Bar className="h-4 w-1/6" />
                <Bar className="h-6 w-24 rounded-full" />
                <Bar className="ml-auto h-4 w-20" />
              </div>
            ))}
          </div>
        </>
      );
    case "dashboard":
      return (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Card key={i} className="space-y-3"><Bar className="h-4 w-24" /><Bar className="h-9 w-16" /></Card>
            ))}
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            {[0, 1].map((i) => (
              <Card key={i} className="space-y-5 p-6"><Bar className="h-6 w-48" /><Bar className="h-44 w-full" /></Card>
            ))}
          </div>
        </>
      );
    case "record":
      return (
        <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
          <div className="space-y-6">
            <Card className="grid grid-cols-2 gap-6 p-6">
              {[0, 1, 2, 3].map((i) => <div key={i} className="space-y-2"><Bar className="h-3 w-16" /><Bar className="h-5 w-32" /></div>)}
            </Card>
            <Card className="space-y-3 p-6"><Bar className="h-4 w-full" /><Bar className="h-4 w-11/12" /><Bar className="h-4 w-2/3" /></Card>
          </div>
          <Card className="space-y-4"><Bar className="h-6 w-32" /><Bar className="h-10 w-full rounded-lg" /></Card>
        </div>
      );
    case "form":
      return (
        <Card className="space-y-6 p-6 md:p-8">
          <div className="grid gap-6 sm:grid-cols-2">
            {[0, 1, 2, 3].map((i) => <div key={i} className="space-y-2"><Bar className="h-4 w-20" /><Bar className="h-10 w-full rounded-lg" /></div>)}
          </div>
          <div className="space-y-2"><Bar className="h-4 w-20" /><Bar className="h-24 w-full rounded-lg" /></div>
          <Bar className="ml-auto h-10 w-32 rounded-lg" />
        </Card>
      );
    default:
      return (
        <div className="space-y-4">
          {[0, 1, 2].map((i) => <Card key={i} className="space-y-3 p-6"><Bar className="h-5 w-1/3" /><Bar className="h-4 w-full" /><Bar className="h-4 w-4/5" /></Card>)}
        </div>
      );
  }
}

export function PageSkeleton({ pattern = "default" }: { pattern?: SkeletonPattern }) {
  return (
    <div role="status" aria-busy="true" aria-live="polite" className="mx-auto max-w-6xl space-y-6 p-6 md:p-8">
      <span className="sr-only">Loading…</span>
      <Heading action={pattern !== "form" && pattern !== "dashboard"} />
      <Body pattern={pattern} />
    </div>
  );
}

export default PageSkeleton;
