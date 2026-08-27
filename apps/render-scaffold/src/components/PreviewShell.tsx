"use client";
import * as React from "react";
import { useRouter, useParams } from "next/navigation";
import { AppShell } from "@tentoroforge/library";

interface NavPage {
  id: string;
  route: string;
  title: string;
}

export interface PreviewShellProps {
  projectId: string;
  navFlow: { pages?: NavPage[] } | null;
  children: React.ReactNode;
}

// Auth routes are rendered bare (no sidebar) via the isBare check in page.tsx.
// We still list them in the sidebar so that navigating *to* them from other
// pages is possible — e.g. the commitbiz-demo flow: Intent Intelligence → Login.
const EXCLUDE_ROUTES = new Set(["/signup", "/forgot-password"]);

export function PreviewShell({ projectId, navFlow, children }: PreviewShellProps) {
  const router = useRouter();
  const params = useParams() as { slug?: string[] };
  const currentSlug = "/" + (params.slug?.join("/") ?? "");

  const pages = (navFlow?.pages ?? []).filter(
    (p) => !p.route.includes("[") && !EXCLUDE_ROUTES.has(p.route)
  );

  const navTo = (route: string) => {
    const path = route === "/" ? `/p/${projectId}` : `/p/${projectId}${route}`;
    router.push(path);
  };

  const sidebar = (
    <nav aria-label="Pages" className="p-3 flex flex-col gap-1">
      <div className="px-2 pb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
        Pages
      </div>
      {pages.map((p) => {
        const isActive =
          currentSlug === p.route ||
          (p.route === "/" && (currentSlug === "/" || currentSlug === "/home"));
        return (
          <button
            key={p.id}
            type="button"
            onClick={() => navTo(p.route)}
            className={`text-left px-3 py-1.5 rounded text-sm transition-colors ${
              isActive
                ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                : "hover:bg-sidebar-accent/40 text-sidebar-foreground"
            }`}
          >
            <span className="block truncate">{p.title || p.id}</span>
            <span className="block text-[10px] font-mono text-muted-foreground truncate">
              {p.route}
            </span>
          </button>
        );
      })}
      {pages.length === 0 && (
        <p className="px-3 text-xs text-muted-foreground">No nav-flow pages.</p>
      )}
    </nav>
  );

  const topbar = (
    <div className="text-sm">
      <span className="font-semibold">Preview</span>
      <span className="ml-2 text-xs text-muted-foreground font-mono">{projectId}</span>
    </div>
  );

  return (
    <AppShell sidebar={sidebar} topbar={topbar}>
      {children}
    </AppShell>
  );
}
