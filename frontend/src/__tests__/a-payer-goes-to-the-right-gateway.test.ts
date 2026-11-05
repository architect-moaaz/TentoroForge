/**
 * The rule Settings → Payments previews and the build dialog ticks by: the
 * domestic gateway for its own country and currency, the international one
 * for everyone else; the best gateways pre-ticked for a new app; a key's
 * prefix says which mode it belongs to. The same rule the generated app runs
 * (backend/templates/runtime/payments/routing.ts).
 */
import { describe, expect, it } from "vitest";
import { fieldOfKey, modeOfKey, prefixProblem, routeFor, routingLines, suggested, type Gateway, type ProviderInfo } from "@/lib/payment-gateways";
import { readPrice } from "@/components/payments/PaymentChoiceDialog";

const g = (over: Partial<Gateway>): Gateway => ({
  id: over.provider ?? "x", provider: "stripe", providerName: "", label: over.provider ?? "x", coverage: "both", homeCountry: null,
  currencies: ["USD"], isDefault: false, status: "ready", modes: { test: { set: true, check: null }, live: { set: true, check: null } },
  webhooks: "auto", testName: "Test mode", createdAt: null, updatedAt: null, ...over,
});

const rzp = g({ id: "r", provider: "razorpay", label: "Razorpay India", coverage: "domestic", homeCountry: "IN", currencies: ["INR"] });
const stripe = g({ id: "s", provider: "stripe", label: "Stripe", coverage: "international", currencies: ["USD", "EUR", "AED", "INR"], isDefault: true });
const paypal = g({ id: "p", provider: "paypal", label: "PayPal", coverage: "international", currencies: ["USD", "EUR"] });

describe("routing", () => {
  it("sends INR at home to the domestic gateway and everything else abroad", () => {
    const all = [rzp, stripe, paypal];
    expect(routeFor(all, "INR", "IN")?.id).toBe("r");
    expect(routeFor(all, "INR")?.id).toBe("r");
    expect(routeFor(all, "INR", "US")?.id).toBe("s");
    expect(routeFor(all, "USD", "IN")?.id).toBe("s");
    expect(routeFor(all, "JPY", "JP")).toBeNull();
  });
  it("lists who takes each currency once", () => {
    const lines = routingLines([rzp, stripe, paypal]);
    expect(lines.map((l) => `${l.currency}:${l.gateway.id}`)).toEqual(["INR:r", "USD:s", "EUR:s", "AED:s"]);
  });
});

describe("suggested gateways for a new app", () => {
  it("ticks the domestic one for its currency and an international partner", () => {
    expect(suggested([stripe, rzp, paypal], "INR").map((x) => x.id)).toEqual(["r", "s"]);
  });
  it("ticks the default and the domestic one for a foreign currency", () => {
    expect(suggested([stripe, rzp], "USD").map((x) => x.id)).toEqual(["s", "r"]);
  });
  it("never ticks a gateway whose keys were refused", () => {
    expect(suggested([{ ...rzp, status: "attention" }, stripe], "INR").map((x) => x.id)).toEqual(["s"]);
  });
  it("ticks nothing when there is nothing", () => {
    expect(suggested([], "INR")).toEqual([]);
  });
});

describe("a key's prefix", () => {
  const razorpay: ProviderInfo = {
    id: "razorpay", name: "Razorpay", tagline: "", coverage: "domestic", homeCountry: "IN", currencies: ["INR"], defaultCurrencies: ["INR"],
    testName: "Test mode", keysUrl: {}, webhooks: "manual", paymentMethods: "",
    fields: [
      { key: "key_id", label: "Key ID", secret: false, required: true, prefix: { test: ["rzp_test_"], live: ["rzp_live_"] }, help: "" },
      { key: "key_secret", label: "Key secret", secret: true, required: true, prefix: {}, help: "" },
    ],
  };
  it("says which mode a pasted key belongs to", () => {
    expect(modeOfKey(razorpay, " rzp_live_Abc")).toBe("live");
    expect(modeOfKey(razorpay, "rzp_test_Abc")).toBe("test");
    expect(modeOfKey(razorpay, "somethingElse")).toBeNull();
  });
  it("names the mistake in the person's words", () => {
    const f = razorpay.fields[0];
    expect(prefixProblem(f, "test", "rzp_live_X", "Test mode")).toBe("This is a live key — it goes under Live.");
    expect(prefixProblem(f, "live", "rzp_test_X", "Test mode")).toBe("This is a test mode key — it goes under Test mode.");
    expect(prefixProblem(f, "test", "abc", "Test mode")).toBe("Should start with rzp_test_");
    expect(prefixProblem(f, "test", "", "Test mode")).toBe("");
    expect(prefixProblem(razorpay.fields[1], "test", "anything", "Test mode")).toBe("");
  });
});


describe("brutal round 1", () => {
  it("never pre-ticks two accounts of one provider (the server refuses an app on two Stripe accounts)", () => {
    const stripeUS = g({ id: "us", provider: "stripe", currencies: ["USD"] });
    const stripeEU = g({ id: "eu", provider: "stripe", currencies: ["EUR"], isDefault: true });
    expect(suggested([stripeUS, stripeEU], "USD").map((x) => x.id)).toEqual(["us"]);
  });
  it("finds the field a pasted key belongs in — a Key ID pasted where the secret goes", () => {
    const razorpay: ProviderInfo = {
      id: "razorpay", name: "Razorpay", tagline: "", coverage: "domestic", homeCountry: "IN", currencies: ["INR"], defaultCurrencies: ["INR"],
      testName: "Test mode", keysUrl: {}, webhooks: "manual", paymentMethods: "",
      fields: [
        { key: "key_id", label: "Key ID", secret: false, required: true, prefix: { test: ["rzp_test_"], live: ["rzp_live_"] }, help: "" },
        { key: "key_secret", label: "Key secret", secret: true, required: true, prefix: {}, help: "" },
      ],
    };
    const found = fieldOfKey(razorpay, " rzp_live_Abc123 ");
    expect(found?.field.key).toBe("key_id");
    expect(found?.mode).toBe("live");
    expect(fieldOfKey(razorpay, "plainsecretvalue")).toBeNull();
  });
  it("reads a typed price against its currency's decimals, and says why it cannot be charged", () => {
    expect(readPrice("", "USD")).toEqual({ value: null, problem: "" });
    expect(readPrice("5", "USD").value).toBe(5);
    expect(readPrice("-5", "USD").problem).toMatch(/more than zero/);
    expect(readPrice("0", "USD").problem).toMatch(/more than zero/);
    expect(readPrice("abc", "USD").problem).toMatch(/not a number/);
    expect(readPrice("5.999", "USD").problem).toMatch(/more than 2 decimals/);
    expect(readPrice("1.255", "KWD").value).toBe(1.255);
    expect(readPrice("500.5", "JPY").problem).toMatch(/no decimals/);
  });
});
