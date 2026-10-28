"use client";

// A tab of the phone's bottom bar, picked in the picture: its name, changed in place. The name is the menu entry's own label (the
// same one the left panel's Menu list changes), so the website's menu and the phone's tab stay one thing.
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { editorApi, failureOf } from "@/components/react-editor/api";
import { toSpec } from "@/components/react-editor/PagesPanel";
import { useEditorStore } from "@/components/react-editor/store";

/** Whether a picked part is a tab of the bar: the tab layout draws it. */
export function isTabPart(source: { file: string } | null | undefined): boolean {
  return /(?:^|\/)app\/\(tabs\)\/_layout\.tsx$/.test((source?.file ?? "").replace(/\\/g, "/"));
}

export function TabRename({ projectId, label }: { projectId: string; label: string }) {
  const navigation = useEditorStore((s) => s.navigation);
  const loadPages = useEditorStore((s) => s.loadPages);
  const entry = navigation?.tree.find((n) => n.label.trim() === label.trim()) ?? null;
  const [typed, setTyped] = useState(label);
  const [seen, setSeen] = useState(label);
  const [busy, setBusy] = useState(false);
  if (seen !== label) { setSeen(label); setTyped(label); }

  if (!entry) {
    return (
      <p className="rounded-md border p-2 text-xs text-muted-foreground" data-testid="tab-rename-fixed">
        This tab is added by the app itself, so its name is not changed here.
      </p>
    );
  }
  const next = typed.trim();
  const save = async () => {
    if (!next || next === entry.label || !navigation) return;
    setBusy(true);
    try {
      await editorApi.setNavigation(projectId, { tree: navigation.tree.map((n) => toSpec(n === entry ? { ...n, label: next } : n)) });
      await loadPages();
      toast.success("Tab renamed.");
    } catch (err) {
      toast.error("Couldn't rename the tab.", { description: failureOf(err).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-1.5 rounded-md border p-2 text-xs" data-testid="tab-rename">
      <label className="text-[11px] text-muted-foreground" htmlFor="tab-name">Tab name</label>
      <input
        id="tab-name"
        value={typed}
        disabled={busy}
        onChange={(e) => setTyped(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void save(); } }}
        className="w-full rounded-md border bg-background px-2 py-1 text-sm"
      />
      {next && next !== entry.label && (
        <Button size="sm" className="h-7 w-full text-xs" disabled={busy} onClick={() => void save()}>
          {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null} Save name
        </Button>
      )}
      <p className="text-[11px] text-muted-foreground">It is the menu entry's name, so the website's menu changes with it.</p>
    </div>
  );
}
