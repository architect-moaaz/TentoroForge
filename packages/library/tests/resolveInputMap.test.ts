import { describe, expect, it } from "vitest";
import { resolveInputMap } from "../src/util/resolveInputMap";

describe("resolveInputMap", () => {
  describe("route source", () => {
    it("resolves against ctx.routeParams", () => {
      const r = resolveInputMap(
        { applicantId: { kind: "route", param: "id" } },
        { routeParams: { id: "abc-123" } },
      );
      expect(r.args).toEqual({ applicantId: "abc-123" });
      expect(r.unresolved).toEqual([]);
    });

    it("reports unresolved when param is missing", () => {
      const r = resolveInputMap(
        { applicantId: { kind: "route", param: "id" } },
        { routeParams: {} },
      );
      expect(r.args).toEqual({});
      expect(r.unresolved).toHaveLength(1);
      expect(r.unresolved[0].name).toBe("applicantId");
    });

    it("reports missing param key", () => {
      const r = resolveInputMap(
        { x: { kind: "route" } as unknown },
        { routeParams: { id: "1" } },
      );
      expect(r.unresolved[0].reason).toContain("param");
    });
  });

  describe("auth source", () => {
    it("resolves against ctx.authClaims", () => {
      const r = resolveInputMap(
        { reviewerId: { kind: "auth", claim: "user.id" } },
        { authClaims: { "user.id": "u_9" } },
      );
      expect(r.args).toEqual({ reviewerId: "u_9" });
    });

    it("reports unresolved when claim is missing", () => {
      const r = resolveInputMap(
        { reviewerId: { kind: "auth", claim: "user.id" } },
        { authClaims: {} },
      );
      expect(r.args).toEqual({});
      expect(r.unresolved).toHaveLength(1);
    });
  });

  describe("form_field source", () => {
    it("resolves against ctx.formValues", () => {
      const r = resolveInputMap(
        { rating: { kind: "form_field", field: "rating" } },
        { formValues: { rating: 4 } },
      );
      expect(r.args).toEqual({ rating: 4 });
    });

    it("treats empty string as resolved (a real form value)", () => {
      const r = resolveInputMap(
        { notes: { kind: "form_field", field: "notes" } },
        { formValues: { notes: "" } },
      );
      expect(r.args).toEqual({ notes: "" });
      expect(r.unresolved).toEqual([]);
    });

    it("reports unresolved when field is truly absent", () => {
      const r = resolveInputMap(
        { notes: { kind: "form_field", field: "notes" } },
        { formValues: {} },
      );
      expect(r.args).toEqual({});
      expect(r.unresolved).toHaveLength(1);
    });
  });

  describe("static source", () => {
    it("passes literal values through", () => {
      const r = resolveInputMap(
        { decision: { kind: "static", value: "approved" } },
        {},
      );
      expect(r.args).toEqual({ decision: "approved" });
    });

    it("passes numbers/bools through unchanged", () => {
      const r = resolveInputMap(
        {
          count:   { kind: "static", value: 3 },
          enabled: { kind: "static", value: true },
        },
        {},
      );
      expect(r.args).toEqual({ count: 3, enabled: true });
    });

    it("expands {{now}} via ctx.now", () => {
      const r = resolveInputMap(
        { createdAt: { kind: "static", value: "{{now}}" } },
        { now: () => "2026-07-30T00:00:00Z" },
      );
      expect(r.args).toEqual({ createdAt: "2026-07-30T00:00:00Z" });
    });

    it("expands {{uuid}} via ctx.uuid", () => {
      const r = resolveInputMap(
        { id: { kind: "static", value: "{{uuid}}" } },
        { uuid: () => "test-uuid" },
      );
      expect(r.args).toEqual({ id: "test-uuid" });
    });
  });

  describe("computed source", () => {
    it("reports unresolved (v2 — not implemented)", () => {
      const r = resolveInputMap(
        { total: { kind: "computed", expression: "a + b" } },
        {},
      );
      expect(r.args).toEqual({});
      expect(r.unresolved).toHaveLength(1);
      expect(r.unresolved[0].reason).toContain("computed");
    });
  });

  describe("errors + edge cases", () => {
    it("returns empty result for null/undefined map", () => {
      expect(resolveInputMap(null, {}).args).toEqual({});
      expect(resolveInputMap(undefined, {}).args).toEqual({});
    });

    it("returns empty result for non-object map", () => {
      const r = resolveInputMap("bogus" as unknown as Record<string, unknown>, {});
      expect(r.args).toEqual({});
      expect(r.unresolved).toEqual([]);
    });

    it("skips entries with unknown source kind", () => {
      const r = resolveInputMap(
        { x: { kind: "hocus_pocus" } as unknown },
        {},
      );
      expect(r.args).toEqual({});
      expect(r.unresolved[0].reason).toContain("unknown source kind");
    });

    it("skips non-dict specs", () => {
      const r = resolveInputMap({ x: "route.id" } as unknown as Record<string, unknown>, {});
      expect(r.args).toEqual({});
      expect(r.unresolved[0].reason).toContain("object");
    });

    it("processes mixed sources in one call", () => {
      const r = resolveInputMap(
        {
          applicantId: { kind: "route",      param: "id" },
          reviewerId: { kind: "auth",       claim: "user.id" },
          rating:     { kind: "form_field", field: "rating" },
          decision:   { kind: "static",     value: "approved" },
        },
        {
          routeParams: { id: "a_1" },
          authClaims:  { "user.id": "u_9" },
          formValues:  { rating: 5 },
        },
      );
      expect(r.args).toEqual({
        applicantId: "a_1",
        reviewerId:  "u_9",
        rating:      5,
        decision:    "approved",
      });
      expect(r.unresolved).toEqual([]);
    });

    it("collects multiple unresolved entries in order", () => {
      const r = resolveInputMap(
        {
          a: { kind: "route", param: "missing" },
          b: { kind: "auth",  claim: "missing" },
        },
        {},
      );
      expect(r.args).toEqual({});
      expect(r.unresolved.map((u) => u.name)).toEqual(["a", "b"]);
    });

    it("never throws on garbage input", () => {
      expect(() => resolveInputMap(
        { x: 42 as unknown as Record<string, unknown> },
        {},
      )).not.toThrow();
    });
  });
});
