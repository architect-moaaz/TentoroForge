import { validate, parse, tokenize } from "../../templates/runtime/feel-lite/index";
// stdin: JSON array of {id, expression}; stdout: JSON array of {id, ok, error}.
// The engine's own tokenizer and parser, so what is refused here is exactly
// what the engine would refuse at run time.
const FUNCTIONS = "sum, count, min, max, avg, abs, floor, ceiling, round, contains, starts with, ends with, matches, string, number, date, now, duration";
let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  const items = JSON.parse(raw || "[]") as Array<{ id: string; expression: string }>;
  const out = items.map(({ id, expression }) => {
    try {
      parse(tokenize(expression));
      const v = validate(expression) as { valid?: boolean; ok?: boolean; issues?: Array<{ message: string; severity?: string }> };
      // The validator files an unknown function as a warning; the evaluator
      // throws on it. What throws at run time is refused here.
      const errors = (v.issues || []).filter(
        (i) => !i.severity || i.severity === "error" || /^Unknown function/.test(i.message),
      ).map((i) => (/^Unknown function/.test(i.message) ? { ...i, message: `${i.message} — the engine has ${FUNCTIONS}` } : i));
      if (v.valid === false || v.ok === false || errors.length) return { id, ok: false, error: errors.map((i) => i.message).join("; ") || "invalid" };
      return { id, ok: true };
    } catch (e) {
      return { id, ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  });
  process.stdout.write(JSON.stringify(out));
});
