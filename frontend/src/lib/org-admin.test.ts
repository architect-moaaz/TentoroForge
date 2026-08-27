import { describe, it, expect } from "vitest";
import { isOrgAdmin } from "./org-admin";

const user = (role: string, org = "o1") => ({ orgs: [{ org_id: org, role }] });

describe("isOrgAdmin", () => {
  it("is true for an owner of the org", () => {
    expect(isOrgAdmin(user("owner"), "o1")).toBe(true);
  });
  it("is true for an admin of the org", () => {
    expect(isOrgAdmin(user("admin"), "o1")).toBe(true);
  });
  it("is false for a member", () => {
    expect(isOrgAdmin(user("member"), "o1")).toBe(false);
  });
  it("is false for an admin of a different org", () => {
    expect(isOrgAdmin(user("admin", "other"), "o1")).toBe(false);
  });
  it("is false when user is null/undefined", () => {
    expect(isOrgAdmin(null, "o1")).toBe(false);
    expect(isOrgAdmin(undefined, "o1")).toBe(false);
  });
});
