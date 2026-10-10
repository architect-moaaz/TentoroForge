/**
 * Human handoff — handing a conversation to a person. Forge runtime — do not remove.
 *
 * The assistant asks the person a few questions, then calls `request_human`. Here is what that does:
 *   1. records the handoff (reason, urgency, how to reach them, the last few messages) — if THIS fails the
 *      tool fails, because the assistant must never say "I've passed you to the team" over nothing;
 *   2. picks who takes it, by the box's assignment: the shared queue, round-robin, or a named owner;
 *   3. tells them: the in-app bell always (when on), email only when asked for AND set up.
 *
 * Step 3 can never fail the handoff, the chat or the app. No email set up, a mail server down, a
 * notification table missing: each is caught, counted and left out of the answer. Everything outside the
 * loop arrives as `HandoffDeps`, so all of this runs in tests against fakes.
 */
import { ToolError } from "./tools";
import type { AgentUser, HandoffDeps, HandoffRecord, HandoffSpec, HandoffUrgency, Person, ToolContext } from "./types";

const URGENCIES: HandoffUrgency[] = ["low", "normal", "urgent"];

/** Whether this person may work the inbox: a handler by role or by name. With nobody named, any signed-in person may. */
export function canHandle(spec: HandoffSpec | null | undefined, user: AgentUser | null): boolean {
  if (!spec || !user) return false;
  const { roles, people } = spec.handlers;
  if (roles.length === 0 && people.length === 0) return true;
  if (people.some((p) => p.id === user.id)) return true;
  const role = (user.role ?? "").toLowerCase();
  return !!role && roles.some((r) => r.toLowerCase() === role);
}

/** Who takes it. `queue` = nobody yet (anyone on the team claims it); `owner` = the named person;
 *  `round_robin` = whoever holds the fewest unresolved handoffs, ties broken by id so it is repeatable. */
export function pickAssignee(spec: HandoffSpec, candidates: Person[], openCounts: Record<string, number>): Person | null {
  if (spec.assignment === "owner") {
    return spec.ownerId ? candidates.find((c) => c.id === spec.ownerId) ?? { id: spec.ownerId } : null;
  }
  if (spec.assignment !== "round_robin" || candidates.length === 0) return null;
  return [...candidates].sort((a, b) => (openCounts[a.id] ?? 0) - (openCounts[b.id] ?? 0) || a.id.localeCompare(b.id))[0];
}

/** What the person is told when they write to a conversation that is with a person now. */
export function handoffNotice(h: Pick<HandoffRecord, "ref" | "status" | "assignedToName">): string {
  const who = h.status === "claimed" && h.assignedToName ? `${h.assignedToName} is looking at it. ` : "";
  return `This conversation is with a person on the team now (reference ${h.ref}). ${who}They will pick it up from here; nothing more is needed from you, and you can add details here if you like.`;
}

function unique(people: Person[]): Person[] {
  const seen = new Set<string>();
  return people.filter((p) => (seen.has(p.id) ? false : (seen.add(p.id), true)));
}

async function tell(deps: HandoffDeps, spec: HandoffSpec, h: HandoffRecord, assignee: Person | null, pool: Person[]) {
  const out = { inApp: 0, emailed: 0, emailNote: undefined as string | undefined };
  const title = `Handoff requested${h.urgency === "urgent" ? " (urgent)" : ""}: ${h.reason.slice(0, 70)}`;
  const message =
    `${h.requestedByName || "Someone"} asked for a person. Reason: ${h.reason}.` +
    (h.contact ? ` Reach them at: ${h.contact}.` : "") +
    ` Open Handoffs (/handoffs) to take it (${h.ref}).`;

  if (spec.notify.inApp) {
    const targets: Array<{ userId?: string; role?: string }> = assignee
      ? [{ userId: assignee.id }]
      : [...spec.handlers.roles.map((role) => ({ role })), ...spec.handlers.people.map((p) => ({ userId: p.id }))];
    for (const t of targets) {
      try {
        await deps.notify({ title, message, userId: t.userId ?? null, role: t.role ?? null, entityId: h.id });
        out.inApp++;
      } catch {
        /* a notification that cannot be written never fails a handoff */
      }
    }
  }

  const wantsEmail = spec.notify.email && (h.urgency === "urgent" || !spec.notify.emailUrgentOnly);
  if (wantsEmail) {
    if (!deps.email) {
      out.emailNote = "email is not set up";
    } else {
      const to = unique((assignee ? [assignee] : pool).filter((p) => !!p.email)).map((p) => String(p.email)).slice(0, 10);
      if (to.length === 0) out.emailNote = "no email address on file for the people who handle this";
      for (const address of to) {
        try {
          const r = await deps.email(address, title, `${message}\n\n${h.summary ?? ""}`.trim());
          if (r.sent) out.emailed++;
          else out.emailNote = r.reason || "email is not set up";
        } catch (e) {
          out.emailNote = e instanceof Error ? e.message : String(e);
        }
      }
    }
  }
  return out;
}

/** The `request_human` tool. Throws a ToolError only for what the model should be told: no reason, not signed in,
 *  or the handoff could not be saved. */
export async function requestHandoff(
  deps: HandoffDeps,
  ctx: ToolContext,
  input: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const spec = ctx.handoff;
  if (!spec) throw new ToolError("Handing over to a person is not set up for this assistant.", "unavailable");
  if (!ctx.user) throw new ToolError("The person needs to be signed in before they can be handed to the team.", "auth");
  if (!ctx.conversationId) throw new ToolError("There is no conversation to hand over.", "invalid");

  const reason = String(input.reason ?? "").trim().slice(0, 1000);
  if (!reason) throw new ToolError("A reason is needed, so whoever picks this up knows what it is about. Ask the person.", "invalid");
  const urgency = (URGENCIES as unknown[]).includes(input.urgency) ? (input.urgency as HandoffUrgency) : "normal";
  const contact = String(input.contact ?? "").trim().slice(0, 300) || ctx.user.email || "";

  // Asked twice: the same handoff, not a second one.
  const existing = await deps.store.openFor(ctx.conversationId).catch(() => null);
  if (existing) {
    return { ok: true, ref: existing.ref, status: existing.status, message: `Already with the team (reference ${existing.ref}).` };
  }

  let found: Person[] = [];
  try {
    found = spec.handlers.roles.length ? await deps.people(spec.handlers.roles) : [];
  } catch {
    /* no way to look people up: the queue still works */
  }
  const pool = unique([...spec.handlers.people.map((p) => ({ id: p.id, name: p.name ?? null })), ...found]);
  let counts: Record<string, number> = {};
  if (spec.assignment === "round_robin") counts = await deps.store.openCounts(pool.map((p) => p.id)).catch(() => ({}));
  const assignee = pickAssignee(spec, pool, counts);

  let summary: string | null = null;
  try {
    summary = deps.snapshot ? await deps.snapshot(ctx.conversationId) : null;
  } catch {
    /* the handoff does not need its transcript to exist */
  }

  let record: HandoffRecord;
  try {
    record = await deps.store.create({
      conversationId: ctx.conversationId,
      agentId: ctx.agentId ?? "",
      requestedById: ctx.user.id,
      requestedByName: null,
      reason,
      urgency,
      contact: contact || null,
      summary,
      assignedToId: assignee?.id ?? null,
      assignedToName: assignee?.name ?? null,
      resolutionNote: null,
    });
  } catch (e) {
    throw new ToolError(
      "The handoff could not be recorded, so nobody has been told. Say so plainly and suggest contacting the app's administrator.",
      "failed",
    );
  }

  const told = await tell(deps, spec, record, assignee, pool);
  return {
    ok: true,
    ref: record.ref,
    status: "open",
    message: `Recorded and passed to the team. Give the person the reference ${record.ref}. Do not promise a time.`,
    notified: told.inApp > 0 || told.emailed > 0 ? { inApp: told.inApp, emailed: told.emailed } : { inApp: 0, emailed: 0 },
    ...(told.emailNote ? { emailNote: told.emailNote } : {}),
  };
}
