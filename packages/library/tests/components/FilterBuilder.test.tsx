/**
 * FilterBuilder — Spec E Wave 3.
 *
 * Covers: empty state, adding + removing clauses, encoding to URL,
 * and round-tripping via decode.
 */
import { describe, it, expect, afterEach, beforeEach } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import * as React from "react";

import {
  FilterBuilder,
  encodeFilterExpression,
  decodeFilterExpression,
} from "../../src";

const fields = [
  { name: "status", label: "Status", type: "enum" as const, options: [{ value: "open", label: "Open" }, { value: "closed", label: "Closed" }] },
  { name: "amount", label: "Amount", type: "number" as const },
];

describe("FilterBuilder", () => {
  beforeEach(() => window.history.replaceState({}, "", "/"));
  afterEach(() => cleanup());

  it("shows the empty prompt when there are no clauses", () => {
    const { getByText } = render(<FilterBuilder fields={fields} />);
    getByText("Add a filter…");
  });

  it("adds a clause when the empty prompt is clicked", () => {
    const { getByText, container } = render(<FilterBuilder fields={fields} />);
    fireEvent.click(getByText("Add a filter…"));
    expect(container.querySelectorAll("[data-forge-filter-clause]").length).toBe(1);
  });

  it("Apply writes the encoded expression to the URL", () => {
    const { getByText } = render(<FilterBuilder fields={fields} paramKey="q" />);
    fireEvent.click(getByText("Add a filter…"));
    fireEvent.click(getByText("Apply"));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("q")).toBeTruthy();
  });

  it("encode/decode round-trips a clause list", () => {
    const expr = {
      combinator: "AND" as const,
      clauses: [{ field: "status", op: "eq", value: "open" }],
    };
    const round = decodeFilterExpression(encodeFilterExpression(expr));
    expect(round).toEqual(expr);
  });

  it("decode returns an empty expr on garbage input", () => {
    expect(decodeFilterExpression("not-json")).toEqual({
      combinator: "AND",
      clauses: [],
    });
  });
});
