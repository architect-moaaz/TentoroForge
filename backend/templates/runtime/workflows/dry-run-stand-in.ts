/**
 * What the build-time dry run puts where an earlier step's output would be.
 *
 * The dry run executes nothing, so a step's output is unknowable; a reference
 * into one is "supplied by the run", never "empty". This stand-in has to
 * answer ANY path to keep that promise — and it answered one level only.
 * `get` returned the string "dry-run" for every property, so
 * `{{load_rental.rows[0].listingId}}` walked rows → "dry-run", [0] → "d",
 * .listingId → undefined, and the dry run refused a correct workflow with
 * "WHERE id is empty". Reading a queried row is always at least that deep
 * (`db_query` returns `{ rows, count }`), so every such workflow was
 * refused (Neighbourhood Kit, UAT, 2026-09-18).
 *
 * Now every property answers with the stand-in itself, at any depth, and it
 * still reads as the string "dry-run" wherever a value is finally used.
 * Kept free of imports so a test can load exactly this object.
 */
export const STEP_OUTPUT: unknown = new Proxy(
  {},
  {
    get: (_t, prop) =>
      prop === "toString" || prop === Symbol.toPrimitive || prop === "valueOf"
        ? () => "dry-run"
        : STEP_OUTPUT,
  },
);

/**
 * Names a workflow's `set_variable` steps write. The engine stores the value
 * under `variableName`, not the node id, so the dry run seeds these beside the
 * node ids — otherwise `{{resolvedClinicId}}` set by one step and read by the
 * next is "empty" and a correct workflow is refused at assemble.
 */
export function setVariableNames(def: unknown): string[] {
  const d = def as any;
  const nodes: any[] = (d?.definition?.nodes ?? d?.nodes ?? []) as any[];
  return nodes
    .map((n) => n?.data?.config ?? n?.config ?? {})
    .filter((c) => c?.actionType === "set_variable" && typeof c.variableName === "string" && c.variableName)
    .map((c) => String(c.variableName));
}

/**
 * What the dry run puts where an ASSISTANT STEP's answer would be, and what the step itself answers when a run is
 * flagged as a dry run (the model is never called, no tool runs, nothing is written).
 *
 * The envelope is the real one's shape (workflows/../agents/workflow-run.ts: AgentStepEnvelope) filled from the
 * step's declared output fields, deterministically: a choice is its first value, a yes/no false, a number 0, a list
 * [], an object {}, text "sample"; confidence 1, needsHuman false, no proposals, no actions. So a decision after the
 * step compares real-looking values and a step that reads `{{triage.result.urgency}}` gets one.
 */
export function agentStepSample(config: unknown): Record<string, unknown> {
  const fields: any[] = Array.isArray((config as any)?.outputFields) ? (config as any).outputFields : [];
  const result: Record<string, unknown> = {};
  for (const f of fields) {
    if (!f || typeof f.name !== "string" || !f.name) continue;
    switch (f.type) {
      case "enum": result[f.name] = Array.isArray(f.values) && f.values.length ? String(f.values[0]) : ""; break;
      case "boolean": result[f.name] = false; break;
      case "number": result[f.name] = 0; break;
      case "array": result[f.name] = []; break;
      case "object": result[f.name] = {}; break;
      default: result[f.name] = "sample";
    }
  }
  return {
    ok: true,
    needsHuman: false,
    confidence: 1,
    summary: "sample",
    result,
    proposals: [],
    actions: [],
    usage: { turns: 0, inputTokens: 0, outputTokens: 0, ms: 0 },
  };
}

/**
 * The sample as the dry run's variables hold it: everything the sample has reads as it is, and anything it does not
 * have (`{{triage.proposals[0].input.petId}}`, a field a later step names that the sample leaves empty) still reads as
 * "supplied by the run", for the reason STEP_OUTPUT exists. Without this a correct workflow would be refused because
 * a sample has no proposals.
 */
export function agentStepView(value: unknown): unknown {
  if (value === null || typeof value !== "object") return value;
  return new Proxy(value as object, {
    get(target, prop, receiver) {
      if (typeof prop === "symbol") return Reflect.get(target, prop, receiver);
      if (prop in target) return agentStepView((target as any)[prop]);
      return STEP_OUTPUT;
    },
  });
}

/** The nodes of a workflow that are assistant steps (by action type, or by node type), with their config. */
export function agentStepNodes(def: unknown): Array<{ id: string; config: any }> {
  const d = def as any;
  const nodes: any[] = (d?.definition?.nodes ?? d?.nodes ?? []) as any[];
  return nodes
    .map((n) => ({ id: String(n?.id ?? n?.key ?? ""), type: n?.type, config: n?.data?.config ?? n?.config ?? {} }))
    .filter((n) => n.id && (n.config?.actionType === "agent_step" || n.type === "agent_step"))
    .map(({ id, config }) => ({ id, config }));
}
