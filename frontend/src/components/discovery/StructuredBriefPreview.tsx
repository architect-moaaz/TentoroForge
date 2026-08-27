"use client";

/**
 * JT-T9 — Structured brief preview.
 *
 * Shows the transformer's extracted actors + user journeys BEFORE the user
 * commits to project creation. Read-only for this iteration: the user can
 * approve (proceed to convert) or reject (continue the discovery
 * conversation to correct what was extracted). Inline editing is a
 * follow-up; the whole preview loop is worth having even without it,
 * because catching wrong intent here is dramatically cheaper than
 * catching it in the plan chip.
 */
import { Users, MapPin, CheckCircle2, MessageSquare } from "lucide-react";

interface BriefActorOnboarding {
  source: string;
  invited_by?: string;
  gate?: string;
}

interface BriefActor {
  name: string;
  role: string;
  onboarding?: BriefActorOnboarding;
  responsibilities?: string[];
}

interface BriefJourneyStep {
  actor: string;
  action: string;
  page: string;
  workflow?: string;
  outcome: string;
}

interface BriefJourney {
  name: string;
  primary_actor: string;
  trigger?: string;
  steps: BriefJourneyStep[];
}

export interface StructuredBrief {
  overview?: string;
  domain?: string;
  actors?: BriefActor[];
  user_journeys?: BriefJourney[];
  domain_terms?: string[];
  open_questions?: string[];
}

interface Props {
  brief: StructuredBrief;
  isEmpty?: boolean;
  onApprove: () => void;
  onAdjust: () => void;
  disabled?: boolean;
}

export function StructuredBriefPreview({
  brief,
  isEmpty,
  onApprove,
  onAdjust,
  disabled,
}: Props) {
  if (isEmpty) {
    return (
      <div className="my-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        The transformer couldn&apos;t extract actors or journeys from the
        conversation yet. Continue answering the discovery agent&apos;s
        questions — once you&apos;ve named the actors and walked through
        the main task, try again.
      </div>
    );
  }

  return (
    <div className="my-2 rounded-lg border bg-card shadow-sm">
      {/* Header */}
      <div className="border-b bg-gradient-to-r from-emerald-50 to-cyan-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          <h3 className="text-sm font-semibold text-emerald-900">
            Ready to build — review the extracted structure
          </h3>
        </div>
        {brief.overview && (
          <p className="mt-1 text-xs text-muted-foreground">{brief.overview}</p>
        )}
      </div>

      <div className="divide-y text-xs">
        {/* Actors */}
        {brief.actors && brief.actors.length > 0 && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <Users className="h-3 w-3" />
              Actors ({brief.actors.length})
            </div>
            <div className="space-y-1">
              {brief.actors.map((a) => {
                const src = a.onboarding?.source;
                const badge =
                  src === "self_signup"
                    ? { label: "self signup", cls: "bg-emerald-50 text-emerald-700" }
                    : src === "invited_by"
                    ? {
                        label: `invited by ${a.onboarding?.invited_by ?? "?"}`,
                        cls: "bg-amber-50 text-amber-700",
                      }
                    : src === "platform_org"
                    ? { label: "platform org", cls: "bg-sky-50 text-sky-700" }
                    : { label: src ?? "unknown", cls: "bg-muted text-muted-foreground" };
                return (
                  <div key={a.role || a.name} className="flex items-center gap-2">
                    <span className="font-medium">{a.name}</span>
                    <code className="rounded bg-muted px-1 py-0.5 text-[10px]">
                      {a.role}
                    </code>
                    <span className={`rounded px-2 py-0.5 text-[10px] ${badge.cls}`}>
                      {badge.label}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Journeys */}
        {brief.user_journeys && brief.user_journeys.length > 0 && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <MapPin className="h-3 w-3" />
              User Journeys ({brief.user_journeys.length})
            </div>
            <div className="space-y-2">
              {brief.user_journeys.map((j) => (
                <div key={j.name} className="rounded border bg-muted/30 p-2">
                  <div className="text-[11px] font-semibold">
                    {j.name}{" "}
                    <span className="ml-1 font-normal text-muted-foreground">
                      (primary: {j.primary_actor})
                    </span>
                  </div>
                  {j.trigger && (
                    <div className="mt-0.5 text-[10px] italic text-muted-foreground">
                      trigger: {j.trigger}
                    </div>
                  )}
                  <ol className="mt-1 space-y-0.5">
                    {(j.steps ?? []).map((s, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-1.5 text-[10px]">
                        <span className="text-muted-foreground">{i + 1}.</span>
                        <span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">
                          {s.actor}
                        </span>
                        <span>{s.action}</span>
                        <code className="rounded bg-muted px-1 py-0.5">{s.page}</code>
                        {s.workflow && (
                          <span className="rounded bg-purple-50 px-1.5 py-0.5 text-purple-700">
                            via {s.workflow}
                          </span>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Open questions */}
        {brief.open_questions && brief.open_questions.length > 0 && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 font-medium text-muted-foreground">
              Open questions ({brief.open_questions.length}) — the planner will resolve these
            </div>
            <ul className="space-y-0.5 text-[10px]">
              {brief.open_questions.map((q, i) => (
                <li key={i}>• {q}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 border-t px-4 py-3">
        <button
          onClick={onApprove}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50"
        >
          <CheckCircle2 className="h-3 w-3" />
          Approve — create project
        </button>
        <button
          onClick={onAdjust}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          <MessageSquare className="h-3 w-3" />
          Something&apos;s off — keep talking
        </button>
      </div>
    </div>
  );
}
