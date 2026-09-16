import { describe, it, expect, vi } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { Form, parseTags } from "../src/components/Form/Form";

/**
 * A `string[]` column is collected by a `tags` field: the record's array
 * pre-fills it as chips, the typed text is parsed on every keystroke without
 * eating the separator, and the form submits the ARRAY — what a jsonb column
 * holds — never the JSON text the edit form used to show in a textarea.
 */
describe("a tags field over a string[] column", () => {
  const fields = [
    { kind: "text" as const, name: "name", label: "Name" },
    { kind: "tags" as const, name: "specialities", label: "Specialities" },
  ];

  it("pre-fills from the record's array and submits an array", async () => {
    const dispatch = vi.fn();
    const { container, getByLabelText, getByText } = render(
      <Form workflow="FLOW-002" fields={fields} submitLabel="Save Changes"
            defaultValues={{ name: "Amara Okonkwo", specialities: ["Pediatrics", "Neonatal Care"] }}
            __dispatch={dispatch} />,
    );
    const input = getByLabelText("Specialities") as HTMLInputElement;
    expect(input.value).toBe("Pediatrics, Neonatal Care");
    expect(container.querySelectorAll("[data-tags-preview] span")).toHaveLength(2);

    fireEvent.change(input, { target: { value: "Pediatrics, Neonatal Care, " } });
    expect(input.value).toBe("Pediatrics, Neonatal Care, ");          // the separator survives
    fireEvent.change(input, { target: { value: "Pediatrics, Neonatal Care, ICU" } });
    expect(container.querySelectorAll("[data-tags-preview] span")).toHaveLength(3);

    fireEvent.click(getByText("Save Changes"));
    await waitFor(() => expect(dispatch).toHaveBeenCalled());
    expect(dispatch.mock.calls[0][1]).toMatchObject({
      name: "Amara Okonkwo",
      specialities: ["Pediatrics", "Neonatal Care", "ICU"],
    });
  });

  it("pre-fills from the JSON text a text column held, and never shows it raw", () => {
    const { getByLabelText } = render(
      <Form workflow="FLOW-002" fields={fields}
            defaultValues={{ name: "x", specialities: '["Pediatrics","Neonatal Care"]' }} />,
    );
    expect((getByLabelText("Specialities") as HTMLInputElement).value).toBe("Pediatrics, Neonatal Care");
  });

  it("parses what a person types", () => {
    expect(parseTags("a, b ,, c\nd")).toEqual(["a", "b", "c", "d"]);
    expect(parseTags(["a", " b "])).toEqual(["a", "b"]);
    expect(parseTags(null)).toEqual([]);
  });
});
