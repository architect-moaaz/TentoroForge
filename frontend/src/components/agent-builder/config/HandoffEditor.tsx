"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import type { HandoffAssignment, HumanHandoffConfig } from "@/types/agent-builder";

/** What the assistant asks before it hands over, unless the box says otherwise. */
export const DEFAULT_HANDOFF_QUESTIONS = ["Why do you need a person?", "How urgent is it?", "How can we reach you?"];
const MAX_QUESTIONS = 5;

interface HandoffOptions {
  roles: string[];
  people: Array<{ id: string; name: string; role: string | null }>;
  peopleNote: string | null;
}

interface HandoffEditorProps {
  config: HumanHandoffConfig;
  onUpdate: (config: Partial<HumanHandoffConfig>) => void;
  /** Where the roles and people to choose from come from (the app this agent lives in). */
  projectId?: string;
}

const ASSIGNMENT_HELP: Record<HandoffAssignment, string> = {
  queue: "Everyone who handles handoffs sees it and one of them claims it.",
  round_robin: "Given to whoever holds the fewest open handoffs, so the work spreads evenly.",
  owner: "Always goes to one named person.",
};

/**
 * The human-handoff box as a form: who handles handoffs, how one is assigned, what the assistant asks first, and who
 * is told. Roles and people are the app's own: the people who sign in, not a separate list.
 */
export function HandoffEditor({ config, onUpdate, projectId }: HandoffEditorProps) {
  const { data: options } = useQuery<HandoffOptions>({
    queryKey: ["project", projectId, "handoff-options"],
    queryFn: () => api.get<HandoffOptions>(`/api/projects/${projectId}/agent-definitions/handoff-options`),
    enabled: !!projectId,
    staleTime: 60_000,
    retry: false,
  });

  const conditions = config.conditions || {};
  const handlers = config.handlers || {};
  const roles = handlers.roles ?? [];
  const people = handlers.people ?? [];
  const assignment: HandoffAssignment = config.assignment ?? "queue";
  const questions = config.questions ?? DEFAULT_HANDOFF_QUESTIONS;
  const notify = config.notify || {};
  const knownRoles = options?.roles ?? [];
  const roster = options?.people ?? [];

  const setHandlers = (next: { roles?: string[]; people?: Array<{ id: string; name?: string }> }) =>
    onUpdate({ handlers: { roles, people, ...next } });
  const toggleRole = (role: string) =>
    setHandlers({ roles: roles.includes(role) ? roles.filter((r) => r !== role) : [...roles, role] });
  const togglePerson = (p: { id: string; name: string }) =>
    setHandlers({ people: people.some((x) => x.id === p.id) ? people.filter((x) => x.id !== p.id) : [...people, { id: p.id, name: p.name }] });
  const setNotify = (next: Partial<NonNullable<HumanHandoffConfig["notify"]>>) => onUpdate({ notify: { ...notify, ...next } });
  const setQuestions = (next: string[]) => onUpdate({ questions: next });

  const nobody = roles.length === 0 && people.length === 0;
  // A role already chosen that the app does not have: shown, so it can be seen and unticked.
  const unknownRoles = knownRoles.length ? roles.filter((r) => !knownRoles.some((k) => k.toLowerCase() === r.toLowerCase())) : [];
  const emailOn = notify.email === true;

  return (
    <div className="space-y-4" data-testid="handoff-editor">
      <section className="space-y-2">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">Who handles handoffs</p>
        {knownRoles.length > 0 ? (
          <div className="space-y-1">
            <Label className="text-xs">Anyone with the role</Label>
            {[...knownRoles, ...unknownRoles].map((role) => (
              <label key={role} className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={roles.includes(role)} onChange={() => toggleRole(role)} />
                {role}
                {unknownRoles.includes(role) && <span className="text-red-600">(this app has no such role)</span>}
              </label>
            ))}
          </div>
        ) : (
          <div>
            <Label className="text-xs">Roles (comma-separated)</Label>
            <Input
              className="mt-1 h-8 text-xs"
              placeholder="Manager, Support Agent"
              value={roles.join(", ")}
              onChange={(e) => setHandlers({ roles: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
            />
          </div>
        )}
        {roster.length > 0 && (
          <div className="space-y-1">
            <Label className="text-xs">Or specific people</Label>
            <div className="max-h-28 space-y-1 overflow-y-auto rounded border p-1.5">
              {roster.map((p) => (
                <label key={p.id} className="flex items-center gap-2 text-xs">
                  <input type="checkbox" checked={people.some((x) => x.id === p.id)} onChange={() => togglePerson(p)} />
                  {p.name}
                  {p.role && <span className="text-muted-foreground">({p.role})</span>}
                </label>
              ))}
            </div>
          </div>
        )}
        {options?.peopleNote && <p className="text-[10px] text-muted-foreground">{options.peopleNote}</p>}
        {nobody && (
          <p role="note" className="text-[10px] text-amber-700">
            Nobody is named, so nobody will be notified. Handoffs still land in the inbox, where any signed-in person can see them.
          </p>
        )}
        <p className="text-[10px] text-muted-foreground">
          They are the people who already sign in to the app. To add one, create them in the app and give them the role. They work handoffs at
          /handoffs in the app.
        </p>
      </section>

      <section className="space-y-2">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">How a handoff is assigned</p>
        <select
          aria-label="Assignment"
          className="h-8 w-full rounded border bg-transparent px-1 text-xs"
          value={assignment}
          onChange={(e) => onUpdate({ assignment: e.target.value as HandoffAssignment })}
        >
          <option value="queue">Shared queue: someone claims it</option>
          <option value="round_robin">Spread evenly across the team</option>
          <option value="owner">A named owner</option>
        </select>
        <p className="text-[10px] text-muted-foreground">{ASSIGNMENT_HELP[assignment]} A manager can always reassign it from the inbox.</p>
        {assignment === "owner" &&
          (roster.length > 0 ? (
            <select
              aria-label="Owner"
              className="h-8 w-full rounded border bg-transparent px-1 text-xs"
              value={config.owner_id ?? ""}
              onChange={(e) => onUpdate({ owner_id: e.target.value || undefined })}
            >
              <option value="">Choose a person…</option>
              {roster.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          ) : (
            <Input
              className="h-8 text-xs"
              placeholder="The owner's user id"
              value={config.owner_id ?? ""}
              onChange={(e) => onUpdate({ owner_id: e.target.value.trim() || undefined })}
            />
          ))}
      </section>

      <section className="space-y-2">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">What the assistant asks first</p>
        <p className="text-[10px] text-muted-foreground">
          Only what the person has not already said. Their answers go to whoever takes the handoff.
        </p>
        {questions.map((q, i) => (
          <div key={i} className="flex items-center gap-1">
            <Input
              className="h-8 text-xs"
              aria-label={`Question ${i + 1}`}
              value={q}
              onChange={(e) => setQuestions(questions.map((x, k) => (k === i ? e.target.value : x)))}
            />
            <button type="button" aria-label={`Remove question ${i + 1}`} className="text-muted-foreground" onClick={() => setQuestions(questions.filter((_, k) => k !== i))}>
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-3">
          {questions.length < MAX_QUESTIONS && (
            <button type="button" className="flex items-center gap-1 text-xs text-indigo-600" onClick={() => setQuestions([...questions, ""])}>
              <Plus className="h-3 w-3" /> Add a question
            </button>
          )}
          <button type="button" className="text-xs text-muted-foreground underline" onClick={() => setQuestions([...DEFAULT_HANDOFF_QUESTIONS])}>
            Use the usual three
          </button>
        </div>
      </section>

      <section className="space-y-2">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">Who is told</p>
        <div className="flex items-center gap-2">
          <Switch checked={notify.in_app !== false} onCheckedChange={(v) => setNotify({ in_app: v })} aria-label="Notify in the app" />
          <Label className="text-xs">Ring the bell in the app (recommended)</Label>
        </div>
        <div className="flex items-center gap-2">
          <Switch checked={emailOn} onCheckedChange={(v) => setNotify({ email: v })} aria-label="Also send email" />
          <Label className="text-xs">Also send email</Label>
        </div>
        {emailOn && (
          <div className="ml-10 flex items-center gap-2">
            <Switch checked={notify.email_urgent_only !== false} onCheckedChange={(v) => setNotify({ email_urgent_only: v })} aria-label="Only urgent ones" />
            <Label className="text-xs">Only for urgent handoffs</Label>
          </div>
        )}
        <p className="text-[10px] text-muted-foreground">
          Email is optional. It only goes out if the app has email set up; if not, nothing breaks: handoffs still reach the inbox and the bell.
        </p>
      </section>

      <section className="space-y-2">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">Asking for a person</p>
        <div>
          <Label className="text-xs">Words that mean it</Label>
          <Input
            className="mt-1 h-8 text-xs"
            placeholder="human, real person, speak to someone"
            value={(conditions.keyword_triggers || []).join(", ")}
            onChange={(e) =>
              onUpdate({
                conditions: { ...conditions, keyword_triggers: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) },
              })
            }
          />
        </div>
        <div className="flex items-center gap-2">
          <Switch
            checked={conditions.explicit_request ?? true}
            onCheckedChange={(v) => onUpdate({ conditions: { ...conditions, explicit_request: v } })}
            aria-label="Hand over when asked"
          />
          <Label className="text-xs">Hand over when the person asks</Label>
        </div>
      </section>
    </div>
  );
}
