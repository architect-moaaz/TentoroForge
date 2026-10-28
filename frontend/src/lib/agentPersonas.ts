// Who each agent is, as people meet them: a name, a title, a few words of
// introduction and the Foundry room they work in. A copy of the backend's
// `services/agent_personas.json` (a backend test keeps the two the same); the
// Foundry, the cockpit's agent dashboard and the spend charts all read it, so an
// agent has one name everywhere. Display only — no prompt carries these names.
import data from "./agent-personas.json";

export interface AgentPersona {
  agent: string;
  name: string;
  title: string;
  room: string;
  intro: string;
}

type Raw = { name: string; title: string; room: string; intro: string };

const RAW = (data as { personas: Record<string, Raw>; aliases: Record<string, string> }).personas;
const ALIASES = (data as { aliases: Record<string, string> }).aliases;

/** Every agent, by its key. */
export const PERSONAS: Record<string, AgentPersona> = Object.fromEntries(
  Object.entries(RAW).map(([agent, p]) => [agent, { agent, ...p }]),
);

/**
 * The agent a usage row or an event names: `page_code:ui_engineer` (a build's
 * usage row) → `ui_engineer`, `workflow_steps:workflow:edit` (a repair) →
 * `workflow`, `app_check` → `testing`. Null when nothing names an agent.
 */
export function agentOf(key: string | null | undefined): string | null {
  const k = String(key ?? "").trim();
  if (!k) return null;
  if (k.includes(":")) {
    const parts = k.split(":").filter((p) => p && p !== "edit");
    for (let i = parts.length - 1; i >= 0; i--) {
      const found = agentOf(parts[i]);
      if (found) return found;
    }
    return null;
  }
  if (PERSONAS[k]) return k;
  const lower = k.toLowerCase();
  if (PERSONAS[lower]) return lower;
  return ALIASES[lower] ?? null;
}

/** The persona for an agent key, or null. */
export function personaOf(key: string | null | undefined): AgentPersona | null {
  const agent = agentOf(key);
  return agent ? PERSONAS[agent] ?? null : null;
}

/** "Leo (UI engineer)" — or the key as it was when no agent owns it. */
export function agentLabel(key: string | null | undefined): string {
  const p = personaOf(key);
  return p ? `${p.name} (${p.title})` : String(key ?? "");
}
