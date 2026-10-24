/**
 * The platform's ingest contract (POST /api/insights/ingest), written down as a checker. Tests hand it a batch the
 * app produced and get back every rule that batch breaks, in plain words; an empty list means the batch is valid.
 *
 * It is deliberately strict: an extra field is a problem too, because a field the platform does not know about is
 * a field somebody added without telling it (and, here, a possible leak).
 */

const ID = /^[A-Za-z0-9_-]{8,64}$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
const HEX = /^[0-9a-f]{16,64}$/;

const isInt = (v: unknown, min = 0): boolean => typeof v === "number" && Number.isInteger(v) && v >= min;
const isStr = (v: unknown, max: number, min = 0): boolean => typeof v === "string" && v.length >= min && v.length <= max;
const isIso = (v: unknown): boolean => typeof v === "string" && ISO.test(v) && !Number.isNaN(Date.parse(v));

function keysExactly(o: Record<string, unknown>, allowed: string[], where: string, out: string[]) {
  for (const k of Object.keys(o)) if (!allowed.includes(k)) out.push(`${where}: unknown field "${k}"`);
  for (const k of allowed) if (!(k in o)) out.push(`${where}: missing field "${k}"`);
}

function turn(e: Record<string, any>, where: string, out: string[]) {
  keysExactly(e, ["type", "id", "at", "agentId", "conversationId", "userKey", "role", "env", "model", "inputTokens", "outputTokens", "ms", "status", "toolCalls", "toolErrors", "tools", "handedOff", "turnNumber", "problem"], where, out);
  if (!isStr(e.agentId, 80, 1)) out.push(`${where}: agentId must be 1-80 characters`);
  if (!isStr(e.conversationId, 64, 1)) out.push(`${where}: conversationId must be 1-64 characters`);
  if (typeof e.userKey !== "string" || !HEX.test(e.userKey)) out.push(`${where}: userKey must be 16-64 hex characters`);
  if (!(e.role === null || isStr(e.role, 60, 1))) out.push(`${where}: role must be null or at most 60 characters`);
  if (e.env !== "production" && e.env !== "development") out.push(`${where}: env must be production or development`);
  if (!(e.model === null || isStr(e.model, 100, 1))) out.push(`${where}: model must be null or at most 100 characters`);
  for (const k of ["inputTokens", "outputTokens", "ms", "toolCalls", "toolErrors"]) if (!isInt(e[k])) out.push(`${where}: ${k} must be a whole number >= 0`);
  if (!["ok", "error", "blocked"].includes(e.status)) out.push(`${where}: status must be ok, error or blocked`);
  if (!Array.isArray(e.tools) || e.tools.length > 20) out.push(`${where}: tools must be a list of at most 20`);
  else {
    e.tools.forEach((t: any, i: number) => {
      if (!t || typeof t !== "object") return out.push(`${where}: tools[${i}] must be an object`);
      keysExactly(t, ["name", "ok", "ms"], `${where}: tools[${i}]`, out);
      if (!isStr(t.name, 80, 1)) out.push(`${where}: tools[${i}].name must be 1-80 characters`);
      if (typeof t.ok !== "boolean") out.push(`${where}: tools[${i}].ok must be true or false`);
      if (!isInt(t.ms)) out.push(`${where}: tools[${i}].ms must be a whole number >= 0`);
    });
  }
  if (typeof e.handedOff !== "boolean") out.push(`${where}: handedOff must be true or false`);
  if (!isInt(e.turnNumber, 1)) out.push(`${where}: turnNumber must be a whole number >= 1`);
  if (e.problem !== null) {
    if (!e.problem || typeof e.problem !== "object") out.push(`${where}: problem must be null or an object`);
    else {
      keysExactly(e.problem, ["reason", "message", "detail"], `${where}: problem`, out);
      if (!["error", "blocked", "tool_failed", "handed_off", "slow", "thumbs_down"].includes(e.problem.reason)) out.push(`${where}: problem.reason is not one of the known reasons`);
      if (!(e.problem.message === null || isStr(e.problem.message, 200))) out.push(`${where}: problem.message must be null or at most 200 characters`);
      if (!(e.problem.detail === null || isStr(e.problem.detail, 200))) out.push(`${where}: problem.detail must be null or at most 200 characters`);
    }
  }
}

function rating(e: Record<string, any>, where: string, out: string[]) {
  keysExactly(e, ["type", "id", "at", "turnId", "rating", "note"], where, out);
  if (typeof e.turnId !== "string" || !ID.test(e.turnId)) out.push(`${where}: turnId must look like an event id`);
  if (e.rating !== 1 && e.rating !== -1) out.push(`${where}: rating must be 1 or -1`);
  if (!(e.note === null || isStr(e.note, 300))) out.push(`${where}: note must be null or at most 300 characters`);
}

function handoff(e: Record<string, any>, where: string, out: string[]) {
  keysExactly(e, ["type", "id", "at", "agentId", "conversationId", "status", "resolveMinutes"], where, out);
  if (!isStr(e.agentId, 80, 1)) out.push(`${where}: agentId must be 1-80 characters`);
  if (!isStr(e.conversationId, 64, 1)) out.push(`${where}: conversationId must be 1-64 characters`);
  if (!["open", "claimed", "resolved"].includes(e.status)) out.push(`${where}: status must be open, claimed or resolved`);
  if (!(e.resolveMinutes === null || (typeof e.resolveMinutes === "number" && Number.isFinite(e.resolveMinutes) && e.resolveMinutes >= 0))) out.push(`${where}: resolveMinutes must be null or a number >= 0`);
}

/** Every rule the batch breaks. `bytes` is the size of the JSON as sent, before any compression. */
export function validateBatch(body: unknown, bytes?: number): string[] {
  const out: string[] = [];
  const b = body as Record<string, any> | null;
  if (!b || typeof b !== "object" || Array.isArray(b)) return ["the body must be an object"];
  keysExactly(b, ["schema", "events"], "body", out);
  if (b.schema !== 1) out.push("body: schema must be 1");
  if (!Array.isArray(b.events) || b.events.length < 1) return [...out, "body: events must be a list with at least one event"];
  if (b.events.length > 500) out.push(`body: ${b.events.length} events is more than 500`);
  if (bytes !== undefined && bytes > 1_000_000) out.push(`body: ${bytes} bytes is more than 1 MB`);
  b.events.forEach((e: any, i: number) => {
    const where = `events[${i}]`;
    if (!e || typeof e !== "object") return out.push(`${where}: must be an object`);
    if (typeof e.id !== "string" || !ID.test(e.id)) out.push(`${where}: id must be 8-64 characters of A-Z a-z 0-9 _ -`);
    if (!isIso(e.at)) out.push(`${where}: at must be an ISO-8601 UTC time`);
    if (e.type === "turn") turn(e, where, out);
    else if (e.type === "rating") rating(e, where, out);
    else if (e.type === "handoff") handoff(e, where, out);
    else out.push(`${where}: type must be turn, rating or handoff`);
  });
  return out;
}
