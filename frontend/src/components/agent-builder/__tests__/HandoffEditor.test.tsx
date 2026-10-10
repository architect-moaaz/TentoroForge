/**
 * HandoffEditor — the human-handoff box as a form.
 *
 * Who handles handoffs (the app's own roles and people), how one is assigned, what the assistant asks first and who
 * is told. Email is optional: turning it on explains that nothing breaks without it. jsdom + manual createRoot + act().
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const apiGet = vi.fn(async (_url: string): Promise<unknown> => ({ roles: [], people: [], peopleNote: null }));
vi.mock("@/lib/api", () => ({ api: { get: (url: string) => apiGet(url), post: vi.fn(), put: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }));

import { HandoffEditor, DEFAULT_HANDOFF_QUESTIONS } from "../config/HandoffEditor";
import type { HumanHandoffConfig } from "@/types/agent-builder";

const OPTIONS = {
  roles: ["Manager", "Support Agent"],
  people: [
    { id: "u1", name: "Maya Brandt", role: "Manager" },
    { id: "u2", name: "Idris Okafor", role: "Support Agent" },
  ],
  peopleNote: null,
};

let container: HTMLDivElement;
let root: Root;
const update = vi.fn();

beforeEach(() => {
  apiGet.mockReset();
  apiGet.mockResolvedValue(OPTIONS);
  update.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const wait = (ms = 20) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

async function mount(config: HumanHandoffConfig = {}, projectId: string | undefined = "p1") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={qc}>
        <HandoffEditor config={config} onUpdate={update} projectId={projectId} />
      </QueryClientProvider>,
    );
  });
  await wait();
}

const byLabel = (label: string) => container.querySelector(`[aria-label="${label}"]`) as HTMLElement;
const checkbox = (text: string) =>
  [...container.querySelectorAll("label")].find((l) => (l.textContent ?? "").trim().startsWith(text))!.querySelector("input")! as HTMLInputElement;
const text = () => container.textContent ?? "";

async function click(el: Element) {
  await act(async () => {
    (el as HTMLElement).click();
  });
}

async function type(el: Element, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function choose(el: Element, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

describe("HandoffEditor", () => {
  it("offers the app's own roles and people, asked for from this project", async () => {
    await mount();
    expect(apiGet).toHaveBeenCalledWith("/api/projects/p1/agent-definitions/handoff-options");
    expect(text()).toContain("Manager");
    expect(text()).toContain("Support Agent");
    expect(text()).toContain("Maya Brandt");
    expect(text()).toContain("(Support Agent)");
  });

  it("ticking a role names it as a handler and leaves the rest alone", async () => {
    await mount({ handlers: { roles: ["Manager"], people: [{ id: "u9", name: "Pat" }] } });
    await click(checkbox("Support Agent"));
    expect(update).toHaveBeenLastCalledWith({ handlers: { roles: ["Manager", "Support Agent"], people: [{ id: "u9", name: "Pat" }] } });
    update.mockReset();
    await click(checkbox("Manager"));
    expect(update).toHaveBeenLastCalledWith({ handlers: { roles: [], people: [{ id: "u9", name: "Pat" }] } });
  });

  it("a role the app does not have is shown, so it can be seen and unticked", async () => {
    await mount({ handlers: { roles: ["Janitor"] } });
    expect(text()).toContain("Janitor");
    expect(text()).toContain("this app has no such role");
  });

  it("people can be named, by id, with their name kept for display", async () => {
    await mount();
    await click(checkbox("Idris Okafor"));
    expect(update).toHaveBeenLastCalledWith({ handlers: { roles: [], people: [{ id: "u2", name: "Idris Okafor" }] } });
  });

  it("with no roles to offer, roles are typed in, comma-separated", async () => {
    apiGet.mockResolvedValue({ roles: [], people: [], peopleNote: "The app is not built yet, so its people could not be listed." });
    await mount();
    expect(text()).toContain("not built yet");
    const input = container.querySelector('input[placeholder="Manager, Support Agent"]')!;
    await type(input, "Manager,  Clerk ,");
    expect(update).toHaveBeenLastCalledWith({ handlers: { roles: ["Manager", "Clerk"], people: [] } });
  });

  it("without a project it still works: roles are typed", async () => {
    await mount({}, "");
    expect(apiGet).not.toHaveBeenCalled();
    expect(container.querySelector('input[placeholder="Manager, Support Agent"]')).toBeTruthy();
  });

  it("naming nobody says nobody will be notified, and naming someone clears it", async () => {
    await mount();
    expect(container.querySelector('[role="note"]')?.textContent).toContain("nobody will be notified");
    await mount({ handlers: { roles: ["Manager"] } });
    expect(container.querySelector('[role="note"]')).toBeNull();
  });

  it("the assignment is chosen from three, each explained, and a named owner is picked from the people", async () => {
    await mount();
    expect(text()).toContain("Everyone who handles handoffs sees it");
    await choose(byLabel("Assignment"), "round_robin");
    expect(update).toHaveBeenLastCalledWith({ assignment: "round_robin" });

    await mount({ assignment: "owner" });
    expect(text()).toContain("Always goes to one named person");
    await choose(byLabel("Owner"), "u1");
    expect(update).toHaveBeenLastCalledWith({ owner_id: "u1" });
  });

  it("the questions start as the usual three and can be edited, removed and added up to five", async () => {
    await mount();
    expect((byLabel("Question 1") as HTMLInputElement).value).toBe(DEFAULT_HANDOFF_QUESTIONS[0]);
    await type(byLabel("Question 2"), "Which order is it about?");
    expect(update).toHaveBeenLastCalledWith({ questions: [DEFAULT_HANDOFF_QUESTIONS[0], "Which order is it about?", DEFAULT_HANDOFF_QUESTIONS[2]] });
    await click(byLabel("Remove question 1"));
    expect(update).toHaveBeenLastCalledWith({ questions: [DEFAULT_HANDOFF_QUESTIONS[1], DEFAULT_HANDOFF_QUESTIONS[2]] });
    await click([...container.querySelectorAll("button")].find((b) => /Add a question/.test(b.textContent ?? ""))!);
    expect(update).toHaveBeenLastCalledWith({ questions: [...DEFAULT_HANDOFF_QUESTIONS, ""] });

    await mount({ questions: ["a?", "b?", "c?", "d?", "e?"] });
    expect([...container.querySelectorAll("button")].some((b) => /Add a question/.test(b.textContent ?? ""))).toBe(false);
  });

  it("the bell is on unless switched off, and email is an extra that explains itself", async () => {
    await mount();
    expect(byLabel("Notify in the app").getAttribute("aria-checked")).toBe("true");
    expect(byLabel("Also send email").getAttribute("aria-checked")).toBe("false");
    expect(byLabel("Only urgent ones")).toBeNull();
    expect(text()).toContain("Email is optional");
    expect(text()).toContain("nothing breaks");
    await click(byLabel("Also send email"));
    expect(update).toHaveBeenLastCalledWith({ notify: { email: true } });

    await mount({ notify: { email: true } });
    expect(byLabel("Only urgent ones").getAttribute("aria-checked")).toBe("true");
    await click(byLabel("Only urgent ones"));
    expect(update).toHaveBeenLastCalledWith({ notify: { email: true, email_urgent_only: false } });
  });

  it("the words that mean 'a person please' are edited as a list", async () => {
    await mount();
    await type(container.querySelector('input[placeholder="human, real person, speak to someone"]')!, "human, person ,");
    expect(update).toHaveBeenLastCalledWith({ conditions: { keyword_triggers: ["human", "person"] } });
  });

  it("an agent saved before the form existed still opens", async () => {
    await mount({ target: { type: "email", value: "support@example.com" }, context_fields: ["topic"], conditions: { sentiment_threshold: 0.3 } });
    expect(container.querySelector('[data-testid="handoff-editor"]')).toBeTruthy();
  });
});
