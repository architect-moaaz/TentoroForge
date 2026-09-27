/**
 * Two reviews before a build.
 *
 * The requirements come first, grouped by what the product does, with what
 * the last change moved marked on the rows it moved. Then the product model,
 * module by module, with a tick on each module: the whole app is one button,
 * the ticked modules another. After a partial build the modules left out are
 * still there, each with its own Build.
 */
// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ProductModelReview,
  RequirementsReview,
  WaitingModules,
  gateCardLine,
  type GatesPayload,
} from "@/components/smith/GateReview";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DOC = { application: { name: "KidsCare" } };

const GATES: GatesPayload = {
  gate: "requirements",
  built: false,
  requirements: {
    version: 2,
    approval: "open",
    items: [
      { id: "REQ-001", description: "A parent books a visit.", area: "Booking",
        criteria: ["a free slot is chosen"], assumption: "" },
      { id: "REQ-002", description: "A parent cancels up to 12 hours before.", area: "Booking",
        criteria: [], assumption: "" },
      { id: "REQ-014", description: "An SMS reminder the day before.", area: "Notifications",
        criteria: [], assumption: "provider not named" },
    ],
    diff: {
      added: ["REQ-014"],
      removed: [{ id: "REQ-008", description: "A parent pays online.", area: "Payments",
                  criteria: [], assumption: "" }],
      changed: [{ id: "REQ-002", was: "A parent cancels up to 24 hours before." }],
    },
  },
  product_model: {
    version: 1,
    approval: "open",
    diff: null,
    items: {
      modules: [
        { id: "MODULE-001", name: "Appointments", description: "Booking visits.", deferred: false,
          pages: [{ id: "PAGE-001", name: "Book a visit", route: "/book", purpose: "Pick a slot" }],
          entities: [{ id: "ENTITY-001", name: "Appointment", description: "", fields: ["slot"] }],
          workflows: [], requirements: ["REQ-001"] },
        { id: "MODULE-002", name: "Clinic admin", description: "Doctors and hours.", deferred: false,
          pages: [{ id: "PAGE-003", name: "Doctors", route: "/admin/doctors", purpose: "" }],
          entities: [], workflows: [], requirements: [] },
      ],
      foundation: { roles: [{ id: "ROLE-001", name: "Parent", description: "" }],
                    auth: [{ id: "PAGE-005", name: "Sign in", route: "/login" }],
                    pages: [], entities: [], workflows: [] },
      integrations: [{ id: "INT-001", name: "Email", kind: "email", provider: "", connected: true }],
      uncovered: [],
      counts: { modules: 2, pages: 3, entities: 1, workflows: 0, integrations: 1, roles: 1 },
    },
  },
};

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const render = (node: React.ReactNode) => act(() => root.render(node));
const button = (label: string) =>
  [...host.querySelectorAll("button")].find((b) => b.textContent?.includes(label)) as HTMLButtonElement;

describe("the requirements review", () => {
  it("groups by area and marks what the last change moved", () => {
    const onApprove = vi.fn();
    render(<RequirementsReview doc={DOC} data={GATES.requirements} onApprove={onApprove} onEdit={() => {}} />);
    const text = host.textContent ?? "";
    expect(text).toContain("Booking");
    expect(text).toContain("Notifications");
    expect(text).toContain("Since v1:");
    expect(text).toContain("+1 added");
    expect(text).toContain("−1 removed");
    expect(text).toContain("A parent cancels up to 24 hours before."); // what it was
    expect(text).toContain("A parent pays online.");                  // shown struck, in its area
    expect(text).toContain("3 requirements in 2 areas · 1 assumed");
    act(() => button("Approve requirements").click());
    expect(onApprove).toHaveBeenCalledOnce();
  });
});

describe("the product model review", () => {
  it("builds the whole app, or only the modules left ticked", () => {
    const onBuild = vi.fn();
    render(<ProductModelReview doc={DOC} gates={{ ...GATES, gate: "product_model" }}
                               onBuild={onBuild} onEdit={() => {}} />);
    const text = host.textContent ?? "";
    expect(text).toContain("Foundation");
    expect(text).toContain("Appointments");
    expect(text).toContain("/admin/doctors");
    expect(text).toContain("Connections");
    expect(button("Build selected").disabled).toBe(true); // everything is ticked

    act(() => (host.querySelector('[aria-label="Build Clinic admin"]') as HTMLButtonElement).click());
    expect(host.textContent).toContain("Only their screens wait");
    expect(button("Build selected (1)").disabled).toBe(false);
    act(() => button("Build selected (1)").click());
    expect(onBuild).toHaveBeenLastCalledWith(["MODULE-001"]);

    act(() => button("Build app").click());
    expect(onBuild).toHaveBeenLastCalledWith(null);
  });
});

describe("after a partial build", () => {
  it("offers each module that waits, on top of what is built", () => {
    const onBuild = vi.fn();
    const built: GatesPayload = {
      ...GATES, gate: null, built: true,
      product_model: { ...GATES.product_model, items: { ...GATES.product_model.items,
        modules: GATES.product_model.items.modules.map((m) =>
          m.id === "MODULE-002" ? { ...m, deferred: true } : m) } },
    };
    render(<WaitingModules gates={built} onBuild={onBuild} />);
    expect(host.textContent).toContain("Clinic admin");
    act(() => button("Build").click());
    expect(onBuild).toHaveBeenCalledWith(["MODULE-001", "MODULE-002"]);
  });
});

describe("the transcript card", () => {
  it("names the review that is open", () => {
    expect(gateCardLine(GATES)?.label).toBe("Requirements · v2");
    expect(gateCardLine({ ...GATES, gate: "product_model" })?.line).toBe("2 modules · 3 screens · 1 record");
    expect(gateCardLine({ ...GATES, gate: null })).toBeNull();
  });
});
