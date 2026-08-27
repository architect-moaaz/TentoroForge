/**
 * Real AI action handlers for the workflow runtime — ai_generate, ai_classify,
 * ai_extract, ai_decide. Each calls the Anthropic API (Claude) and falls back to
 * a deterministic mock when ANTHROPIC_API_KEY is absent, so a generated app runs
 * green in dev without a key and does real inference once a key is set.
 *
 * Config contract (canonical; aliases accepted for editor↔generator parity):
 *   common:   aiModel, aiMaxTokens, aiTemperature, aiSystemPrompt, aiPrompt, aiInput
 *   generate: aiTone, aiMaxLength
 *   classify: aiLabels: string[], aiThreshold | aiConfidenceThreshold
 *   extract:  aiExtractFields: string[] | {name,type}[], (aiInput may resolve to a
 *             file descriptor → the file is handed to Claude as a document block)
 *   decide:   aiOptions: string[], aiRules: string | string[], aiContext
 *
 * The `output` field is always present so a downstream node that maps output
 * without naming a source gets the node's primary value.
 */
import { registerActionHandler } from "./engine";
import type { NodeConfig, WorkflowExecutionContext } from "./types";

type Cfg = Record<string, any>;

// ── variable resolution ──────────────────────────────────────────────────
// Nested-path aware ({{candidate.cv.text}}) and able to return the RAW value
// (an object/array — e.g. a file descriptor) when the ref is a single token.

const SINGLE_TOKEN = /^\s*\{\{\s*([\w.[\]]+)\s*\}\}\s*$/;

function getPath(obj: any, pathStr: string): unknown {
  return String(pathStr)
    .replace(/\[(\w+)\]/g, ".$1")
    .split(".")
    .filter(Boolean)
    .reduce((acc: any, k) => (acc == null ? acc : acc[k]), obj);
}

/** Resolve a config ref to its RAW value. A lone `{{token}}` returns the raw
 *  variable (may be an object); an interpolated string returns a string. */
function resolveValue(ref: unknown, vars: Record<string, unknown>): unknown {
  if (typeof ref !== "string") return ref;
  const single = ref.match(SINGLE_TOKEN);
  if (single) {
    const v = getPath(vars, single[1]);
    return v === undefined ? "" : v;
  }
  if (ref.includes("{{")) {
    return ref.replace(/\{\{\s*([\w.[\]]+)\s*\}\}/g, (_m, k) => {
      const v = getPath(vars, k);
      return v == null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
    });
  }
  if (Object.prototype.hasOwnProperty.call(vars, ref)) return vars[ref];
  return ref;
}

function resolveString(ref: unknown, vars: Record<string, unknown>): string {
  const v = resolveValue(ref, vars);
  if (v == null) return "";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

// ── file descriptors → Claude document/image blocks ──────────────────────
// A resolved input may be a file descriptor produced by the upload pipeline:
//   { __forgeFile: { base64, mediaType, filename } }  (or the bare shape)
// or an array of them. Everything else is treated as text.

type Doc = { kind: "pdf" | "image"; base64: string; mediaType: string; filename?: string };

// A loader the storage layer registers (setFileLoader) so ai_extract can turn a
// stored-file id into base64 bytes without ai.ts depending on the storage module.
export type FileDescriptor = { base64: string; mediaType: string; filename?: string };
let fileLoader: ((ref: string) => Promise<FileDescriptor | null>) | null = null;
export function setFileLoader(fn: (ref: string) => Promise<FileDescriptor | null>): void {
  fileLoader = fn;
}

function descriptorToDoc(f: FileDescriptor): Doc | null {
  const mt = f.mediaType || "application/octet-stream";
  if (mt.includes("pdf")) return { kind: "pdf", base64: f.base64, mediaType: "application/pdf", filename: f.filename };
  if (mt.startsWith("image/")) return { kind: "image", base64: f.base64, mediaType: mt, filename: f.filename };
  return null;
}

async function loadById(id: string): Promise<Doc | null> {
  if (!fileLoader) return null;
  try {
    const loaded = await fileLoader(id);
    return loaded ? descriptorToDoc(loaded) : null;
  } catch (err) {
    console.warn("[workflow] fileLoader failed for", id, err);
    return null;
  }
}

/** Public wrapper so sibling handlers (ocr.ts, …) reuse the same fileLoader
 *  registration without each having to wire its own setter. Returns the raw
 *  {base64, mediaType, filename} descriptor — sibling handlers turn it into
 *  their preferred body shape (Claude document block, PaddleOCR base64, …). */
export async function getStoredFile(id: string): Promise<FileDescriptor | null> {
  if (!fileLoader) return null;
  try {
    return await fileLoader(id);
  } catch (err) {
    console.warn("[workflow] getStoredFile failed for", id, err);
    return null;
  }
}

// Resolve an explicit file ref into document blocks. Accepts: a stored-file id
// string; a JSON string of an id / array / descriptor; a {base64}/{__forgeFile}
// descriptor; a {id} reference (from FileUpload); or an array of any of these.
async function loadDocs(ref: unknown): Promise<Doc[]> {
  if (ref == null || ref === "") return [];
  if (typeof ref === "string") {
    const s = ref.trim();
    if (s.startsWith("{") || s.startsWith("[")) {
      try { return await loadDocs(JSON.parse(s)); } catch { /* fall through */ }
    }
    const d = await loadById(s);
    return d ? [d] : [];
  }
  const out: Doc[] = [];
  const items = Array.isArray(ref) ? ref : [ref];
  for (const it of items) {
    const desc: any = (it as any)?.__forgeFile ?? it;
    if (desc && typeof desc === "object" && (desc.base64 || desc.data)) {
      const d = descriptorToDoc({ base64: desc.base64 ?? desc.data, mediaType: desc.mediaType ?? desc.media_type ?? desc.contentType, filename: desc.filename });
      if (d) out.push(d);
    } else if (desc && typeof desc === "object" && typeof desc.id === "string") {
      const d = await loadById(desc.id);
      if (d) out.push(d);
    } else if (typeof it === "string") {
      const d = await loadById(it);
      if (d) out.push(d);
    }
  }
  return out;
}

function asDocuments(val: unknown): { docs: Doc[]; text: string } {
  const docs: Doc[] = [];
  const texts: string[] = [];
  const items = Array.isArray(val) ? val : [val];
  for (const it of items) {
    const f: any = (it as any)?.__forgeFile ?? it;
    const data = f && typeof f === "object" ? f.base64 ?? f.data : undefined;
    const mt = f && typeof f === "object" ? f.mediaType ?? f.media_type ?? f.contentType : undefined;
    if (data && typeof data === "string" && typeof mt === "string") {
      if (mt.includes("pdf")) docs.push({ kind: "pdf", base64: data, mediaType: "application/pdf", filename: f.filename });
      else if (mt.startsWith("image/")) docs.push({ kind: "image", base64: data, mediaType: mt, filename: f.filename });
      else texts.push(typeof f.text === "string" ? f.text : "");
    } else if (typeof it === "string") {
      texts.push(it);
    } else if (it != null) {
      texts.push(JSON.stringify(it));
    }
  }
  return { docs, text: texts.filter(Boolean).join("\n") };
}

// ── the LLM call (with mock fallback) ─────────────────────────────────────

async function aiModel(config: Cfg): Promise<string> {
  // Priority: workflow node's own config > DB-configured (integrations)
  // > env > default. getSecret handles the DB→env→default chain internally.
  if (typeof config.aiModel === "string" && config.aiModel) {
    return config.aiModel;
  }
  const { getSecret } = await import("@/lib/integrations/resolver");
  const dbOrEnv = await getSecret("anthropic", "FORGE_AI_MODEL");
  return dbOrEnv || process.env.ANTHROPIC_MODEL || "claude-sonnet-4-6";
}

interface LLMOpts {
  system: string;
  user: string;
  model: string;
  maxTokens?: number;
  temperature?: number;
  documents?: Doc[];
}

/** Returns the model's text response, or "" when no key/SDK is available (the
 *  caller then substitutes a deterministic mock). Never throws. */
async function callLLM(opts: LLMOpts): Promise<string> {
  // Credentials via getSecret() — admin can override env from the /settings/
  // integrations UI without restart. Falls through to process.env when
  // the DB row is empty.
  const { getSecret } = await import("@/lib/integrations/resolver");
  const apiKey = await getSecret("anthropic", "ANTHROPIC_API_KEY");
  if (!apiKey) {
    // In production, silently returning "" (which handlers turn into a
    // deterministic mock) would let ai_decide default to "approve",
    // ai_classify default to the first label at 0.85 confidence, and
    // ai_extract emit "Mock User" — all of which then flow into real DB
    // writes with only a console.log. Throw instead so the engine marks
    // the run failed. Dev keeps the mock so local generation works
    // without a key. Opt-in strict via FORGE_AI_STRICT=1.
    const isProd =
      process.env.NODE_ENV === "production" || process.env.FORGE_AI_STRICT === "1";
    if (isProd) {
      throw new Error(
        "AI not configured — set ANTHROPIC_API_KEY (via env or /settings/integrations)",
      );
    }
    console.log("[workflow] No ANTHROPIC_API_KEY — using mock AI response (dev)");
    return "";
  }
  try {
    const mod: any = await import("@anthropic-ai/sdk");
    const Anthropic = mod.default ?? mod.Anthropic ?? mod;
    const client = new Anthropic({ apiKey });
    const content: any[] = [];
    for (const d of opts.documents ?? []) {
      if (d.kind === "pdf") {
        content.push({ type: "document", source: { type: "base64", media_type: d.mediaType, data: d.base64 } });
      } else {
        content.push({ type: "image", source: { type: "base64", media_type: d.mediaType, data: d.base64 } });
      }
    }
    content.push({ type: "text", text: opts.user });
    const message = await client.messages.create({
      model: opts.model,
      max_tokens: opts.maxTokens ?? 1024,
      ...(opts.temperature != null ? { temperature: opts.temperature } : {}),
      system: opts.system,
      messages: [{ role: "user", content }],
    });
    const block = (message.content ?? []).find((b: any) => b.type === "text");
    return block ? String(block.text) : "";
  } catch (err) {
    console.warn("[workflow] LLM call failed, using mock:", err);
    return "";
  }
}

function parseJson(text: string): any {
  if (!text) return null;
  let t = text.trim();
  t = t.replace(/^```(?:json)?/i, "").replace(/```\s*$/i, "").trim();
  const start = t.search(/[[{]/);
  if (start > 0) t = t.slice(start);
  try {
    return JSON.parse(t);
  } catch {
    return null;
  }
}

// ── config normalizers ────────────────────────────────────────────────────

/** aiExtractFields accepts string[] OR {name,type}[] (editor shape). */
function extractFieldNames(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((f: any) => (typeof f === "string" ? f : f && typeof f === "object" ? String(f.name ?? f.field ?? "") : ""))
    .filter(Boolean);
}

function num(v: unknown, dflt: number): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : dflt;
}

// ── handlers ──────────────────────────────────────────────────────────────

export async function aiGenerate(config: NodeConfig, ctx: WorkflowExecutionContext): Promise<Record<string, unknown>> {
  const c = config as Cfg;
  const vars = (ctx.variables ?? {}) as Record<string, unknown>;
  const tone = resolveString(c.aiTone ?? "professional", vars) || "professional";
  const input = resolveString(c.aiInput ?? "", vars);
  const prompt = resolveString(c.aiPrompt ?? "", vars);
  const maxWords = num(c.aiMaxLength, 0);
  const lenHint = maxWords > 0 ? ` Keep it under ${maxWords} words.` : "";
  const system = c.aiSystemPrompt
    ? resolveString(c.aiSystemPrompt, vars)
    : `You are a content-generation assistant. Write in a ${tone} tone.${lenHint} Respond with JSON: {"generated_text": "<content>"}.`;
  const user = [prompt, input && `Context:\n${input}`].filter(Boolean).join("\n\n") || prompt || "Generate the requested content.";
  const raw = await callLLM({
    system,
    user,
    model: await aiModel(c),
    maxTokens: num(c.aiMaxTokens, 1024),
    temperature: c.aiTemperature != null ? num(c.aiTemperature, 1) : undefined,
  });
  let text: string;
  if (raw) {
    const p = parseJson(raw);
    text = (p?.generated_text ?? p?.text ?? raw) as string;
  } else {
    text = "This is mock-generated content for local development.";
  }
  // Include the contract-declared `text` key alongside the legacy names so
  // an outputMapping that promotes `{{node.output.text}}` doesn't resolve
  // to undefined. See workflow-audit "output declarations vs handler
  // returns" (~half the catalog).
  // A0-6 is fixed on the CONTRACT side, not here: `usage` was declared as a
  // promotable output but no path could produce it — callLLM returns a plain
  // string and never surfaces token counts. Returning fabricated zeros would be
  // worse than absent (it would report 0 tokens for a real call), so the
  // declaration was removed from actionContracts.ts instead. Re-add it here and
  // there together if callLLM ever exposes usage.
  return { text, generated_text: text, generated: text, tone, output: text };
}

export async function aiClassify(config: NodeConfig, ctx: WorkflowExecutionContext): Promise<Record<string, unknown>> {
  const c = config as Cfg;
  const vars = (ctx.variables ?? {}) as Record<string, unknown>;
  const input = resolveString(c.aiInput ?? "{{input}}", vars);
  const labels = (Array.isArray(c.aiLabels) ? c.aiLabels.map(String) : []).filter(Boolean);
  const labelList = labels.length ? labels : ["positive", "negative", "neutral"];
  const threshold = num(c.aiThreshold ?? c.aiConfidenceThreshold, 0.7);
  const extra = resolveString(c.aiPrompt ?? "", vars);
  const system = `You are a classification assistant. Classify the input into EXACTLY one of these labels: [${labelList.join(", ")}]. Respond with JSON: {"label": "<one label>", "confidence": <0..1>}.`;
  const user = [extra, `Input:\n${input}`].filter(Boolean).join("\n\n");
  const raw = await callLLM({ system, user, model: await aiModel(c), maxTokens: num(c.aiMaxTokens, 256) });
  const parsed = raw ? parseJson(raw) : null;
  const label = (parsed?.label ?? (raw ? String(raw).trim() : labelList[0])) as string;
  const confidence = num(parsed?.confidence, raw ? 0.5 : 0.85);
  return {
    label,
    classification: label,
    confidence,
    meets_threshold: confidence >= threshold,
    output: label,
  };
}

export async function aiExtract(config: NodeConfig, ctx: WorkflowExecutionContext): Promise<Record<string, unknown>> {
  const c = config as Cfg;
  const vars = (ctx.variables ?? {}) as Record<string, unknown>;
  const inputVal = resolveValue(c.aiInput ?? "{{input}}", vars);
  const { docs, text } = asDocuments(inputVal);
  // Explicit file reference (a stored-file id or descriptor) → document blocks.
  if (c.aiFileRef != null) {
    const extra = await loadDocs(resolveValue(c.aiFileRef, vars));
    docs.push(...extra);
  }
  const fields = extractFieldNames(c.aiExtractFields);
  const fieldList = fields.length ? fields : ["name", "email", "phone"];
  const extra = resolveString(c.aiPrompt ?? "", vars);
  const system = c.aiSystemPrompt
    ? resolveString(c.aiSystemPrompt, vars)
    : `You are a precise data-extraction assistant. Extract EXACTLY these fields from the input and respond with a SINGLE JSON object whose keys are exactly: [${fieldList.join(", ")}]. Use null when a field is absent. No commentary.`;
  const user =
    [extra, text && `Input:\n${text}`].filter(Boolean).join("\n\n") ||
    (docs.length ? "Extract the fields from the attached document." : "Extract the fields.");
  const raw = await callLLM({
    system,
    user,
    model: await aiModel(c),
    maxTokens: num(c.aiMaxTokens, 2048),
    documents: docs,
  });
  const parsed = raw ? parseJson(raw) ?? {} : mockExtract(fieldList);
  // Expose each extracted field as a top-level process variable so a downstream
  // db_insert/db_update can bind it directly (values: { column: "{{field}}" }).
  // Reserved roots are never overwritten.
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const reserved = new Set(["input", "user", "trigger", "now"]);
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (k && !reserved.has(k)) (ctx.variables as Record<string, unknown>)[k] = v;
    }
  }
  // Include contract-declared `data` alongside legacy names.
  return { data: parsed, extracted_fields: parsed, extracted: parsed, output: parsed };
}

export async function aiDecide(config: NodeConfig, ctx: WorkflowExecutionContext): Promise<Record<string, unknown>> {
  const c = config as Cfg;
  const vars = (ctx.variables ?? {}) as Record<string, unknown>;
  const context = resolveString(c.aiContext ?? c.aiInput ?? "", vars);
  const options = (Array.isArray(c.aiOptions) ? c.aiOptions.map(String) : []).filter(Boolean);
  const optList = options.length ? options : ["approve", "reject"];
  const rules = Array.isArray(c.aiRules)
    ? c.aiRules.map(String).join("\n")
    : resolveString(c.aiRules ?? "", vars);
  const prompt = resolveString(c.aiPrompt ?? "", vars);
  const system = `You are a decision-making assistant. Choose the single best option from: [${optList.join(", ")}]. Respond with JSON: {"decision": true|false, "option": "<one option>", "confidence": <0..1>, "reasoning": "<short>"}. decision=true selects the first/primary option.`;
  const user = [context && `Context:\n${context}`, rules && `Rules:\n${rules}`, prompt].filter(Boolean).join("\n\n") || "Make the decision.";
  const raw = await callLLM({ system, user, model: await aiModel(c), maxTokens: num(c.aiMaxTokens, 512) });
  const parsed = raw ? parseJson(raw) : null;
  const decision = parsed ? !!parsed.decision : true;
  const option = (parsed?.option as string) ?? optList[decision ? 0 : 1] ?? optList[0];
  const reasoning = (parsed?.reasoning as string) ?? (raw ? "" : "Mock decision — defaulting to the primary option.");
  // Include contract-declared `rationale` alongside legacy `reasoning`.
  return {
    decision,
    option,
    confidence: num(parsed?.confidence, 0.85),
    reasoning,
    rationale: reasoning,
    output: decision,
  };
}

function mockExtract(fields: string[]): Record<string, unknown> {
  const o: Record<string, unknown> = {};
  for (const f of fields) o[f] = null;
  if ("name" in o) o.name = "Mock User";
  if ("email" in o) o.email = "mock@example.com";
  return o;
}

// ── ai_identify_product: vision preset ──────────────────────────────────
// A specialised ai_extract for identifying a product in an image. Takes a
// forge_files id (or descriptor, or {{binding}} that resolves to one) via
// `image_file_id` (canonical) or `aiFileRef` (parity with ai_extract), sends
// the image to Claude with a fixed identify-product prompt, and returns
// {brand, model, category, attributes, confidence} strict-JSON. Throws on
// missing image or unparseable model output — this is a preset, so the
// caller expects the shape, not a mock.
const IDENTIFY_PRODUCT_PROMPT =
  "Identify the product in this image. Return a JSON object with these exact keys: " +
  "brand (string), model (string), category (string), attributes (object of key-value " +
  "pairs of any other visible characteristics like color, size, material), " +
  "confidence (a number between 0 and 1 representing how confident you are in " +
  "your identification — use 0.9+ for iconic/instantly-recognisable products, " +
  "0.6–0.8 for likely-but-uncertain matches, and below 0.5 when you're guessing). " +
  "If uncertain about a field, use null. Do NOT include prose — return JSON only.";

export async function aiIdentifyProduct(
  config: NodeConfig,
  ctx: WorkflowExecutionContext,
): Promise<Record<string, unknown>> {
  const c = config as Cfg;
  const vars = (ctx.variables ?? {}) as Record<string, unknown>;
  // Canonical input: image_file_id. Accept aiFileRef / aiInput for parity.
  const ref =
    c.image_file_id != null ? c.image_file_id :
    c.aiFileRef != null ? c.aiFileRef :
    c.aiInput != null ? c.aiInput : null;
  if (ref == null || ref === "") {
    throw new Error(
      "ai_identify_product: image_file_id is required (a forge_files id or FileUpload descriptor).",
    );
  }
  const docs = await loadDocs(resolveValue(ref, vars));
  const images = docs.filter((d) => d.kind === "image");
  if (images.length === 0) {
    throw new Error(
      "ai_identify_product: could not load an image from image_file_id — check the file id and mime-type (image/jpeg, image/png, image/webp, image/gif).",
    );
  }
  const prompt = c.aiPrompt
    ? resolveString(c.aiPrompt, vars)
    : IDENTIFY_PRODUCT_PROMPT;
  const system = c.aiSystemPrompt
    ? resolveString(c.aiSystemPrompt, vars)
    : "You are a precise product-identification assistant. Look at the image and identify the product. Respond with a SINGLE JSON object only — no prose, no markdown fences.";
  const raw = await callLLM({
    system,
    user: prompt,
    model: await aiModel(c),
    maxTokens: num(c.aiMaxTokens, 1024),
    documents: images,
  });
  if (!raw) {
    // No API key / SDK unavailable / call failed. Preset contract requires a
    // real answer — surface it instead of silently returning a mock.
    throw new Error(
      "ai_identify_product: no model response. Configure ANTHROPIC_API_KEY (env or /settings/integrations).",
    );
  }
  const parsed = parseJson(raw);
  if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(
      `ai_identify_product: model response was not a JSON object. Got: ${raw.slice(0, 200)}`,
    );
  }
  const obj = parsed as Record<string, unknown>;
  const brand = (obj.brand as string | null | undefined) ?? null;
  const model = (obj.model as string | null | undefined) ?? null;
  const category = (obj.category as string | null | undefined) ?? null;
  const attributes =
    obj.attributes && typeof obj.attributes === "object" && !Array.isArray(obj.attributes)
      ? (obj.attributes as Record<string, unknown>)
      : {};
  const confidence =
    typeof obj.confidence === "number" && Number.isFinite(obj.confidence)
      ? obj.confidence
      : undefined;
  // Promote to process vars (same treatment as ai_extract) so downstream
  // db_insert can bind {{brand}} / {{model}} / {{category}} directly.
  const reserved = new Set(["input", "user", "trigger", "now"]);
  for (const [k, v] of Object.entries({ brand, model, category, attributes })) {
    if (k && !reserved.has(k)) (ctx.variables as Record<string, unknown>)[k] = v as unknown;
  }
  return {
    brand,
    model,
    category,
    attributes,
    ...(confidence !== undefined ? { confidence } : {}),
    data: { brand, model, category, attributes, ...(confidence !== undefined ? { confidence } : {}) },
    output: { brand, model, category, attributes },
  };
}

/** Register all four real AI handlers (called from registerDefaultActions). */
export function registerAIActions(): void {
  registerActionHandler("ai_generate", aiGenerate as any);
  registerActionHandler("ai_classify", aiClassify as any);
  registerActionHandler("ai_extract", aiExtract as any);
  registerActionHandler("ai_decide", aiDecide as any);
  registerActionHandler("ai_identify_product", aiIdentifyProduct as any);
}
