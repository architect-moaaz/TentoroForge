/**
 * Agent runtime — the loop. Forge runtime — do not remove.
 *
 *   1. check the message against the input guardrails
 *   2. replay the conversation (summary + recent turns), add the message
 *   3. ask the model; if it asks for tools, run them and ask again
 *   4. check the answer against the output guardrails and rules
 *   5. save the turn, fold old turns into the summary, say "done"
 *
 * Everything outside the loop — the model, the tools, the database — arrives as
 * `AgentDeps`, so the loop is tested with fakes and shipped with the real ones
 * (io.ts, store.ts). It reports as it goes through `emit`; it never throws: a
 * failure is an `error` event, because a half-streamed answer has nowhere to
 * throw to.
 */
import { checkOutputRules, validateInput, validateOutput } from "./guardrails";
import { handoffNotice } from "./handoff";
import { loadHistory, summarizeIfNeeded } from "./memory";
import { toModelTools } from "./tools";
import type {
  AgentDeps,
  AgentEvent,
  AgentRunInput,
  AgentRuntimeConfig,
  AgentToolSpec,
  ModelBlock,
  ModelMessage,
  ToolCallRecord,
} from "./types";

const REFUSAL_ANSWER = "I'm sorry — I can't share that. Please contact support directly.";

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export async function runAgent(
  config: AgentRuntimeConfig,
  input: AgentRunInput,
  deps: AgentDeps,
  emit: (e: AgentEvent) => void,
): Promise<void> {
  const tokens = { input: 0, output: 0 };
  try {
    if (!config.enabled) {
      emit({ type: "error", message: `${config.name} is switched off.` });
      return;
    }

    // 1 ── input guardrails
    const verdict = validateInput(input.message, config.guardrails.input, !!input.user);
    if (!verdict.ok) {
      emit({ type: "blocked", stage: "input", reason: verdict.reason ?? "Blocked." });
      return;
    }

    // 2 ── the conversation
    const userId = input.user?.id ?? "anonymous";
    let conversationId = input.conversationId;
    let summary: string | null = null;
    if (conversationId) {
      const existing = await deps.store.getConversation(conversationId, userId);
      // Someone else's id is treated as no id — a new conversation, never theirs.
      if (!existing) conversationId = null;
      else summary = existing.summary;
    }
    if (!conversationId) conversationId = await deps.store.createConversation(config.id, userId);

    const history = await loadHistory(deps.store, conversationId, summary, config.memory, new Set(config.tools.map((t) => t.name)));
    const messages: ModelMessage[] = [...history, { role: "user", content: input.message }];
    await deps.store.saveMessage(conversationId, { role: "user", content: input.message });

    // A conversation that is with a person is not answered by the assistant: what the person writes is kept for
    // whoever has it, and they are told so. Resolved, it is the assistant's again. A lookup that fails (no handoff
    // table in this app) means "not handed over", never an error.
    const handed = await deps.handoffs?.openFor(conversationId).catch(() => null);
    if (handed) {
      const notice = handoffNotice(handed);
      emit({ type: "text", content: notice });
      emit({ type: "handoff", ref: handed.ref, status: handed.status });
      await deps.store.saveMessage(conversationId, { role: "assistant", content: notice });
      emit({ type: "done", conversationId, tokens, turns: 0 });
      return;
    }

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
          calls.push({ name: use.name, input: use.input, error: msg });
          emit({ type: "tool_result", id: use.id, tool: use.name, ok: false, error: msg });
          toolResults.push({ type: "tool_result", tool_use_id: use.id, content: msg, is_error: true });
          continue;
        }
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
          calls.push({ name: use.name, input: use.input, result: out });
          emit({ type: "tool_result", id: use.id, tool: use.name, ok: true, result: out });
          toolResults.push({ type: "tool_result", tool_use_id: use.id, content: JSON.stringify(out ?? null) });
        } catch (e) {
          const msg = errorText(e);
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
    if (!rules.ok) {
      final = REFUSAL_ANSWER;
      emit({ type: "blocked", stage: "output", reason: rules.reason ?? "Blocked.", replacement: REFUSAL_ANSWER });
    }

    // 5 ── remember it
    await deps.store.saveMessage(conversationId, {
      role: "assistant",
      content: final,
      toolCalls: calls.length ? calls : null,
      tokenCount: tokens.input + tokens.output,
    });
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

    emit({ type: "done", conversationId, tokens, turns });
  } catch (e) {
    emit({ type: "error", message: errorText(e) });
  }
}
