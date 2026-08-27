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
import { WorkflowDispatcherProvider } from "@tentoroforge/renderer";
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

  return (
    <EngineProvider designSpec={designSpec} navFlow={navFlow ?? null} cssVarTokens={cssVarTokens ?? null}>
      <WorkflowDispatcherProvider dispatch={authDispatcher}>
        <Engine schema={page} previewData={resolvedPreview} apiBaseUrl="" />
      </WorkflowDispatcherProvider>
    </EngineProvider>
  );
}
