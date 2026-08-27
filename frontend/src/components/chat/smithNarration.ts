/**
 * Turn a raw Smith tool-call ({tool, summary}) into a short narrative line
 * so the chat reads like Smith thinking, not a debug log.
 *
 * Called from ChatHistory's SSEStatusBar per smith_thought event streamed
 * during a Smith turn. Deliberately declarative — the narration templates
 * are the whole surface; adding a new tool means adding a new entry here.
 */

export type SmithNarration = {
  icon: string;  // single emoji + one trailing space, for consistent alignment
  text: string;
};

/** Category → default icon. Individual tools override below. */
const CATEGORY_ICONS: Record<string, string> = {
  read: "🔍",
  list: "📋",
  analyze: "🔬",
  probe: "📡",
  fallback: "🧠",
};

/** Best-effort extraction of common signals from the tool's result_summary
 *  so the narration can carry the interesting number ("12 workflows",
 *  "8 nodes", "1 issue"). Keeps the parse tolerant — an unrecognized
 *  summary is fine, the narration still runs. */
function extractCount(summary: string, keyword: string): number | null {
  const rx = new RegExp(`(\\d+)\\s+${keyword}`, "i");
  const m = summary.match(rx);
  return m ? Number(m[1]) : null;
}

function extractQuoted(summary: string, field: string): string | null {
  // "path": "workflows/foo.json"
  const rx = new RegExp(`"${field}"\\s*:\\s*"([^"]+)"`);
  const m = summary.match(rx);
  return m ? m[1] : null;
}

function shortFile(path: string): string {
  // /Users/…/output/mc2xgclv/workflows/foo.json → workflows/foo.json
  const wf = path.match(/(?:workflows|schemas)\/[^"]+/);
  if (wf) return wf[0];
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

/** Live "about to run" chip fired the moment Smith invokes a tool.
 *  Reuses the completion-chip narrator so the phrasing is consistent —
 *  the difference is present-tense narration ("Reading login.json…") vs
 *  past-tense summary ("Read login.json (8 nodes)") — but for tools
 *  whose default text already reads as present-progressive, no shape
 *  change is needed. Icon is a spinner-like "…" to signal in-flight. */
export function narrateSmithToolStart(tool: string): SmithNarration {
  const base = narrateSmithThought(tool, "");
  return {
    icon: "⏳",
    // Ensure the text ends with an ellipsis so users read it as ongoing.
    text: /…$/.test(base.text) ? base.text : `${base.text.replace(/[.…]+$/, "")}…`,
  };
}

/** Heartbeat chip — fired every ~12s of silence during a long Smith
 *  turn so the chat is never blank. `elapsed_s` is total wall clock;
 *  `last_tool` is the tool Smith started most recently (may be "").
 *  We phrase it as a colleague checking in, not a system message. */
export function narrateSmithHeartbeat(elapsed_s: number, last_tool: string): SmithNarration {
  const secs = Math.max(0, Math.floor(elapsed_s || 0));
  const elapsedStr = secs >= 60
    ? `${Math.floor(secs / 60)}m ${secs % 60}s`
    : `${secs}s`;
  if (last_tool) {
    const pretty = last_tool.replace(/_/g, " ");
    return {
      icon: "⌛",
      text: `Still on \`${pretty}\` — ${elapsedStr} elapsed`,
    };
  }
  return { icon: "⌛", text: `Still working — ${elapsedStr} elapsed` };
}

/** Reasoning-chip labelling for extended-thinking chunks. The chip label
 *  itself stays static; the reasoning text is rendered inside a
 *  collapsible details element by the caller (ChatHistory). */
export function narrateSmithReasoning(text: string): SmithNarration {
  const s = String(text || "");
  // ~4 chars/token — the standard rough estimate for English prose.
  const approxTokens = s.length ? Math.max(1, Math.round(s.length / 4)) : 0;
  return {
    icon: "💭",
    text: approxTokens
      ? `Reasoning (${approxTokens.toLocaleString()} tokens)`
      : "Reasoning…",
  };
}

/** Classify a raw smith_thought event payload. Extended-thinking events
 *  arrive with `kind:"reasoning"` and a `text` field; classic tool events
 *  carry `tool`+`summary`. Legacy events without `kind` default to
 *  tool. Exported so ChatHistory + tests share one parser. */
export function classifySmithThought(payload: {
  kind?: string;
  tool?: string;
  summary?: string;
  text?: string;
}): { kind: "reasoning" | "tool"; text: string; tool: string; summary: string } {
  const kind = payload?.kind === "reasoning" ? "reasoning" : "tool";
  return {
    kind,
    text: String(payload?.text || ""),
    tool: String(payload?.tool || ""),
    summary: String(payload?.summary || ""),
  };
}

export function narrateSmithThought(tool: string, summary: string): SmithNarration {
  const s = String(summary || "");

  switch (tool) {
    case "recall": {
      const entities = extractCount(s, "entities?");
      const workflows = extractCount(s, "workflows?");
      const bits: string[] = [];
      if (entities) bits.push(`${entities} entities`);
      if (workflows) bits.push(`${workflows} workflows`);
      const tail = bits.length ? ` (${bits.join(", ")})` : "";
      return { icon: "🧠", text: `Reading the app plan${tail}…` };
    }

    case "list_workflows": {
      const n = extractCount(s, "workflows?");
      return {
        icon: "⚙️",
        text: n ? `Enumerated ${n} workflows` : "Enumerating workflows…",
      };
    }

    case "read_workflow": {
      const path = extractQuoted(s, "path");
      const nodes = extractCount(s, "nodes?");
      const where = path ? shortFile(path) : "the workflow";
      const detail = nodes ? ` (${nodes} nodes)` : "";
      return { icon: "⚙️", text: `Reading ${where}${detail}…` };
    }

    case "list_pages": {
      const n = extractCount(s, "pages?");
      return {
        icon: "📄",
        text: n ? `Enumerated ${n} pages` : "Enumerating pages…",
      };
    }

    case "read_page": {
      const path = extractQuoted(s, "path");
      const where = path ? shortFile(path) : "the page";
      return { icon: "🔍", text: `Reading ${where}…` };
    }

    case "read_column": {
      return { icon: "🔬", text: "Checking column type…" };
    }

    case "list_components": {
      const n = extractCount(s, "components?");
      return {
        icon: "📦",
        text: n
          ? `Checked the library (${n} components available)`
          : "Checking the component library…",
      };
    }

    case "analyze_workflow_values": {
      const findings = extractCount(s, "findings?");
      if (findings === 0) return { icon: "✅", text: "Type-check passed — no bad bindings" };
      if (findings)
        return {
          icon: "⚠️",
          text: `Type-checked workflow values — ${findings} issue${findings === 1 ? "" : "s"}`,
        };
      return { icon: "🔬", text: "Type-checking workflow values…" };
    }

    case "parse_error": {
      return { icon: "📝", text: "Parsing the error you shared…" };
    }

    case "probe_logs": {
      return { icon: "📡", text: "Reading the app's runtime log…" };
    }

    case "probe_endpoint": {
      return { icon: "🌐", text: "Hitting a localhost endpoint…" };
    }

    // Reserved-word tools (should never render as thoughts, but degrade
    // gracefully in case one slips through).
    case "propose_fix":
    case "answer":
    case "ask_user":
    case "handoff_to_pipeline":
      return { icon: "💭", text: `Deciding: ${tool.replace(/_/g, " ")}` };

    // ── Streaming-progress events from the planning-phase LLM calls
    // (backend/services/streaming_llm.py). The summary carries the
    // char count; extract it into a live "X,XXX chars" readout so the
    // chip stream reads like a progress bar instead of a repeating "…"
    // spinner. Two stages — narrative expansion, then planner call —
    // each emits _started (once), _chunk (throttled), _complete (once).
    case "narrative_expansion_started":
      return { icon: "✍️", text: "Expanding domain narrative…" };
    case "narrative_expansion_chunk": {
      const chars = extractCount(s, "chars?");
      const tail = chars ? ` — ${chars.toLocaleString()} chars` : "";
      return { icon: "✍️", text: `Streaming narrative${tail}` };
    }
    case "narrative_expansion_complete": {
      const chars = extractCount(s, "chars?");
      const tail = chars ? ` (${chars.toLocaleString()} chars)` : "";
      return { icon: "✅", text: `Narrative complete${tail}` };
    }

    case "planner_call_started":
      return { icon: "🏗️", text: "Authoring plan…" };
    case "planner_call_chunk": {
      const chars = extractCount(s, "chars?");
      const tail = chars ? ` — ${chars.toLocaleString()} chars` : "";
      return { icon: "🏗️", text: `Streaming plan${tail}` };
    }
    case "planner_call_complete": {
      const chars = extractCount(s, "chars?");
      const tail = chars ? ` (${chars.toLocaleString()} chars)` : "";
      return { icon: "✅", text: `Plan authored${tail}` };
    }
    case "planner_call_semantic": {
      // The backend has already humanized the text ("Defining entities…"
      // or "+ Candidate"). Choose an icon based on the shape: "+ …"
      // → an item was added, otherwise → a section transition.
      const isAddition = /^\s*\+/.test(s);
      return { icon: isAddition ? "➕" : "🧩", text: s || "Planning…" };
    }
    // Task 3 — decomposition path (skeleton→parallel-units). Fires
    // instead of the streaming planner_call_chunk events when smith-arch
    // routes through the decomposition adapter for a large app.
    case "planner_decompose_start":
      return { icon: "🌿", text: s || "Decomposing plan for parallel authoring…" };
    case "planner_decompose_complete":
      return { icon: "✅", text: s || "Decomposition complete" };
    case "planner_decompose_error":
      return { icon: "⚠️", text: s || "Decomposition failed, falling back" };
    case "unit_authored":
      // Backend already emits "+ /candidate/apply" style text.
      return { icon: "➕", text: s || "Unit authored" };

    default: {
      // Unknown tool — fall back to category best-guess.
      const cat = tool.split("_")[0];
      const icon = CATEGORY_ICONS[cat] || CATEGORY_ICONS.fallback;
      const pretty = tool.replace(/_/g, " ");
      return { icon, text: `Running ${pretty}…` };
    }
  }
}
