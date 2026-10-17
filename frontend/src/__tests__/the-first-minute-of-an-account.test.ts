/**
 * Sign-up lands on one question — what kind of account — and the create form
 * shows the slug as the name is typed and takes a list of emails in one box.
 */
import { describe, expect, it } from "vitest";
import { ACCOUNT_TYPES, ROLES, badEmails, parseEmails, slugPreview, slugProblem } from "@/app/start/lib";

describe("the first minute of an account", () => {
  it("offers personal, business and joining a team, in that order", () => {
    expect(ACCOUNT_TYPES.map((a) => a.value)).toEqual(["personal", "business", "joining"]);
  });
  it("says what every role may do", () => {
    for (const r of ROLES) expect(r.hint.length).toBeGreaterThan(20);
    expect(ROLES.map((r) => r.value).sort()).toEqual(["admin", "member", "owner"]);
  });
  it("reads emails from one box however they were separated, each once", () => {
    expect(parseEmails("Ann@x.co, bob@x.co;  ann@x.co\ncat@x.co")).toEqual(["ann@x.co", "bob@x.co", "cat@x.co"]);
    expect(badEmails(["ann@x.co", "nope", "a@b"])).toEqual(["nope", "a@b"]);
  });
  it("shows the slug the name makes and refuses one a person broke by hand", () => {
    expect(slugPreview("Tentoro IND")).toBe("tentoro-ind");
    expect(slugPreview("")).toBe("");   // an empty name shows no made-up address
    expect(slugProblem("tentoro-ind")).toBe("");
    expect(slugProblem("Tentoro IND")).toMatch(/lower-case/);
    expect(slugProblem("")).toMatch(/address/);
  });
});
