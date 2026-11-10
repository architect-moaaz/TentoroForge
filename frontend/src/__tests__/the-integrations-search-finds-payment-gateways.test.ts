/**
 * Payment gateways are the Payments group of Settings → Integrations, and the
 * page's one search box finds them as it finds every other integration: by
 * name, by provider, by a currency they take, by what they are for.
 */
import { describe, expect, it } from "vitest";
import { gatewayMatches } from "@/components/payments/GatewaysSection";
import { paymentsSettingsHref, type Gateway } from "@/lib/payment-gateways";

const g = (over: Partial<Gateway>): Gateway => ({
  id: "g1", provider: "razorpay", providerName: "Razorpay", label: "Razorpay India", coverage: "domestic", homeCountry: "IN",
  currencies: ["INR"], isDefault: true, status: "test_only", testName: "Test mode",
  modes: { test: { set: true, check: null }, live: { set: false, check: null } },
  ...over,
} as unknown as Gateway);

describe("the Integrations search and payment gateways", () => {
  it("finds a gateway by its name, its provider and a currency it takes", () => {
    const rzp = g({});
    expect(gatewayMatches(rzp, "")).toBe(true);
    expect(gatewayMatches(rzp, "razorpay")).toBe(true);
    expect(gatewayMatches(rzp, "India")).toBe(true);
    expect(gatewayMatches(rzp, "inr")).toBe(true);
    expect(gatewayMatches(rzp, "subscription")).toBe(true);
    expect(gatewayMatches(rzp, "usd")).toBe(false);
    expect(gatewayMatches(rzp, "email")).toBe(false);
  });
  it("needs every word to match", () => {
    expect(gatewayMatches(g({}), "razorpay inr")).toBe(true);
    expect(gatewayMatches(g({}), "razorpay eur")).toBe(false);
  });
  it("sends every link to the one place gateways are managed", () => {
    expect(paymentsSettingsHref("org-1")).toBe("/org/org-1/settings/integrations#payments");
  });
});
