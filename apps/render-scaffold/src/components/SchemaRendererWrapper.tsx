"use client";

/**
 * Client boundary for the scaffold's schema rendering. Was a ~250-line
 * wrapper with inline buildRegistry / data-resolution / renderNode dispatch;
 * now collapses to EngineProvider + Engine since @tentoroforge/engine
 * encapsulates the same logic.
 *
 * Library components (Card, Heading, etc.) call React hooks — this is
 * the "use client" boundary that lets that work inside Next.js.
 *
 * Inputs are still plain-serialisable (page JSON, register string,
 * tokens map, previewData) because the parent server component
 * cannot pass functions across the server→client boundary.
 */

import * as React from "react";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import type { DesignSpec } from "@tentoroforge/engine";
import { NavigatorProvider, WorkflowDispatcherProvider } from "@tentoroforge/renderer";
import { useRouter } from "next/navigation";
import { resolvePreviewSync } from "@/lib/resolvePreviewSync";

interface SchemaRendererWrapperProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  page: any;
  register: string;
  tokens: Record<string, Record<string, string>>;
  /** Fixture data fetched server-side from /api/_debug/preview-data/{projectId}.
   *  When present, all {{...}} bindings in the schema resolve to realistic values
   *  instead of displaying as literal template strings. */
  previewData?: Record<string, unknown>;
  /** Optional project id; when present, Hero/Section/EmptyStateRich receive
   *  __illustrationBasePath=/p/<projectId>/illustrations as a default prop so
   *  IllustrationResolver resolves slugs against the scaffold's per-project
   *  asset route rather than the standalone /illustrations default. */
  projectId?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  navFlow?: any;
  /** Raw project tokens.custom.json tree. Passed to EngineProvider so it can
   *  inject CSS custom properties (--color-primary-500, etc.) and shadcn
   *  semantic vars (--primary, --background, etc.) that make bg-primary and
   *  similar Tailwind utilities resolve to the project's actual brand colors.
   *  Without this the preview renders with no brand colours (unstyled buttons). */
  cssVarTokens?: Record<string, unknown>;
}


export function SchemaRendererWrapper({
  page,
  register,
  tokens,
  previewData,
  projectId,
  navFlow,
  cssVarTokens,
}: SchemaRendererWrapperProps) {
  // Synthetic designSpec from the discrete scaffold inputs. EngineProvider
  // reads register + tokens from this object; Engine reads illustrationBasePath
  // to thread the per-project illustration asset route into buildDefaultRegistry.
  const designSpec = React.useMemo<DesignSpec>(
    () => ({
      register,
      tokens: tokens as Record<string, unknown>,
      ...(projectId
        ? { illustrationBasePath: `/p/${projectId}/illustrations` }
        : {}),
    }),
    [register, tokens, projectId],
  );

  const resolvedPreview = React.useMemo(
    () => resolvePreviewSync(page, previewData),
    [page, previewData],
  );

  // Default auth workflow dispatcher: reads nav-flow's post_login_redirect /
  // post_logout_redirect so "Sign in" / "Sign out" buttons navigate correctly
  // without hardcoding any route in the schema.
  const authDispatcher = React.useCallback(
    (workflow: string, _args?: Record<string, unknown>) => {
      if (workflow === "auth.signIn" || workflow === "auth.signUp") {
        const target = (navFlow as any)?.post_login_redirect ?? "/";
        const base = projectId ? `/p/${projectId}` : "";
        window.location.assign(`${base}${target}`);
        return;
      }
      if (workflow === "auth.signOut") {
        const target = (navFlow as any)?.post_logout_redirect ?? "/login";
        const base = projectId ? `/p/${projectId}` : "";
        window.location.assign(`${base}${target}`);
        return;
      }
      // Unhandled workflow — log only, do not throw.
      console.log("[workflow]", workflow, _args);
    },
    [navFlow, projectId],
  );

  // THE PREVIEW SERVES AN APP UNDER /p/<id>. Every navigation the app makes —
  // a Button's nav trigger, a Table row's Edit, a row link — is an app-relative
  // route ("/nurse-registration/<id>") that the library hands to the host's
  // Navigator. Without one here the default navigator did a hard assign of
  // that route, escaping the base path: a row's Edit reached a 404 in the
  // preview while the standalone app was fine.
  // Next's `basePath` ("/p") is prepended by the router itself; the app's
  // routes live at `/<projectId>/<slug>` beneath it.
  const router = useRouter();
  const navigator = React.useMemo(() => {
    const base = projectId ? `/${projectId}` : "";
    const withBase = (url: string) =>
      base && url.startsWith("/") && !url.startsWith(`${base}/`) && url !== base
        ? `${base}${url === "/" ? "" : url}`
        : url;
    return {
      push: (url: string) => router.push(withBase(url)),
      replace: (url: string) => router.replace(withBase(url)),
      back: () => router.back(),
      refresh: () => router.refresh(),
    };
  }, [router, projectId]);

  return (
    <EngineProvider designSpec={designSpec} navFlow={navFlow ?? null} cssVarTokens={cssVarTokens ?? null}>
      <NavigatorProvider value={navigator}>
        <WorkflowDispatcherProvider dispatch={authDispatcher}>
          <Engine schema={page} previewData={resolvedPreview} apiBaseUrl="" />
        </WorkflowDispatcherProvider>
      </NavigatorProvider>
    </EngineProvider>
  );
}
