/**
 * Every system an app declares has a card, named as the app named it, under
 * Connected systems — beside Mews, which the runtime signs calls to itself.
 * Three apps declared Mews and the page showed no card for any of it.
 */
import { describe, expect, it } from "vitest";
import { GROUPS, PROVIDERS, infoFor, matches } from "@/app/org/[orgId]/settings/integrations/catalogue";

const declared = [
  { key: "MEWS_ENTERPRISE_ID", label: "Mews PMS Connector — MEWS_ENTERPRISE_ID" },
  { key: "MEWS_WEBHOOK_SECRET", label: "Mews PMS Connector — MEWS_WEBHOOK_SECRET" },
];

describe("a system an app declares has its card", () => {
  it("names Mews and files it under Connected systems", () => {
    expect(PROVIDERS.mews?.name).toBe("Mews");
    expect(PROVIDERS.mews?.group).toBe("systems");
    expect(GROUPS.some((g) => g.id === "systems")).toBe(true);
  });
  it("names an app's own system from its keys' labels", () => {
    const info = infoFor("app:mews-p-m-s-connector", declared);
    expect(info.name).toBe("Mews PMS Connector");
    expect(info.group).toBe("systems");
  });
  it("falls back to the slug when no label names it", () => {
    expect(infoFor("app:xero-payroll").name).toBe("Xero Payroll");
  });
  it("is found by the name the app gave it and by its key names", () => {
    expect(matches("app:mews-p-m-s-connector", declared, "mews pms")).toBe(true);
    expect(matches("app:mews-p-m-s-connector", declared, "ENTERPRISE")).toBe(true);
  });
});
