"use client";

/**
 * Discovery (§108, §109) — where an application starts.
 *
 * §108 opens on one question: "What would you like to build?" §109 then gives
 * Smith the primary interface for early requirements, and says the product
 * should not look like an IDE at this stage. So this page is a prompt, and
 * nothing else on screen.
 *
 * It exists because the workspace needs a project and nothing created one on
 * the Blueprint path. `/blueprint/[projectId]` was reachable only by knowing
 * an id, which meant the engine had a front door and no doorstep.
 *
 * §16 — clarification comes from Smith, not from this form. The alternative is
 * a wizard that asks for a domain, an industry and a persona before anyone has
 * said what they want, which is the IDE §109 warns against. The description is
 * the whole input; Smith asks for what it still needs once it has read it.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ArrowRight } from "lucide-react";
import { api } from "@/lib/api";

interface Org {
  id: string;
  name: string;
}

interface Project {
  id: string;
}

export default function NewApplicationPage() {
  const router = useRouter();
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const begin = async () => {
    const text = description.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);

    try {
      // A project belongs to an org, and a signed-in user has at least one.
      // Taking the first is a placeholder for an org picker, not a decision —
      // it is wrong for anyone who belongs to several.
      const orgs = await api.get<Org[]>("/api/orgs");
      if (!orgs.length) {
        setError("No organisation on this account — create one first.");
        setBusy(false);
        return;
      }

      // The name is the first line of what they typed, trimmed to something a
      // project card can show. The description carries the whole thing, and it
      // is what Smith reads.
      const name = text.split("\n")[0].slice(0, 60) || "New application";
      const project = await api.post<Project>(
        `/api/orgs/${orgs[0].id}/projects`,
        { name, description: text },
      );

      // The workspace picks the conversation up from here: §25 holds at the
      // definition, so nothing is built until it has been approved.
      router.push(
        `/blueprint/${project.id}?brief=${encodeURIComponent(text)}`,
      );
    } catch (e) {
      setError(
        (e as Error).message || "Could not start — is the session still valid?",
      );
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center px-6 py-16">
      <h1 className="text-center text-2xl font-semibold">
        What would you like to build?
      </h1>
      <p className="mt-2 text-center text-sm text-muted-foreground">
        Describe it in your own words. Smith will ask about anything it needs
        before building.
      </p>

      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void begin();
          }
        }}
        rows={6}
        autoFocus
        disabled={busy}
        placeholder="A recruitment tracker for a staffing agency: recruiters post roles, track candidates through interview stages, and schedule interviews."
        className="mt-8 w-full resize-none rounded-lg border bg-background p-4 text-sm outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
      />

      {error && (
        <p className="mt-3 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      <button
        onClick={() => void begin()}
        disabled={busy || !description.trim()}
        className="mt-4 flex items-center justify-center gap-2 self-end rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40"
      >
        {busy ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Starting…
          </>
        ) : (
          <>
            Start
            <ArrowRight className="h-4 w-4" />
          </>
        )}
      </button>

      {/*
        §108 lists five creation modes — describe, Figma, upload requirements,
        screenshot, import. Only the first reaches the Blueprint engine today:
        the Figma path (§41–55) produces a legacy app and never writes to the
        Blueprint, so offering it here would promise something that does not
        happen. Listed as unbuilt rather than shown as broken.
      */}
      <p className="mt-10 text-center text-xs text-muted-foreground">
        Figma, requirements upload, screenshot and import are not yet connected
        to the Blueprint engine.
      </p>
    </main>
  );
}
