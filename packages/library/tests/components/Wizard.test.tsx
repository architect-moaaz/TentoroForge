/**
 * Wizard — Spec E Wave 3.
 *
 * Covers: step progression, required-field gating, review pane, and
 * final onComplete workflow dispatch via the `forge:workflow` event bus.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import * as React from "react";

import { Wizard } from "../../src/components/Wizard/Wizard";
import type { WizardStepType } from "../../src/components/Wizard/Wizard.schema";

const steps: WizardStepType[] = [
  {
    id: "s1",
    title: "Basics",
    fields: [
      { name: "name", label: "Name", kind: "text", required: true },
    ],
  },
  {
    id: "s2",
    title: "Contact",
    fields: [
      { name: "email", label: "Email", kind: "email" },
    ],
  },
];

describe("Wizard", () => {
  afterEach(() => cleanup());

  it("renders the first step and disables Next when required is empty", () => {
    const { getByLabelText, getByRole, getByText } = render(
      <Wizard steps={steps} onComplete="createFoo" />,
    );
    getByLabelText(/name/i);
    const next = getByRole("button", { name: /next/i });
    expect((next as HTMLButtonElement).disabled).toBe(true);
    // Fill required
    fireEvent.change(getByLabelText(/name/i), { target: { value: "Ada" } });
    expect((next as HTMLButtonElement).disabled).toBe(false);
    getByText("Basics");
  });

  it("advances through steps and reaches a Review pane", () => {
    const { getByLabelText, getByRole, container } = render(
      <Wizard steps={steps} onComplete="createFoo" />,
    );
    fireEvent.change(getByLabelText(/name/i), { target: { value: "Ada" } });
    fireEvent.click(getByRole("button", { name: /next/i }));
    // Step 2
    fireEvent.change(getByLabelText(/email/i), { target: { value: "a@b.co" } });
    fireEvent.click(getByRole("button", { name: /next/i }));
    // Review
    expect(container.querySelector("[data-forge-wizard-review]")).not.toBeNull();
  });

  it("dispatches forge:workflow with accumulated values on submit", () => {
    const spy = vi.fn();
    const handler = (e: Event) => spy((e as CustomEvent).detail);
    window.addEventListener("forge:workflow", handler);
    const { getByLabelText, getByRole } = render(
      <Wizard steps={steps} onComplete="createFoo" skipReview />,
    );
    fireEvent.change(getByLabelText(/name/i), { target: { value: "Ada" } });
    fireEvent.click(getByRole("button", { name: /next/i }));
    fireEvent.change(getByLabelText(/email/i), { target: { value: "a@b.co" } });
    fireEvent.click(getByRole("button", { name: /submit/i }));
    expect(spy).toHaveBeenCalled();
    expect(spy.mock.calls[0][0]).toMatchObject({
      workflow: "createFoo",
      input: { name: "Ada", email: "a@b.co" },
    });
    window.removeEventListener("forge:workflow", handler);
  });
});
