"use client";

// Client-side mount for the editor. Owns the registry + tokens imports
// so server components don't have to pass functions across the RSC boundary.

import { Editor } from "@tentoroforge/editor";
import { libraryRegistry } from "./library-registry";
import { tokens } from "@/theme/tokens";

export function EditorMount({ schemaPath }: { schemaPath: string }) {
  return (
    <Editor
      initialSchemaPath={schemaPath}
      registry={libraryRegistry}
      tokens={tokens}
      apiBaseUrl="/api/editor"
    />
  );
}
