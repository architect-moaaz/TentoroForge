import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Form } from "../src/components/Form/Form";

describe("a predicate-hidden field does not loop the form", () => {
  it("renders a form whose field is hidden by an interaction predicate", () => {
    // The new-user form hides Home Property until a property role is chosen.
    // Its conditional-state map was keyed on a fresh values object every
    // render, so the hidden field was unregistered on every render — which
    // re-rendered the form: "Maximum update depth exceeded", on this page
    // and on the guest refund form.
    const { container } = render(
      <Form workflow="FLOW-020" fields={[
        { kind: "select", name: "role", label: "Role",
          options: [{ value: "Reception", label: "Reception" }, { value: "Finance", label: "Finance" }] },
        { kind: "text", name: "homePropertyId", label: "Home property",
          interaction: { visibleIf: "role == 'Reception'" } },
      ]} />,
    );
    expect(container.querySelector('select[name="role"]')).not.toBeNull();
    expect(container.querySelector('input[name="homePropertyId"]')).toBeNull();
  });
});
