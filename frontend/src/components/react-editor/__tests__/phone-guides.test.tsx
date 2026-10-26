/**
 * The questions a guided part asks: which workflow a form saves or a button runs, which records a list shows.
 *
 * Only names are chosen and a few words typed; what goes to the server is those names, never code. A button for a workflow that
 * acts on one record is refused outside a list row, and says why in words.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GuidedDialog } from "../PhoneGuides";
import type { Place } from "../phoneParts";
import type { GuideKind, GuideRefs, GuideSpec, PhonePart } from "../types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const part = (over: Partial<PhonePart>): PhonePart => ({ id: "r0", parent: null, type: "Stack", kind: "component", line: 1, props: [], file: "view", ...over });
const nodes: Record<string, PhonePart> = {
  r0: part({ id: "r0", type: "ScreenView", children: ["r0.0", "r0.1"] }),
  "r0.0": part({ id: "r0.0", parent: "r0", type: "Stack" }),
  "r0.1": part({ id: "r0.1", parent: "r0", type: "ListView", children: [] }),
  "r0.1@renderItem.0": part({ id: "r0.1@renderItem.0", parent: "r0.1", type: "Row", slot: "renderItem", rowVar: "item" }),
};
const refs: GuideRefs = {
  workflows: [
    { id: "FLOW-001", key: "addItem", name: "Add Item", description: "Capture a new thing", inputs: [
      { name: "name", kind: "field", type: "string", required: true, description: "", entity: null, options: [] },
      { name: "count", kind: "field", type: "number", required: true, description: "", entity: null, options: [] }] },
    { id: "FLOW-002", key: "markBought", name: "Mark Bought", description: "", inputs: [
      { name: "item", kind: "record", type: "string", required: true, description: "", entity: "ShoppingItem", options: [] }] },
  ],
  entities: [{ name: "ShoppingItem", typeName: "ShoppingItem", fields: [
    { name: "id", type: "uuid", label: "Id" }, { name: "name", type: "string", label: "Name" }, { name: "quantity", type: "string", label: "Quantity" }] }],
};
const outside: Place = { op: { parentId: "r0.0" }, says: "inside the Stack" };
const inRow: Place = { op: { parentId: "r0.1@renderItem.0" }, says: "inside the Row" };

let root: Root | null = null;
let host: HTMLElement | null = null;
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null; host = null; document.body.innerHTML = ""; });

function open(kind: GuideKind, place: Place, onAdd: (s: GuideSpec) => Promise<boolean> = async () => true, given: GuideRefs = refs) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root!.render(<GuidedDialog guide={{ kind, place }} refs={given} nodes={nodes} busy={false} onClose={() => {}} onAdd={onAdd} />));
}
const dialog = () => document.body.querySelector('[data-testid="guided-dialog"]') as HTMLElement;
const addButton = () => [...dialog().querySelectorAll("button")].find((b) => b.textContent === "Add it") as HTMLButtonElement;
function type(el: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => { set.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); });
}
const otherWorkflow = () => dialog().querySelector('input[type="radio"][name="workflow"]:not(:checked)') as HTMLInputElement;

describe("a form that saves", () => {
  it("lists the application's workflows and sends only the name of the one chosen", async () => {
    const onAdd = vi.fn(async () => true);
    open("form", outside, onAdd);
    expect(dialog().textContent).toContain("Add Item");
    expect(dialog().textContent).toContain("Mark Bought");
    expect(dialog().textContent).toContain("A form with 2 fields that runs “Add Item”");
    await act(async () => { addButton().click(); });
    expect(onAdd).toHaveBeenCalledWith({ kind: "form", place: { parentId: "r0.0" }, workflow: "FLOW-001" });
  });
});

describe("a button that runs a workflow", () => {
  it("asks what to send for each input, and is not ready until they are given", async () => {
    const onAdd = vi.fn(async () => true);
    open("button", outside, onAdd);
    expect(addButton().disabled).toBe(true);
    type(dialog().querySelector("#guide-in-name") as HTMLInputElement, "Milk");
    expect(addButton().disabled).toBe(true);
    type(dialog().querySelector("#guide-in-count") as HTMLInputElement, "3");
    type(dialog().querySelector("#guide-label") as HTMLInputElement, "Add milk");
    expect(addButton().disabled).toBe(false);
    await act(async () => { addButton().click(); });
    expect(onAdd).toHaveBeenCalledWith({ kind: "button", place: { parentId: "r0.0" }, workflow: "FLOW-001", label: "Add milk", values: { name: "Milk", count: "3" } });
  });
  it("is refused for a workflow that acts on one record, outside a list row, and says why", () => {
    open("button", outside);
    act(() => { otherWorkflow().click(); });
    expect(dialog().textContent).toContain("acts on one ShoppingItem");
    expect(dialog().textContent).toContain("row of a list");
    expect(addButton().disabled).toBe(true);
  });
  it("is fine inside a list row: it acts on that row's record", async () => {
    const onAdd = vi.fn(async () => true);
    open("button", inRow, onAdd);
    act(() => { otherWorkflow().click(); });
    expect(dialog().textContent).toContain("on the row's record");
    expect(addButton().disabled).toBe(false);
    await act(async () => { addButton().click(); });
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ kind: "button", workflow: "FLOW-002", place: { parentId: "r0.1@renderItem.0" } }));
  });
});

describe("a list of records", () => {
  it("shows the first text field per row and sends the kind of record and the fields chosen", async () => {
    const onAdd = vi.fn(async () => true);
    open("list", outside, onAdd);
    expect(dialog().textContent).toContain("A list of ShoppingItem records, each row saying its name");
    const sub = dialog().querySelector("#guide-subtitle") as HTMLSelectElement;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(sub, "quantity");
      sub.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => { addButton().click(); });
    expect(onAdd).toHaveBeenCalledWith({ kind: "list", place: { parentId: "r0.0" }, entity: "ShoppingItem", title: "name", subtitle: "quantity" });
  });
  it("does not offer the record's id as something to read out", () => {
    open("list", outside);
    const options = [...(dialog().querySelector("#guide-title") as HTMLSelectElement).options].map((o) => o.value);
    expect(options).toEqual(["name", "quantity"]);
  });
});

describe("an application with nothing to connect to", () => {
  it("says so, and adds nothing", () => {
    open("form", outside, async () => true, { workflows: [], entities: [] });
    expect(dialog().textContent).toContain("no workflows yet");
    expect(addButton().disabled).toBe(true);
  });
});
