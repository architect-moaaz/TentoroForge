/**
 * The Invite button said "Sending..." and sent nothing, and nobody was told
 * what to do next. The notice under the form now says what happened and, when
 * nothing was emailed, hands over the sign-up address to pass on.
 */
import { describe, expect, it } from "vitest";
import { describeInvite } from "@/app/org/[orgId]/settings/invites";

const base = { id: "i1", invite_email: "zed@example.com", role: "member", invite_status: "pending" };

describe("what an invitation did", () => {
  it("says a person with an account is in already", () => {
    const { text, link } = describeInvite({ ...base, invite_status: "accepted", joined: true, emailed: false, invite_url: "" });
    expect(text).toContain("already had a Forge account");
    expect(link).toBe("");
  });
  it("says the email went, and still offers the address", () => {
    const { text, link } = describeInvite({ ...base, joined: false, emailed: true, invite_url: "https://forge-v3.tentoro.ai/signup?email=zed%40example.com" });
    expect(text).toContain("emailed to zed@example.com");
    expect(link).toContain("/signup?email=");
  });
  it("hands over the address when no mail service is set up", () => {
    const { text, link } = describeInvite({ ...base, joined: false, emailed: false, invite_url: "https://forge-v3.tentoro.ai/signup?email=zed%40example.com" });
    expect(text).toContain("No email service is set up here");
    expect(link).toBe("https://forge-v3.tentoro.ai/signup?email=zed%40example.com");
  });
});
