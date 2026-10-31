/**
 * Agent runtime — the loop. Forge runtime — do not remove.
 *
 *   1. check the message against the input guardrails
 *   2. replay the conversation (summary + recent turns), add the message
 *   3. ask the model; if it asks for tools, run them and ask again
 *   4. check the answer against the output guardrails and rules
 *   5. save the turn, fold old turns into the summary, say "done"
 *   6. note what the turn cost and how it went (best-effort, after "done": see recordTurnSafely)
 *
 * Everything outside the loop — the model, the tools, the database — arrives as
 * `AgentDeps`, so the loop is tested with fakes and shipped with the real ones
 * (io.ts, store.ts). It reports as it goes through `emit`; it never throws: a
 * failure is an `error` event, because a half-streamed answer has nowhere to
 * throw to.
 */
import { gate } from "./confirm";
import { checkOutputRules, validateInput, validateOutput } from "./guardrails";
import { handoffNotice } from "./handoff";
import { checkLimits, limitsOf } from "./limits";
import { loadHistory, summarizeIfNeeded } from "./memory";
import { toModelTools } from "./tools";
import { guestFromCookie, visitorKeys } from "./visitor";
import type {
  AgentDeps,
  AgentEvent,
  AgentRunInput,
  AgentRuntimeConfig,
  AgentToolSpec,
  ConfirmState,
  ModelBlock,
  ModelMessage,
  ToolCallRecord,
  TurnRecord,
  TurnStatus,
  TurnToolStat,
} from "./types";

const REFUSAL_ANSWER = "I'm sorry — I can't share that. Please contact support directly.";

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** Per-turn tool detail is capped, and so are the words kept about why a turn failed. */
const MAX_TOOL_STATS = 20;
const MAX_ERROR_CHARS = 300;

/** Whether the first words of a turn that went wrong may be sent to the platform's insights. Off unless the builder set it. */
function includeTextInInsights(): boolean {
  return typeof process !== "undefined" && process.env?.FORGE_INSIGHTS_INCLUDE_TEXT === "1";
}

// ── recording a turn ──────────────────────────────────────────────────────

let saidItCouldNotRecord = false;

/** For tests: forget that the one warning was already given. */
export function resetTurnWarning(): void {
  saidItCouldNotRecord = false;
}

/**
 * Hand a finished turn to the store, and never let that touch the chat. Nothing is awaited by the caller, a store
 * that throws (or hangs) is swallowed, and the most likely failure — an app that was updated but whose database was
 * not pushed yet, so the table is missing — is said once in the log, not on every message. A later success re-arms
 * the warning, so a table that goes missing again is still noticed.
 */
export function recordTurnSafely(deps: AgentDeps, turn: TurnRecord): void {
  const store = deps.turns;
  if (!store) return;
  const fail = (e: unknown) => {
    if (saidItCouldNotRecord) return;
    saidItCouldNotRecord = true;
    try {
      console.warn(`[agent] a turn could not be recorded (${errorText(e).slice(0, 120)}). If the database was not pushed after the last update, run the push; the chat is not affected.`);
    } catch {
      /* a broken logger is not the chat's problem either */
    }
  };
  try {
    Promise.resolve(store.record(turn)).then(() => { saidItCouldNotRecord = false; }, fail);
  } catch (e) {
    fail(e);
  }
}

export async function runAgent(
  config: AgentRuntimeConfig,
  input: AgentRunInput,
  deps: AgentDeps,
  emit: (e: AgentEvent) => void,
): Promise<void> {
  const clock = deps.now ?? Date.now;
  const startedAt = clock();
  const tokens = { input: 0, output: 0 };
  const userId = input.user?.id ?? "anonymous";
  // WHO IS COUNTED against the limits: a signed-in person by their account, a signed-out visitor by their guest cookie
  // AND the address they came from (visitor.ts), so a public assistant cannot be run without limit on the owner's key
  // by clearing cookies, nor by one office's worth of visitors being mistaken for one. Nothing identifies them: not counted.
  const limitKeys = input.user
    ? [input.user.id]
    : visitorKeys({ guest: input.visitor?.guest ?? guestFromCookie(input.cookie), ip: input.visitor?.ip ?? null });
  // What this turn did, kept for the record at the end (see recordTurnSafely). The conversation goes in it only once
  // it is known to be the person's: an id a visitor made up is never written down as theirs.
  const turn = {
    status: "ok" as TurnStatus,
    error: null as string | null,
    model: null as string | null,
    conversation: "",
    calls: 0,
    callErrors: 0,
    stats: [] as TurnToolStat[],
    handedOff: false,
    messageId: null as string | null,
    // Which message of its conversation this is (1 = the first). Known once the conversation's state is read.
    number: null as number | null,
  };
  const noteTool = (name: string, ok: boolean, ms: number) => {
    turn.calls++;
    if (!ok) turn.callErrors++;
    if (turn.stats.length < MAX_TOOL_STATS) turn.stats.push({ name, ok, ms: Math.max(0, Math.round(ms)) });
  };
  try {
    if (!config.enabled) {
      turn.status = "error";
      turn.error = `${config.name} is switched off.`;
      emit({ type: "error", message: `${config.name} is switched off.` });
      return;
    }

    // 1 ── input guardrails
    const verdict = validateInput(input.message, config.guardrails.input, !!input.user);
    deps.trace?.({ type: "phase", phase: "input_check", ok: verdict.ok, ...(verdict.reason ? { reason: verdict.reason } : {}) });
    if (!verdict.ok) {
      turn.status = "blocked";
      turn.error = verdict.reason ?? "Blocked.";
      emit({ type: "blocked", stage: "input", reason: verdict.reason ?? "Blocked." });
      return;
    }

    // 2 ── the conversation
    let conversationId = input.conversationId;
    let summary: string | null = null;
    if (conversationId) {
      const existing = await deps.store.getConversation(conversationId, userId);
      // Someone else's id is treated as no id — a new conversation, never theirs.
      if (!existing) conversationId = null;
      else {
        summary = existing.summary;
        turn.conversation = conversationId;
      }
    }

    // A conversation that is with a person is not answered by the assistant: what the person writes is kept for
    // whoever has it, and they are told so. Resolved, it is the assistant's again. A lookup that fails (no handoff
    // table in this app) means "not handed over", never an error.
    const handed = conversationId ? await deps.handoffs?.openFor(conversationId).catch(() => null) : null;

    // The person's own limits, before anything is created, saved or paid for. Talking to a person on the team costs
    // nothing, so it is never limited. Counts that cannot be read (no table yet) mean "not limited". A visitor is over
    // when ANY of their keys is; all are read before any is counted, so a refused message is not counted as used.
    if (!handed && deps.usage && limitKeys.length) {
      const limits = limitsOf(config.guardrails.limits);
      for (const key of limitKeys) {
        const used = await deps.usage.read(key).catch(() => null);
        const over = used ? checkLimits(limits, used) : null;
        if (over) {
          turn.status = "blocked";
          turn.error = over.reason ?? "Limit reached.";
          emit({ type: "blocked", stage: "input", reason: over.reason ?? "Limit reached." });
          return;
        }
      }
      for (const key of limitKeys) await deps.usage.add(key, { messages: 1 }).catch(() => {});
    }

    if (!conversationId) conversationId = await deps.store.createConversation(config.id, userId);
    turn.conversation = conversationId;

    const history = await loadHistory(deps.store, conversationId, summary, config.memory, new Set(config.tools.map((t) => t.name)));
    const messages: ModelMessage[] = [...history, { role: "user", content: input.message }];
    await deps.store.saveMessage(conversationId, { role: "user", content: input.message });
    deps.trace?.({ type: "phase", phase: "memory", messages: history.length, summarised: summary !== null });

    if (handed) {
      deps.trace?.({ type: "phase", phase: "with_person", ref: handed.ref });
      // The person is told once. After that (or once a person has written back) what they add simply reaches
      // whoever has it; repeating the notice on every message would drown a real conversation.
      const last = history[history.length - 1];
      const lastText = last && typeof last.content === "string" ? last.content : "";
      const told = last?.role === "assistant" && (lastText.startsWith("This conversation is with a person") || lastText.startsWith("[A person on the team wrote"));
      if (!told) {
        const notice = handoffNotice(handed);
        emit({ type: "text", content: notice });
        const noticeId = await deps.store.saveMessage(conversationId, { role: "assistant", content: notice });
        turn.messageId = typeof noticeId === "string" ? noticeId : null;
      }
      turn.handedOff = true;
      emit({ type: "handoff", ref: handed.ref, status: handed.status });
      // Whoever has it hears that the person wrote. A failure here never touches the chat.
      await deps.handoffs?.customerWrote?.(handed, input.message).catch(() => {});
      emit({ type: "done", conversationId, tokens, turns: 0, messageId: turn.messageId });
      return;
    }

    // The changes this conversation is holding back until the person agrees (confirm.ts). A store that cannot keep
    // them still works: nothing it holds can be released, so every change is asked about, never skipped.
    const confirmState: ConfirmState = (await deps.store.getState?.(conversationId).catch(() => null)) ?? { turn: 0, holds: [] };
    confirmState.turn += 1;
    turn.number = confirmState.turn;
    const saveConfirmState = () => deps.store.setState?.(conversationId as string, confirmState).catch(() => {});
    await saveConfirmState();

    // 3 ── the model ⇄ tools loop
    const specs = new Map<string, AgentToolSpec>(config.tools.map((t) => [t.name, t]));
    const modelTools = toModelTools(config.tools);
    const scope: Record<string, unknown> = {};
    const calls: ToolCallRecord[] = [];
    let answer = "";
    let turns = 0;
    let finished = false;

    while (turns < config.maxTurns) {
      turns++;
      let turnText = "";
      // Text before a tool call and text after it are two pieces of one answer. Run
      // together they read "Let me look!Found it!" — so a paragraph break goes between.
      let needBreak = answer.length > 0 && !/\s$/.test(answer);
      const result = await deps.callModel(
        {
          model: config.model.name,
          maxTokens: config.model.maxTokens,
          temperature: config.model.temperature,
          system: config.systemPrompt,
          messages,
          tools: modelTools,
        },
        (chunk) => {
          if (needBreak && chunk.trim()) {
            needBreak = false;
            turnText += "\n\n";
            emit({ type: "text", content: "\n\n" });
          }
          turnText += chunk;
          emit({ type: "text", content: chunk });
        },
      );
      tokens.input += result.usage.inputTokens;
      tokens.output += result.usage.outputTokens;
      turn.model = result.model ?? turn.model;
      answer += turnText;

      const uses = result.content.filter(
        (b): b is Extract<ModelBlock, { type: "tool_use" }> => b.type === "tool_use",
      );
      if (uses.length === 0) {
        finished = true;
        break;
      }

      messages.push({ role: "assistant", content: result.content });
      const toolResults: ModelBlock[] = [];
      for (const use of uses) {
        emit({ type: "tool_call", id: use.id, tool: use.name, input: use.input });
        const spec = specs.get(use.name);
        if (!spec) {
          const msg = `There is no tool called ${use.name}.`;
          noteTool(use.name, false, 0);
          calls.push({ name: use.name, input: use.input, error: msg });
          emit({ type: "tool_result", id: use.id, tool: use.name, ok: false, error: msg });
          toolResults.push({ type: "tool_result", tool_use_id: use.id, content: msg, is_error: true });
          continue;
        }
        const verdict = gate(confirmState, spec, use.input, { now: (deps.now ?? Date.now)(), confirm: input.confirm });
        if (!verdict.run) {
          await saveConfirmState();
          if ("held" in verdict) {
            noteTool(use.name, true, 0);
            calls.push({ name: use.name, input: use.input, result: verdict.held });
            emit({ type: "tool_result", id: use.id, tool: use.name, ok: true, result: verdict.held });
            toolResults.push({ type: "tool_result", tool_use_id: use.id, content: JSON.stringify(verdict.held) });
          } else {
            noteTool(use.name, false, 0);
            calls.push({ name: use.name, input: use.input, error: verdict.refused });
            emit({ type: "tool_result", id: use.id, tool: use.name, ok: false, error: verdict.refused });
            toolResults.push({ type: "tool_result", tool_use_id: use.id, content: `Error: ${verdict.refused}`, is_error: true });
          }
          continue;
        }
        await saveConfirmState();
        const toolStart = clock();
        try {
          const out = await deps.runTool(
            spec,
            use.input,
            {
              user: input.user,
              cookie: input.cookie,
              origin: input.origin,
              conversationId: conversationId as string,
              agentId: config.id,
              handoff: config.handoff ?? null,
            },
            scope,
          );
          scope[spec.name] = out;
          noteTool(use.name, true, clock() - toolStart);
          if (spec.kind === "handoff") turn.handedOff = true;
          calls.push({ name: use.name, input: use.input, result: out });
          emit({ type: "tool_result", id: use.id, tool: use.name, ok: true, result: out });
          toolResults.push({ type: "tool_result", tool_use_id: use.id, content: JSON.stringify(out ?? null) });
        } catch (e) {
          const msg = errorText(e);
          noteTool(use.name, false, clock() - toolStart);
          calls.push({ name: use.name, input: use.input, error: msg });
          emit({ type: "tool_result", id: use.id, tool: use.name, ok: false, error: msg });
          toolResults.push({ type: "tool_result", tool_use_id: use.id, content: `Error: ${msg}`, is_error: true });
        }
      }
      messages.push({ role: "user", content: toolResults });
    }

    if (!finished) {
      const msg = "I couldn't finish that within my step limit. Please try a simpler request.";
      answer += (answer ? "\n\n" : "") + msg;
      emit({ type: "text", content: (answer === msg ? "" : "\n\n") + msg });
    }

    // 4 ── output guardrails
    let final = answer;
    const out = validateOutput(final, config.guardrails.output);
    const rules = out.ok ? checkOutputRules(config.guardrails.outputRules, scope, deps.evalExpression) : out;
    deps.trace?.({ type: "phase", phase: "output_check", ok: rules.ok, ...(rules.ok ? {} : { reason: rules.reason ?? "Blocked." }) });
    if (!rules.ok) {
      final = REFUSAL_ANSWER;
      turn.status = "blocked";
      turn.error = rules.reason ?? "Blocked.";
      emit({ type: "blocked", stage: "output", reason: rules.reason ?? "Blocked.", replacement: REFUSAL_ANSWER });
    }

    // 5 ── remember it
    const savedId = await deps.store.saveMessage(conversationId, {
      role: "assistant",
      content: final,
      toolCalls: calls.length ? calls : null,
      tokenCount: tokens.input + tokens.output,
    });
    turn.messageId = typeof savedId === "string" ? savedId : null;
    if (deps.usage) for (const key of limitKeys) await deps.usage.add(key, { tokens: tokens.input + tokens.output }).catch(() => {});
    try {
      await summarizeIfNeeded(deps.store, conversationId, summary, config.memory, async (transcript) => {
        const r = await deps.callModel(
          {
            maxTokens: 400,
            system:
              "Summarise this conversation in 2-3 sentences. Keep the facts, decisions and open requests a later reply would need.",
            messages: [{ role: "user", content: transcript }],
            tools: [],
          },
          () => {},
        );
        return r.content.filter((b) => b.type === "text").map((b) => (b as { text: string }).text).join("");
      });
    } catch {
      /* summarising is housekeeping — never fail the answer for it */
    }

    emit({ type: "done", conversationId, tokens, turns, messageId: turn.messageId });
  } catch (e) {
    turn.status = "error";
    turn.error = errorText(e);
    emit({ type: "error", message: errorText(e) });
  } finally {
    // Last, after the person has the answer, and never awaited: what it cost is housekeeping, not part of the reply.
    recordTurnSafely(deps, {
      conversationId: turn.conversation,
      agentId: config.id,
      userId,
      model: turn.model ?? config.model.name ?? null,
      inputTokens: tokens.input,
      outputTokens: tokens.output,
      ms: Math.max(0, Math.round(clock() - startedAt)),
      status: turn.status,
      error: turn.error ? turn.error.slice(0, MAX_ERROR_CHARS) : null,
      toolCalls: turn.calls,
      toolErrors: turn.callErrors,
      toolStats: turn.stats,
      handedOff: turn.handedOff,
      assistantMessageId: turn.messageId,
      userRole: input.user?.role ? String(input.user.role) : null,
      turnNumber: turn.number,
      // The person's words travel with a turn that went wrong only when the builder allowed it (FORGE_INSIGHTS_INCLUDE_TEXT=1).
      userMessage: includeTextInInsights() ? input.message.slice(0, MAX_ERROR_CHARS) : null,
    });
  }
}
