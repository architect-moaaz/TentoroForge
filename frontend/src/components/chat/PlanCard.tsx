"use client";

import { useState } from "react";
import {
  Database,
  Layout,
  GitBranch,
  Shield,
  Scroll,
  Swords,
  MessageSquare,
  Users,
  MapPin,
} from "lucide-react";
import { AdjustPanel } from "./AdjustPanel";

interface PlanField {
  name: string;
  type: string;
  primaryKey?: boolean;
  nullable?: boolean;
}

interface PlanDataModel {
  name: string;
  fields: PlanField[];
  indexes?: string[];
}

interface PlanPage {
  route: string;
  name: string;
  description: string;
}

interface PlanWorkflow {
  name: string;
  trigger: string;
  steps: (string | { name?: string; action?: string; id?: string; type?: string })[];
}

interface PlanAccessControl {
  roles: string[];
  rules: string[];
}

interface PlanActorOnboarding {
  source: "self_signup" | "invited_by" | "platform_org" | string;
  invited_by?: string;
  gate?: string;
}

interface PlanActor {
  name: string;
  role: string;
  onboarding?: PlanActorOnboarding;
  responsibilities?: string[];
}

interface PlanJourneyStep {
  actor: string;
  action: string;
  page: string;
  workflow?: string;
  outcome: string;
}

interface PlanJourney {
  name: string;
  primary_actor: string;
  trigger?: string;
  steps: PlanJourneyStep[];
}

interface Plan {
  module_name?: string;
  description?: string;
  data_models?: PlanDataModel[];
  relations?: { from: string; to: string; type: string }[];
  pages?: PlanPage[];
  api_routes?: { method: string; path: string; description: string }[];
  workflows?: PlanWorkflow[];
  seed_data?: string;
  actors?: PlanActor[];
  user_journeys?: PlanJourney[];
  access_control?: PlanAccessControl;
}

interface PlanCardProps {
  plan: Plan;
  onApprove: () => void;
  /** Legacy free-text fallback. When `projectId` is provided the card
   *  opens the inline AdjustPanel instead and this becomes a no-op. */
  onAdjust: () => void;
  /** Enables the reliable in-place Adjust-strategy flow. Without it the
   *  Adjust button falls back to `onAdjust` (free-text chat). */
  projectId?: string;
  /** Called with the new plan after each Adjust turn. Parent should
   *  swap this card's `plan` so users see the current state. */
  onPlanUpdated?: (newPlan: Plan) => void;
  disabled?: boolean;
}

export function PlanCard({
  plan,
  onApprove,
  onAdjust,
  projectId,
  onPlanUpdated,
  disabled,
}: PlanCardProps) {
  const [adjustOpen, setAdjustOpen] = useState(false);
  const canAdjustInline = Boolean(projectId && onPlanUpdated);
  const handleAdjust = () => {
    if (canAdjustInline) setAdjustOpen(true);
    else onAdjust();
  };
  return (
    <div className="my-2 rounded-lg border bg-card shadow-sm">
      {/* Header */}
      <div className="border-b bg-gradient-to-r from-blue-50 to-indigo-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <Scroll className="h-4 w-4 text-indigo-500" />
          <h3 className="font-semibold text-sm text-indigo-900">
            {plan.module_name || "Quest Briefing"}
          </h3>
        </div>
        {plan.description && (
          <p className="mt-1 text-xs text-muted-foreground">
            {plan.description}
          </p>
        )}
      </div>

      <div className="divide-y text-xs">
        {/* Data Models */}
        {plan.data_models && plan.data_models.length > 0 && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <Database className="h-3 w-3" />
              Data Models ({plan.data_models.length})
            </div>
            <div className="flex flex-wrap gap-1.5">
              {plan.data_models.map((model) => (
                <span
                  key={model.name}
                  className="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5"
                >
                  {model.name}
                  <span className="text-muted-foreground">
                    ({model.fields.length} fields)
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Pages */}
        {plan.pages && plan.pages.length > 0 && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <Layout className="h-3 w-3" />
              Pages ({plan.pages.length})
            </div>
            <div className="space-y-1">
              {plan.pages.map((page) => (
                <div key={page.route} className="flex items-center gap-2">
                  <code className="rounded bg-muted px-1 py-0.5 text-[10px]">
                    {page.route}
                  </code>
                  <span className="text-muted-foreground truncate">
                    {page.description}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Workflows */}
        {plan.workflows && plan.workflows.length > 0 && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <GitBranch className="h-3 w-3" />
              Workflows ({plan.workflows.length})
            </div>
            <div className="space-y-1">
              {plan.workflows.map((wf, idx) => (
                <div key={wf.name || wf.id || idx} className="flex items-center gap-1.5">
                  <span className="font-medium">{wf.name}</span>
                  <span className="text-muted-foreground">—</span>
                  <span className="text-muted-foreground">
                    {(wf.steps ?? []).map((s) => {
                      if (typeof s === "string") return s;
                      const label = s.name || s.action || s.id || s.type;
                      return label ? label.replace(/_/g, " ") : "—";
                    }).join(" → ") || (wf.purpose ?? "—")}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* User Journeys — JT-T11: each step names the actor + page + optional workflow */}
        {plan.user_journeys && plan.user_journeys.length > 0 && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <MapPin className="h-3 w-3" />
              User Journeys ({plan.user_journeys.length})
            </div>
            <div className="space-y-2">
              {plan.user_journeys.map((journey) => (
                <div key={journey.name} className="rounded border bg-muted/30 p-2">
                  <div className="flex items-center gap-2 text-[11px] font-semibold">
                    <span>{journey.name}</span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
                      primary: {journey.primary_actor}
                    </span>
                  </div>
                  {journey.trigger && (
                    <div className="mt-0.5 text-[10px] text-muted-foreground italic">
                      trigger: {journey.trigger}
                    </div>
                  )}
                  <ol className="mt-1 space-y-0.5">
                    {(journey.steps ?? []).map((step, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-1.5 text-[10px]">
                        <span className="text-muted-foreground">{i + 1}.</span>
                        <span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">
                          {step.actor}
                        </span>
                        <span>{step.action}</span>
                        <code className="rounded bg-muted px-1 py-0.5">
                          {step.page}
                        </code>
                        {step.workflow && (
                          <span className="rounded bg-purple-50 px-1.5 py-0.5 text-purple-700">
                            via {step.workflow}
                          </span>
                        )}
                        {step.outcome && (
                          <span className="text-muted-foreground">→ {step.outcome}</span>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Actors & Onboarding — slice B: how each human role gets into the app */}
        {plan.actors && plan.actors.length > 0 && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <Users className="h-3 w-3" />
              Actors & Onboarding ({plan.actors.length})
            </div>
            <div className="space-y-1">
              {plan.actors.map((actor) => {
                const src = actor.onboarding?.source;
                const badge =
                  src === "self_signup"
                    ? { label: "self signup", cls: "bg-emerald-50 text-emerald-700" }
                    : src === "invited_by"
                    ? {
                        label: `invited by ${actor.onboarding?.invited_by ?? "?"}`,
                        cls: "bg-amber-50 text-amber-700",
                      }
                    : src === "platform_org"
                    ? { label: "platform org", cls: "bg-sky-50 text-sky-700" }
                    : { label: src ?? "unknown", cls: "bg-muted text-muted-foreground" };
                return (
                  <div key={actor.role || actor.name} className="flex items-center gap-2">
                    <span className="font-medium">{actor.name}</span>
                    <code className="rounded bg-muted px-1 py-0.5 text-[10px]">
                      {actor.role}
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

        {/* Access Control */}
        {plan.access_control && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <Shield className="h-3 w-3" />
              Access Roles
            </div>
            <div className="flex flex-wrap gap-1.5">
              {plan.access_control.roles.map((role) => (
                <span
                  key={role}
                  className="rounded bg-blue-50 px-2 py-0.5 text-blue-700"
                >
                  {role}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 border-t px-4 py-3">
        <button
          onClick={onApprove}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 rounded-md bg-gradient-to-r from-amber-500 to-amber-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:from-amber-600 hover:to-amber-700 disabled:opacity-50"
        >
          <Swords className="h-3 w-3" />
          Begin Quest
        </button>
        <button
          onClick={handleAdjust}
          disabled={disabled || adjustOpen}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          <MessageSquare className="h-3 w-3" />
          Adjust strategy
        </button>
      </div>
      {adjustOpen && projectId && onPlanUpdated && (
        <AdjustPanel
          projectId={projectId}
          onPlanUpdated={(np) => onPlanUpdated(np as unknown as Plan)}
          onClose={() => setAdjustOpen(false)}
          disabled={disabled}
        />
      )}
    </div>
  );
}
