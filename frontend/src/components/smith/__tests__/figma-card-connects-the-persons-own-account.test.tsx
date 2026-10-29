/**
 * The Figma link card offers Connect Figma. Not connected: the button, and the token field as
 * the other way in. Connected: the Figma account's name, no token field, and the link is sent.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("next/navigation", () => ({ useParams: () => ({ orgId: "o1" }) }));

import { SecretCard } from "../SecretCard";

const FIELD = {
  provider: "figma", key: "FIGMA_TOKEN", label: "Figma access token", saved: "Figma design saved",
  action: "Save and read design", extra: { label: "Link to your Figma file or screens" }, connect: "figma",
} as any;
let root: Root;
let host: HTMLDivElement;

async function render(status: object, onSaved: (s: string) => void = () => {}) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith("/api/me/figma/connect")) {
      return new Response(JSON.stringify({ url: "https://www.figma.com/oauth?client_id=x" }), { status: 200 });
    }
    return new Response(JSON.stringify(status), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => { root.render(<SecretCard field={FIELD} onSaved={onSaved} />); });
  for (let i = 0; i < 5; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  return fetchMock;
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

describe("the Figma link card", () => {
  it("offers Connect Figma, with the token as the other way in", async () => {
    const fetchMock = await render({ configured: true, connected: false });
    const button = [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Connect Figma"));
    expect(button).toBeTruthy();
    expect(host.querySelector('input[type="password"]')).toBeTruthy();
    expect(host.textContent).toContain("Or paste a Figma access token instead");

    const popup = { location: { href: "" }, closed: false, close: vi.fn() };
    vi.stubGlobal("open", vi.fn(() => popup));
    await act(async () => { button!.click(); });
    for (let i = 0; i < 5; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/me/figma/connect"))!;
    expect(JSON.parse(String((call[1] as RequestInit).body))).toMatchObject({ popup: true });
    expect(popup.location.href).toBe("https://www.figma.com/oauth?client_id=x");
  });

  it("once connected, names the account and asks only for the link", async () => {
    const sent: string[] = [];
    await render({ configured: true, connected: true, account: { handle: "Ada Designer", email: "ada@studio.test" } },
                 (s) => sent.push(s));
    expect(host.textContent).toContain("Figma connected as Ada Designer");
    expect(host.querySelector('input[type="password"]')).toBeNull();

    const link = host.querySelector('input[type="url"]') as HTMLInputElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(link, "https://www.figma.com/design/Abc123/Client");
      link.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(sent).toEqual(["Figma design saved: https://www.figma.com/design/Abc123/Client"]);
  });

  it("shows nothing extra when the platform has no Figma OAuth app", async () => {
    await render({ configured: false, connected: false });
    expect(host.querySelector('[data-testid="figma-connect"]')).toBeNull();
    expect(host.querySelector('input[type="password"]')).toBeTruthy();
  });
});
