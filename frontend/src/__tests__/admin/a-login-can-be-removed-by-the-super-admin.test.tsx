/**
 * The People table offers "Remove login…" for an ordinary login, and not for
 * a super admin (the role is revoked first) or for the admin's own row.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { PeopleTable } from "@/components/admin/PeopleTable";
import type { AdminPerson } from "@/lib/admin-types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const person = (id: string, email: string, role: string | null = null): AdminPerson => ({
  id, email, name: email.split("@")[0], platform_role: role, disabled_at: null, disabled_reason: null,
  last_sign_in_at: null, orgs: [], spend_30d: 0,
} as unknown as AdminPerson);

let root: Root | undefined; let el: HTMLDivElement;
beforeEach(() => { el = document.createElement("div"); document.body.appendChild(el); });
afterEach(() => { if (root) act(() => root!.unmount()); root = undefined; el.remove(); });

async function openMenuFor(email: string) {
  const trigger = el.querySelector(`[aria-label="Actions for ${email}"]`) as HTMLButtonElement | null;
  if (!trigger) return null;
  await act(async () => {
    trigger.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0, ctrlKey: false }));
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  return Array.from(document.querySelectorAll('[role="menuitem"]')).map((n) => n.textContent ?? "");
}

describe("removing a login from the cockpit", () => {
  it("is offered for an ordinary login and hands the person to the page", async () => {
    const onRemove = vi.fn();
    const rows = [person("u1", "ann@example.com"), person("u2", "boss@tentoro.ai", "super_admin"), person("me", "admin@tentoro.ai", "super_admin")];
    root = createRoot(el);
    await act(async () => {
      root!.render(<PeopleTable rows={rows} selfId="me" onDisable={vi.fn()} onEnable={vi.fn()} onGrant={vi.fn()}
                                onRevoke={vi.fn()} onImpersonate={vi.fn()} onRemove={onRemove} />);
    });
    const ann = await openMenuFor("ann@example.com");
    expect(ann).toContain("Remove login…");
    const item = Array.from(document.querySelectorAll('[role="menuitem"]')).find((n) => n.textContent === "Remove login…") as HTMLElement;
    await act(async () => { item.click(); });
    expect(onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: "u1" }));
  });

  it("is not offered for a super admin, and the admin's own row has no menu", async () => {
    const rows = [person("u2", "boss@tentoro.ai", "super_admin"), person("me", "admin@tentoro.ai", "super_admin")];
    root = createRoot(el);
    await act(async () => {
      root!.render(<PeopleTable rows={rows} selfId="me" onDisable={vi.fn()} onEnable={vi.fn()} onGrant={vi.fn()}
                                onRevoke={vi.fn()} onImpersonate={vi.fn()} onRemove={vi.fn()} />);
    });
    expect(el.querySelector('[aria-label="Actions for admin@tentoro.ai"]')).toBeNull();
    const boss = await openMenuFor("boss@tentoro.ai");
    expect(boss).not.toContain("Remove login…");
    expect(boss).toContain("Revoke super admin");
  });
});
