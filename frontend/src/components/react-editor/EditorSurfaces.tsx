"use client";
/**
 * The Editor tab: the website's editor, the phone app's, or a switch between them.
 *
 * Which ones exist is what the application has (`surfaces`): a website only, a phone app only, or both. With both, a switch at
 * the top says which one is on show, and is remembered for the project.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Globe, Loader2, Smartphone } from "lucide-react";

import { cn } from "@/lib/utils";

import { editorApi } from "./api";
import { PhoneEditor } from "./PhoneEditor";
import { ReactEditor } from "./ReactEditor";
import type { Surfaces } from "./types";

export type Surface = "web" | "phone";

const WEB_ONLY: Surfaces = { web: true, phone: false };

/** The surface to show: the one asked for when both exist, else the only one there is. */
export function surfaceToShow(surfaces: Surfaces, chosen: Surface | null): Surface {
  if (surfaces.web && surfaces.phone) return chosen ?? "web";
  return surfaces.phone ? "phone" : "web";
}

const KEY = (projectId: string) => `forge.editor.surface.${projectId}`;

function remembered(projectId: string): Surface | null {
  try {
    const v = window.localStorage.getItem(KEY(projectId));
    return v === "web" || v === "phone" ? v : null;
  } catch { return null; }
}

export function EditorSurfaces({ projectId, onAskSmith }: { projectId: string; onAskSmith: () => void }) {
  const { data: surfaces, isError } = useQuery({
    queryKey: ["editor-surfaces", projectId],
    queryFn: async () => (await editorApi.pages(projectId)).surfaces ?? WEB_ONLY,
    retry: false,
  });
  const [chosen, setChosen] = useState<Surface | null>(null);
  useEffect(() => { setChosen(remembered(projectId)); }, [projectId]);

  const pick = (next: Surface) => {
    setChosen(next);
    try { window.localStorage.setItem(KEY(projectId), next); } catch { /* the choice is just not remembered */ }
  };

  // The pages could not be read: the website's editor says why, in its own words.
  if (isError) return <ReactEditor projectId={projectId} />;
  if (!surfaces) {
    return <div className="flex h-full items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>;
  }
  const surface = surfaceToShow(surfaces, chosen);
  const both = surfaces.web && surfaces.phone;

  return (
    <div className="flex h-full flex-col">
      {both && (
        <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border bg-card px-2" role="tablist" aria-label="What to edit">
          {([["web", "Website", Globe], ["phone", "Phone app", Smartphone]] as const).map(([key, label, Icon]) => (
            <button key={key} role="tab" aria-selected={surface === key} type="button" onClick={() => pick(key)}
              className={cn("inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors",
                surface === key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
              <Icon className="h-3.5 w-3.5" /> {label}
            </button>
          ))}
        </div>
      )}
      <div className="min-h-0 flex-1">
        {surface === "phone" ? <PhoneEditor projectId={projectId} onAskSmith={onAskSmith} /> : <ReactEditor projectId={projectId} />}
      </div>
    </div>
  );
}

export default EditorSurfaces;
