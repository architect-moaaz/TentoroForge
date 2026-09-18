import type * as React from "react";
import Link from "next/link";
import { BrandMark, BRAND_LOGO } from "@/components/BrandMark";
import { PublicNavLinks } from "@/components/PublicNavLinks";
import { PUBLIC_NAV } from "@/contracts/public-nav";

/**
 * What a page open to the public renders inside — every one of them, coded or
 * laid out, so they read as one application.
 *
 * A public page has no rail: the sidebar belongs to the signed-in application,
 * and a rail into pages the visitor cannot reach is worse than none. But an
 * application that IS public — a directory, an intake form and its list — was
 * left with no navigation at all, and its pages each drew their own, or none
 * (2g13o6yz, 2026-09-19). So the frame carries one header: the application's
 * mark or name, the public pages a visitor can move between
 * (`contracts/public-nav.ts`, projected from the Blueprint), and a way to sign
 * in when there is more behind it. One public page, and no mark: the bare page,
 * as before.
 */
export function PublicPageFrame({ children }: { children: React.ReactNode }) {
  const { appName, items, signIn } = PUBLIC_NAV;
  const hasNav = items.length > 1;
  if (!BRAND_LOGO && !hasNav && !signIn) return <>{children}</>;
  return (
    <>
      <header className="sticky top-0 z-40 border-b border-border bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-4 md:px-6">
          <Link href={items[0]?.route ?? "/"} className="flex shrink-0 items-center gap-2">
            {BRAND_LOGO ? (
              <BrandMark height={28} />
            ) : (
              <span className="text-sm font-semibold tracking-tight text-foreground">{appName}</span>
            )}
          </Link>
          {hasNav && <PublicNavLinks items={items} />}
          {signIn && (
            <Link
              href="/login"
              className="ml-auto shrink-0 rounded-md border border-input px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted"
            >
              Sign in
            </Link>
          )}
        </div>
      </header>
      {/* The page's width and outer padding, set once for every public page —
          the same measure the signed-in shell gives its pages. A page fills
          it; it does not choose its own. */}
      <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-6 md:py-8">{children}</div>
    </>
  );
}
