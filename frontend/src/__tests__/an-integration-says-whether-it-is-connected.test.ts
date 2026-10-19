/**
 * The integrations page used to be one column of every key as a bare input.
 * Now each provider is a card that says whether it is connected, and the
 * rule for that lives in one place.
 */
import { describe, expect, it } from "vitest";
import { GROUPS, PROVIDERS, infoFor, lastUpdated, statusOf, type IntegrationEntry } from "@/app/org/[orgId]/settings/integrations/catalogue";

const e = (key: string, is_set: boolean, required = false, updated_at: string | null = null): IntegrationEntry =>
  ({ provider: "x", key, label: key, kind: "text", required, default: null, help_url: null, options: null, is_set, updated_at });

describe("an integration says whether it is connected", () => {
  it("is connected when every required key is set", () => {
    expect(statusOf([e("KEY", true, true), e("MODEL", false)])).toBe("connected");
  });
  it("needs attention when something is set but a required key is not", () => {
    expect(statusOf([e("KEY", false, true), e("MODEL", true)])).toBe("partial");
  });
  it("is connected when all keys are optional and one is set, and not set up when none is", () => {
    expect(statusOf([e("HOST", true), e("PORT", false)])).toBe("connected");
    expect(statusOf([e("HOST", false), e("PORT", false)])).toBe("unset");
  });
  it("reports the latest change across its keys", () => {
    expect(lastUpdated([e("A", true, false, "2026-10-01T00:00:00Z"), e("B", true, false, "2026-10-16T00:00:00Z")])).toBe("2026-10-16T00:00:00Z");
    expect(lastUpdated([e("A", false)])).toBeNull();
  });
  it("names every provider the pipeline knows, and files an unknown one under Platform", () => {
    for (const p of ["resend", "smtp", "anthropic", "embeddings", "stripe", "figma", "uxpilot", "unsplash", "s3", "paddleocr", "cloudflare", "route53", "godaddy",
                     "expo_eas", "apple_asc", "google_play", "cron", "push", "encryption", "mcp"]) {
      expect(PROVIDERS[p]?.name, p).toBeTruthy();
      expect(GROUPS.some((g) => g.id === PROVIDERS[p].group), p).toBe(true);
    }
    expect(infoFor("something_new")).toMatchObject({ name: "something_new", group: "platform" });
  });
});

import { matches } from "@/app/org/[orgId]/settings/integrations/catalogue";

describe("the search finds a provider by what the person knows it as", () => {
  const s3 = [{ key: "AWS_SECRET_ACCESS_KEY", label: "AWS secret access key" }, { key: "FORGE_S3_BUCKET", label: "S3 bucket" }];
  it("matches the name, the purpose, the group, the id and the keys", () => {
    expect(matches("s3", s3, "amazon")).toBe(true);       // the name
    expect(matches("s3", s3, "upload")).toBe(true);       // what it is for
    expect(matches("s3", s3, "files")).toBe(true);        // the group
    expect(matches("s3", s3, "aws_secret")).toBe(true);   // a key
    expect(matches("apple_asc", [], "app store")).toBe(true);
    expect(matches("s3", s3, "payments")).toBe(false);
  });
  it("needs every word, in any order, and an empty search matches all", () => {
    expect(matches("s3", s3, "secret aws")).toBe(true);
    expect(matches("s3", s3, "aws stripe")).toBe(false);
    expect(matches("s3", s3, "   ")).toBe(true);
  });
});
