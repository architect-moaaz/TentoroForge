/**
 * A web form leans on the browser to refuse an empty required field, a bad email
 * or a date that is not a date; a phone has no such check, so the SDK has it. By
 * kind of the web's WorkflowForm vocabulary: what is refused and in what words,
 * and how a whole form's values become the workflow's input (fixed values sent,
 * empty fields left out, a datetime normalised, a step checked alone).
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();
const form = await import("../src/sdk/form.ts");

const bad = (kind: any, value: unknown, extra: object = {}, required = false) =>
  form.validateValue({ kind, label: "Field", ...extra }, value, required);

console.log("required");
eqJson(bad("text", "", {}, true), "Field is required.", "an empty required text");
eqJson(bad("text", "   ", {}, true), "Field is required.", "blank is empty");
eqJson(bad("multiselect", [], {}, true), "Field is required.", "an empty list is empty");
eqJson(bad("text", "", {}, false), null, "an optional empty field is fine, whatever its kind");
eqJson(bad("email", "", {}, false), null, "…an empty optional email is not 'not an email'");
eqJson(bad("switch", undefined, {}, true), null, "a switch is never 'missing': off is an answer");
eqJson(bad("number", 0, {}, true), null, "zero is a value, not an empty one");

console.log("by kind");
eqJson([bad("email", "ada@x.io"), bad("email", "ada@x"), bad("email", "a b@x.io")], [null, "Field must be an email address.", "Field must be an email address."], "email");
eqJson([bad("url", "https://x.io/a"), bad("url", "x.io")], [null, "Field must be a web address starting with http."], "url");
eqJson([bad("tel", "+44 20 7946 0958"), bad("tel", "12")], [null, "Field must be a phone number."], "tel");
eqJson([bad("number", 12.5), bad("number", Number.NaN), bad("number", "12")], [null, "Field must be a number.", "Field must be a number."], "number: a real number, not text or NaN");
eqJson([bad("number", 5, { min: 10 }), bad("number", 50, { max: 10 }), bad("money", 10, { min: 10, max: 10 })], ["Field must be at least 10.", "Field must be at most 10.", null], "min and max, inclusive");
eqJson([bad("date", "2026-03-01"), bad("date", "2026-02-30"), bad("date", "2026-13-01"), bad("date", "1/3/2026")],
  [null, "Field must be a date, like 2026-03-01.", "Field must be a date, like 2026-03-01.", "Field must be a date, like 2026-03-01."], "date: a real calendar day, ISO");
eqJson([bad("date", "2024-02-29"), bad("date", "2025-02-29")], [null, "Field must be a date, like 2026-03-01."], "leap years");
eqJson([bad("time", "14:30"), bad("time", "24:00"), bad("time", "9:5")], [null, "Field must be a time, like 14:30.", "Field must be a time, like 14:30."], "time: 24-hour HH:MM");
eqJson([bad("datetime", "2026-03-01 14:30"), bad("datetime", "2026-03-01T14:30"), bad("datetime", "2026-03-01"), bad("datetime", "2026-03-01 25:00")],
  [null, null, "Field must be a date and time, like 2026-03-01 14:30.", "Field must be a date and time, like 2026-03-01 14:30."], "datetime: a space or a T");
const options = [{ label: "Open", value: "open" }, { label: "Done", value: "done" }];
eqJson([bad("select", "open", { options }), bad("select", "other", { options }), bad("select", "anything", {})], [null, "Field: choose one of the options.", null], "select: one of the options (any value when none are given)");
eqJson([bad("multiselect", ["open", "done"], { options }), bad("multiselect", ["open", "x"], { options })], [null, "Field: choose from the options."], "multiselect");
eqJson([bad("location", { lat: 1, lng: 2 }), bad("location", { lat: "1" })], [null, "Field needs a location."], "location is a point");

console.log("typed text becoming values");
eqJson([form.numberFromText("12.5"), form.numberFromText("1,5"), form.numberFromText(""), form.numberFromText("abc"), form.numberFromText("-3"), form.numberFromText("1,234"), form.numberFromText("1,234.50")],
  [12.5, 1.5, undefined, null, -3, 1234, 1234.5], "a number from what is typed: decimal comma, grouping, empty is not set, junk is null");
eqJson(form.normaliseDateTime("2026-03-01 9:05"), "2026-03-01T09:05", "a datetime's one stored shape");
eqJson(form.nowText("datetime", new Date(2026, 2, 1, 9, 5)), "2026-03-01 09:05", "'Now' in the device's own time");
eqJson([form.nowText("date", new Date(2026, 2, 1, 9, 5)), form.nowText("time", new Date(2026, 2, 1, 9, 5))], ["2026-03-01", "09:05"], "'Today' and a time");

console.log("a whole form");
{
  const specs = {
    title: { label: "Title", kind: "text" },
    email: { label: "Email", kind: "email" },
    amount: { label: "Amount", kind: "money", min: 0 },
    due: { label: "Due", kind: "datetime" },
    done: { label: "Done", kind: "switch" },
    tags: { label: "Tags", kind: "tags" },
    source: { value: "mobile" },
    note: { label: "Note", kind: "textarea" },
  } as const;
  const r = form.collectInput(specs as any, { title: "Fix", amount: 12.5, due: "2026-03-01 9:05", done: false, tags: [], note: "" }, ["title", "amount"]);
  eqJson(r.errors, {}, "a good form has no errors");
  eqJson(r.input, { title: "Fix", amount: 12.5, due: "2026-03-01T09:05", done: false, tags: [], source: "mobile" },
    "fixed values are sent, empty fields are left out, false and [] are kept, the datetime is normalised");

  const wrong = form.collectInput(specs as any, { email: "nope", amount: -1 }, ["title", "amount"]);
  eqJson(wrong.errors, { title: "Title is required.", email: "Email must be an email address.", amount: "Amount must be at least 0." }, "every field that is wrong says so, by name");

  const step = form.collectInput(specs as any, { email: "nope" }, ["title"], ["email"]);
  eqJson(Object.keys(step.errors), ["email"], "a step checks only its own fields (title is for a later step)");
  eqJson(form.collectInput(specs as any, {}, new Set(["title"])).errors.title, "Title is required.", "required may be a Set (the workflow's list or a set of it)");
  ok(form.isFixed({ value: undefined }) && !form.isFixed({ label: "x" }), "a spec with `value` is fixed, even if the value is undefined");
}

done("form");
