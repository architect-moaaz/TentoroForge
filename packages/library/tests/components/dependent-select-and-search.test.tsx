/**
 * A Select whose options depend on a sibling narrows to the sibling's live
 * value, and offers nothing until the sibling is chosen. A search Input is
 * the page's search: it names itself `q`.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import * as React from "react";
import { Select } from "../../src/components/Select/Select";
import { Input } from "../../src/components/Input/Input";
import { FormValuesContext } from "../../src/components/Form/FormValuesContext";

const options = [
  { value: "c1", label: "Austin" },
  { value: "c2", label: "Boston" },
];
const dependsOn = { field: "state", keys: { c1: "TX", c2: "MA" } };

describe("dependent Select", () => {
  it("offers only the options under the parent's current value", () => {
    render(
      <FormValuesContext.Provider value={{ state: "TX" }}>
        <Select name="city" label="City" options={options} {...({ dependsOn } as any)} />
      </FormValuesContext.Provider>,
    );
    expect(screen.queryByText("Austin")).not.toBeNull();
    expect(screen.queryByText("Boston")).toBeNull();
  });

  it("offers nothing until the parent is chosen", () => {
    render(
      <FormValuesContext.Provider value={{}}>
        <Select name="city" label="City" options={options} {...({ dependsOn } as any)} />
      </FormValuesContext.Provider>,
    );
    expect(screen.queryByText("Austin")).toBeNull();
    expect(screen.queryByText("Boston")).toBeNull();
  });

  it("is an ordinary Select outside a Form", () => {
    render(<Select name="city" label="City" options={options} {...({ dependsOn } as any)} />);
    expect(screen.queryByText("Austin")).not.toBeNull();
    expect(screen.queryByText("Boston")).not.toBeNull();
  });
});

describe("search Input", () => {
  it("names itself q so the page's list source searches it", () => {
    const { container } = render(<Input name="" type="search" placeholder="Search policies..." />);
    const el = container.querySelector("input") as HTMLInputElement;
    expect(el.name).toBe("q");
    expect(el.type).toBe("search");
  });
});
