import type * as React from "react";
import { BrandMark, BRAND_LOGO } from "@/components/BrandMark";

/**
 * What a page open to the public renders inside.
 *
 * A public page has no rail on purpose — `project_nav_flow` marks it
 * `shell: false`, because navigation into a product the visitor cannot reach
 * is worse than no navigation. That leaves the page with nothing at all saying
 * whose it is, which is fine for an application that never gave us a mark and
 * wrong for one that did: "put our logo in the corner" means this page most of
 * all. It is the one a stranger sees.
 *
 * So the header appears only when there IS a mark. An application with none
 * keeps the bare page it has always had — this frame is not a redesign of
 * public pages, it is somewhere for a logo to go.
 *
 * Not a link. A mark in the corner usually goes home, and home here is behind
 * the sign-in the visitor does not have.
 */
export function PublicPageFrame({ children }: { children: React.ReactNode }) {
  if (!BRAND_LOGO) return <>{children}</>;
  return (
    <>
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-6xl items-center px-4 py-3 md:px-6">
          {/* No `alt` override: the mark carries the alt text the owner gave,
              and failing that the application's own name from the Blueprint —
              which is a better answer than any placeholder this file could
              hold. */}
          <BrandMark height={28} />
        </div>
      </header>
      {children}
    </>
  );
}
