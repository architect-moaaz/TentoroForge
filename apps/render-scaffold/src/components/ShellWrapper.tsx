"use client";

/**
 * ShellWrapper — client-side shell composition for schema-driven app shells.
 *
 * Renders the shell schema (top nav, branding) via SchemaRenderer with the
 * page content provided through PageOutletContext. The PageOutlet node in the
 * shell schema reads from the context and renders the page body in-place.
 *
 * Usage (in page.tsx server component):
 *   <ShellWrapper
 *     shell={shellSchema}
 *     page={pageSchema}
 *     register={register}
 *     tokens={tokens}
 *     previewData={previewData}
 *     projectId={projectId}
 *     navFlow={navFlow}
 *   />
 */

import * as React from "react";
import { PageOutletContext } from "@tentoroforge/renderer";
import { SchemaRendererWrapper } from "./SchemaRendererWrapper";

interface ShellWrapperProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  shell: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  page: any;
  register: string;
  tokens: Record<string, Record<string, string>>;
  previewData?: Record<string, unknown>;
  projectId?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  navFlow?: any;
  cssVarTokens?: Record<string, unknown>;
}

export function ShellWrapper({
  shell,
  page,
  register,
  tokens,
  previewData,
  projectId,
  navFlow,
  cssVarTokens,
}: ShellWrapperProps) {
  // Render the page schema as a ReactNode. This becomes the value provided
  // via PageOutletContext so the PageOutlet node in the shell renders it
  // in the correct location (below the top nav).
  const pageContent = (
    <SchemaRendererWrapper
      page={page}
      register={register}
      tokens={tokens}
      previewData={previewData}
      projectId={projectId}
      navFlow={navFlow}
      cssVarTokens={cssVarTokens}
    />
  );

  return (
    <PageOutletContext.Provider value={pageContent}>
      <SchemaRendererWrapper
        page={shell}
        register={register}
        tokens={tokens}
        previewData={previewData}
        projectId={projectId}
        navFlow={navFlow}
        cssVarTokens={cssVarTokens}
      />
    </PageOutletContext.Provider>
  );
}
