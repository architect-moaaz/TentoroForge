"use client";

/**
 * UnifiedEditor — two top-level modes.
 *
 * Live  →  Running Next.js iframe (style tweaks, text, AI edits)
 * Build →  Integrated GrapeJS canvas + IR structure tree + data/workflow binding
 */

import React, { useState, useCallback } from "react";
import {
  Eye, Layers, Loader2, AlertTriangle, CheckCircle2, XCircle,
} from "lucide-react";
import { VisualEditor } from "@/components/visual-editor/VisualEditor";
import { DesignEditor } from "@/components/design-editor/DesignEditor";
import { useAutoFix } from "@/hooks/useAutoFix";

type Mode = "live" | "build";

// ---------------------------------------------------------------------------
// Mode bar
// ---------------------------------------------------------------------------

interface ModeBarProps {
  mode: Mode;
  onSwitch: (m: Mode) => void;
}

function ModeBar({ mode, onSwitch }: ModeBarProps) {
  return (
    <div className="flex items-center border-b bg-background shrink-0">
      <button
        onClick={() => onSwitch("live")}
        className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
          mode === "live"
            ? "border-primary text-foreground bg-muted/40"
            : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/20"
        }`}
      >
        <Eye className={`h-3.5 w-3.5 ${mode === "live" ? "text-emerald-600" : ""}`} />
        Live Edit
      </button>

      <button
        onClick={() => onSwitch("build")}
        className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
          mode === "build"
            ? "border-primary text-foreground bg-muted/40"
            : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/20"
        }`}
      >
        <Layers className={`h-3.5 w-3.5 ${mode === "build" ? "text-blue-600" : ""}`} />
        Build & Design
      </button>

      <span className="ml-auto mr-3 text-xs text-muted-foreground hidden md:inline-block">
        {mode === "live" && "Edit the running app — AI edits, style tweaks, text changes"}
        {mode === "build" && "Structure tree · drag-and-drop canvas · data binding · workflows"}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Unified Editor
// ---------------------------------------------------------------------------

interface UnifiedEditorProps {
  projectId: string;
}

export function UnifiedEditor({ projectId }: UnifiedEditorProps) {
  const [mode, setMode] = useState<Mode>("live");
  const [activeRoute, setActiveRoute] = useState<string | undefined>();
  const { autoFix, dismissAutoFix } = useAutoFix(projectId);

  // Lazy-mount — each canvas initialises once and stays alive via display:none
  const [mounted, setMounted] = useState({ live: true, build: false });

  const switchMode = useCallback((m: Mode) => {
    setMode(m);
    setMounted((prev) => (prev[m] ? prev : { ...prev, [m]: true }));
  }, []);

  // Build/Design → Live: after compiling, show the compiled route in Live mode
  const handleCompiled = useCallback((route: string) => {
    setActiveRoute(route);
    switchMode("live");
  }, [switchMode]);

  // Live → Build: "Edit Structure" button in the Live toolbar
  const handleEditStructure = useCallback(() => {
    switchMode("build");
  }, [switchMode]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <ModeBar mode={mode} onSwitch={switchMode} />

      {/* Auto-Fix Banner — visible in both modes */}
      {autoFix.status !== "idle" && (
        <div
          className={`flex items-center gap-2 px-4 py-2 text-xs font-medium shrink-0 ${
            autoFix.status === "detected"
              ? "bg-amber-50 text-amber-800 border-b border-amber-200"
              : autoFix.status === "fixing"
                ? "bg-blue-50 text-blue-800 border-b border-blue-200"
                : autoFix.status === "fixed"
                  ? "bg-emerald-50 text-emerald-800 border-b border-emerald-200"
                  : "bg-red-50 text-red-800 border-b border-red-200"
          }`}
        >
          {autoFix.status === "detected" && (
            <AlertTriangle className="h-3.5 w-3.5 text-amber-600 shrink-0" />
          )}
          {autoFix.status === "fixing" && (
            <Loader2 className="h-3.5 w-3.5 text-blue-600 animate-spin shrink-0" />
          )}
          {autoFix.status === "fixed" && (
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
          )}
          {autoFix.status === "failed" && (
            <XCircle className="h-3.5 w-3.5 text-red-600 shrink-0" />
          )}
          <span className="flex-1 truncate">{autoFix.message}</span>
          {autoFix.status === "fixing" && (
            <span className="text-[10px] opacity-70">
              Attempt {autoFix.attempt}/{autoFix.maxAttempts}
            </span>
          )}
          {(autoFix.status === "fixed" || autoFix.status === "failed") && (
            <button
              onClick={dismissAutoFix}
              className="text-[10px] underline hover:no-underline opacity-70"
            >
              Dismiss
            </button>
          )}
        </div>
      )}

      <div className="relative flex-1 overflow-hidden">
        {/* Live Edit */}
        <div
          className="absolute inset-0 overflow-hidden"
          style={{ display: mode === "live" ? undefined : "none" }}
        >
          {mounted.live && (
            <VisualEditor
              projectId={projectId}
              initialRoute={activeRoute}
              onEditStructure={handleEditStructure}
            />
          )}
        </div>

        {/* Build & Design (integrated GrapeJS + IR tree) */}
        <div
          className="absolute inset-0 overflow-hidden"
          style={{ display: mode === "build" ? undefined : "none" }}
        >
          {mounted.build && (
            <DesignEditor
              projectId={projectId}
              onCompiled={handleCompiled}
            />
          )}
        </div>
      </div>
    </div>
  );
}
