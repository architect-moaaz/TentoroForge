/**
 * Design Editor Hook — loads and saves annotated HTML via the backend API.
 */

import { useCallback, useEffect } from "react";
import { useDesignEditorStore } from "@/stores/design-editor";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

export function useDesignEditor(projectId: string) {
  const {
    setProjectId,
    setPages,
    setStatus,
    setDirty,
    setCompileResult,
    setThemeCSS,
    updatePageHtml,
    pages,
    activePageId,
    isDirty,
  } = useDesignEditorStore();

  // Set project ID on mount
  useEffect(() => {
    setProjectId(projectId);
  }, [projectId, setProjectId]);

  // Load AHTML pages from backend.
  // Always reverse-compiles from current TSX to reflect Live Edit changes.
  // Falls back to IR-based generation if no code exists.
  const loadDesign = useCallback(async () => {
    setStatus("loading", "Syncing design from code...");
    try {
      // Step 1: Reverse-compile current TSX → AHTML (reflects Live Edit changes)
      let generated = false;
      try {
        const codeRes = await fetch(
          `${API_BASE}/api/projects/${projectId}/design/from-code`,
          { method: "POST" },
        );
        if (codeRes.ok) {
          generated = true;
        }
      } catch {
        // from-code not available — fall through
      }

      // Step 2: If no code exists, try generating from IR
      if (!generated) {
        setStatus("loading", "No code found. Generating from IR...");
        try {
          const irRes = await fetch(
            `${API_BASE}/api/projects/${projectId}/design/from-ir`,
            { method: "POST" },
          );
          if (irRes.ok) {
            generated = true;
          }
        } catch {
          console.warn("Could not generate from IR");
        }
      }

      // Step 3: Load whatever design pages are now on disk
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/design`);
      if (!res.ok) {
        throw new Error(`Failed to load design: ${res.status}`);
      }
      const data = await res.json();
      setPages(data.pages || []);
      if (data.themeCSS) setThemeCSS(data.themeCSS);
      setStatus("idle");
      setDirty(false);
    } catch (err) {
      console.error("Failed to load design:", err);
      setStatus("error", String(err));
    }
  }, [projectId, setPages, setStatus, setDirty, setThemeCSS]);

  // Save AHTML pages to backend
  const saveDesign = useCallback(async () => {
    if (!isDirty) return;
    setStatus("saving", "Saving design...");
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/design`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pages }),
      });
      if (!res.ok) {
        throw new Error(`Failed to save design: ${res.status}`);
      }
      setDirty(false);
      setStatus("idle");
    } catch (err) {
      console.error("Failed to save design:", err);
      setStatus("error", String(err));
    }
  }, [projectId, pages, isDirty, setStatus, setDirty]);

  // Compile AHTML → TSX via backend
  const compileDesign = useCallback(async () => {
    setStatus("compiling", "Compiling to TSX...");
    try {
      // Save first if dirty
      if (isDirty) {
        await fetch(`${API_BASE}/api/projects/${projectId}/design`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pages }),
        });
        setDirty(false);
      }

      const res = await fetch(
        `${API_BASE}/api/projects/${projectId}/design/compile`,
        { method: "POST" },
      );
      if (!res.ok) {
        throw new Error(`Compilation failed: ${res.status}`);
      }
      const result = await res.json();
      setCompileResult(result);
      setStatus("idle");
      return result;
    } catch (err) {
      console.error("Compilation failed:", err);
      setStatus("error", String(err));
      return null;
    }
  }, [projectId, pages, isDirty, setStatus, setDirty, setCompileResult]);

  return {
    loadDesign,
    saveDesign,
    compileDesign,
    updatePageHtml,
    activePage: pages.find((p) => p.pageId === activePageId),
    pages,
  };
}
