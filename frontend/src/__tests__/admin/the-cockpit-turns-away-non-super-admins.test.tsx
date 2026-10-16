/**
 * The cockpit opens for the super admin and nobody else: a member is sent
 * home, and so is a super admin while they are acting as someone — the
 * cockpit is not reachable from inside an impersonation.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

import { SuperAdminGate } from "@/components/admin/SuperAdminGate";
import { useAuthStore, type User } from "@/stores/auth";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const person = (over: Partial<User>): User => ({
  id: "u1", email: "someone@example.com", name: null, orgs: [], ...over,
} as User);

let root: Root; let el: HTMLDivElement;
beforeEach(() => { replace.mockReset(); el = document.createElement("div"); document.body.appendChild(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

function mount(user: User | null) {
  useAuthStore.setState({ user });
  act(() => { root = createRoot(el); root.render(<SuperAdminGate><p>cockpit</p></SuperAdminGate>); });
}

describe("the cockpit's door", () => {
  it("turns a member away and sends them home", () => {
    mount(person({ platform_role: null }));
    expect(el.textContent).not.toContain("cockpit");
    expect(replace).toHaveBeenCalledWith("/");
  });

  it("opens for the super admin", () => {
    mount(person({ email: "admin@tentoro.ai", platform_role: "super_admin" }));
    expect(el.textContent).toContain("cockpit");
    expect(replace).not.toHaveBeenCalled();
  });

  it("stays shut while the super admin is acting as someone", () => {
    mount(person({ platform_role: null, impersonated_by: { id: "a", email: "admin@tentoro.ai" } }));
    expect(el.textContent).not.toContain("cockpit");
    expect(replace).toHaveBeenCalledWith("/");
  });

  it("shows nothing, and decides nothing, before the user has loaded", () => {
    mount(null);
    expect(el.textContent).toBe("");
    expect(replace).not.toHaveBeenCalled();
  });
});
