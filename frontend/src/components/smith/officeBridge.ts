/**
 * What the office is told about a build, from the run's own events.
 *
 * The panel showed a build as a list of stages ticking off — linear, and
 * silent about what actually takes the time: twelve entities being detailed
 * at once, a page sent back by the reviewer, a retry, an API that stopped
 * answering. The office animates every one of those (people at desks, a
 * bubble per subject, a reviewer, a strike when the credit runs out); the v3
 * panel never told it anything. This translates the run's stream into the
 * office's events. Pure: the caller hands the results to the office store.
 */
import type { OfficeEvent } from "@/components/virtual-office/types";

import { labelFor, verbFor } from "./stages";

/** The one who judges every node's output and sends it back. */
export const REVIEWER = "page_reviewer";

const short = (s: unknown, n = 80): string => {
  const t = String(s ?? "").replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};

/** The reviewer's finding, without the "author it again" framing. */
function findingOf(reason: unknown): string {
  const lines = String(reason ?? "").split("\n").map((l) => l.trim()).filter((l) => l.startsWith("- ["));
  const first = lines[0] ?? String(reason ?? "");
  return short(first.replace(/^- \[[^\]]*\]\s*/, ""), 72);
}

export class OfficeBridge {
  /** node key -> the agent behind it, from the plan. */
  private agentOf: Record<string, string> = {};
  private paused = false;

  /** The office events one run event implies, in order. */
  translate(event: string, data: Record<string, unknown>): OfficeEvent[] {
    const node = String(data.node ?? "");
    const agent = this.agentOf[node];
    switch (event) {
      case "plan": {
        this.paused = false;
        this.agentOf = (data.agents as Record<string, string>) ?? {};
        const nodes = (data.nodes as string[]) ?? [];
        const agents = [...new Set(nodes.map((n) => this.agentOf[n]).filter(Boolean))];
        const levels = ((data.levels as string[][]) ?? [])
          .map((lvl) => [...new Set(lvl.map((n) => this.agentOf[n]).filter(Boolean))])
          .filter((lvl) => lvl.length);
        return agents.length ? [{ type: "run_plan", agents, levels }] : [];
      }
      case "node:start":
        return agent ? [{ type: "agent_start", agent, room: "discovery", action: verbFor(node), node }] : [];
      case "node:subject": {
        if (!agent) return [];
        const total = Number(data.total ?? 0);
        const done = Number(data.done ?? 0);
        // The office reads "(i/n)" as the one in hand: the next after those done.
        const status = total > 1
          ? `${verbFor(node)} (${Math.min(done + 1, total)}/${total})`
          : `${labelFor(node)} ready`;
        return [{ type: "agent_status", agent, status, subject: String(data.subject ?? ""), node }];
      }
      case "node:retry":
        return agent
          ? [{ type: "agent_retry", agent, attempt: Number(data.attempt ?? 2), of: Number(data.of ?? 2),
               reason: short(data.reason, 72) }]
          : [];
      case "observer:verdict": {
        if (!agent) return [];
        const what = data.subject ? `${labelFor(node)} · ${data.subject}` : labelFor(node);
        const ok = Boolean(data.ok);
        const n = Number(data.findings ?? 0);
        return [
          { type: "agent_start", agent: REVIEWER, room: "qa", action: `Reviewing ${labelFor(node)}`, node },
          { type: "agent_status", agent: REVIEWER, node,
            status: ok ? `${what}: passes` : `${what}: ${n} finding${n === 1 ? "" : "s"}` },
        ];
      }
      case "observer:repair":
        return agent
          ? [{ type: "agent_retry", agent, attempt: Number(data.round ?? 1), of: Number(data.of ?? 2),
               reason: `Sent back: ${findingOf(data.reason)}` }]
          : [];
      case "observer:unrepaired":
        return agent
          ? [{ type: "agent_status", agent: REVIEWER, node, status: `${labelFor(node)}: left a note` },
             { type: "agent_status", agent, node, status: "Moving on — noted for later" }]
          : [];
      case "node:done":
        return agent ? [{ type: "agent_complete", agent, node }] : [];
      case "node:failed":
        return agent ? [{ type: "agent_error", agent, message: short(data.reason, 90) }] : [];
      case "node:blocked":
        return agent ? [{ type: "agent_blocked", agent, reason: short(data.reason, 90) }] : [];
      case "node:skipped":
        return agent ? [{ type: "agent_skipped", agent, reason: short(data.unmet, 90) }] : [];
      case "node:stalled":
        return agent ? [{ type: "agent_status", agent, node, status: "The API is busy — waiting to try again" }] : [];
      case "run:paused":
        return this.pause(String(data.reason ?? ""));
      case "done": {
        const paused = String(data.paused ?? "");
        if (paused) return this.pause(paused);
        const failed = (data.failed as unknown[]) ?? [];
        const blocked = (data.blocked as unknown[]) ?? [];
        const skipped = (data.skipped as unknown[]) ?? [];
        const completed = (data.completed as unknown[]) ?? [];
        if (failed.length || blocked.length) {
          return [{ type: "run_complete", completed: completed.length, failed: failed.length,
                    blocked: blocked.length, skipped: skipped.length }];
        }
        return [{ type: "build_success" }];
      }
      default:
        return [];
    }
  }

  private pause(reason: string): OfficeEvent[] {
    if (this.paused) return [];
    this.paused = true;
    const credit = /credit|billing|balance/i.test(reason);
    return credit
      ? [{ type: "credits_exhausted", message: short(reason, 90) }]
      : [{ type: "run_complete", completed: 0, failed: 0, blocked: 1, skipped: 0 }];
  }
}
