/**
 * Watch live when TentoroForge is on a server: the builder's own computer is connected through a reverse SSH tunnel.
 *
 * What is pinned: with a tunnel service the address box gives way to "Your computer"; Connect is held back until the computer is
 * connected, and then connects through the tunnel (not through an address); a code and the command to run are shown, with the
 * port the builder's app uses and a countdown; the screen follows the tunnel by itself (a connector starting, a network dropping);
 * a failing check never wipes what is on screen; the setup box goes away once the computer is connected; and a platform with no
 * tunnel (it runs on the builder's computer) still shows the address box exactly as before.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiDelete = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get: (u: string) => apiGet(u), post: (u: string, b: unknown) => apiPost(u, b), put: vi.fn(), delete: (u: string) => apiDelete(u) }, ApiError: class extends Error {} }));

import { AgentWatchPanel } from "../AgentWatchPanel";
import { initialWatch } from "@/lib/agent-watch";

const URL_TUNNEL = "/api/projects/p1/agent-definitions/debug/tunnel";
const OPTIONS = { roles: [], people: [], peopleNote: null };
let tunnel: Record<string, unknown>;
let container: HTMLDivElement;
let root: Root;
const connect = vi.fn();

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date"] });
  window.localStorage.clear();
  [apiGet, apiPost, apiDelete, connect].forEach((f) => f.mockReset());
  tunnel = { enabled: true, registered: false, connected: false };
  apiGet.mockImplementation(async (u: string) => (u === URL_TUNNEL ? tunnel : OPTIONS));
  apiPost.mockResolvedValue({ code: "ABCD-EFGH", expiresAt: Math.floor(Date.now() / 1000) + 600 });
  apiDelete.mockResolvedValue({ removed: true });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
// The connection is a popup behind the Connection button; most tests are about it, so it is opened (popup = false leaves it shut).
async function mount(link: "idle" | "connected" = "idle", popup = true) {
  await act(async () => {
    root.render(
      <AgentWatchPanel state={initialWatch()} link={link} reason={null} suggestedUrl={null} projectId="p1" onConnect={connect} onDisconnect={vi.fn()} onSelect={vi.fn()} onFollow={vi.fn()} />,
    );
  });
  await flush();
  if (popup && !document.body.querySelector('[data-testid="watch-dialog"]')) {
    await act(async () => { (document.body.querySelector('[data-testid="watch-open-connection"]') as HTMLElement).click(); await vi.advanceTimersByTimeAsync(0); });
  }
}
const q = (id: string) => document.body.querySelector(`[data-testid="${id}"]`);
const text = () => document.body.textContent ?? "";
const button = (label: string) => [...document.body.querySelectorAll("button")].find((b) => (b.textContent ?? "").trim() === label) as HTMLButtonElement | undefined;
const click = (e: Element) => act(async () => { (e as HTMLElement).click(); await vi.advanceTimersByTimeAsync(0); });
const type = (el: Element, value: string) =>
  act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); });

describe("Watch live behind a tunnel", () => {
  it("shows Your computer instead of an address box, and holds Connect back until the computer is connected", async () => {
    await mount();
    expect(q("watch-tunnel")).not.toBeNull();
    expect(document.body.querySelector('[aria-label="App address"]'), "no address to type: the server cannot see this computer's localhost").toBeNull();
    expect(q("tunnel-state")?.textContent).toBe("No computer connected yet.");
    expect(button("Connect")!.disabled).toBe(true);
    expect(button("Connect")!.title).toContain("Connect your computer first");
    expect(button("Connect your computer")).toBeDefined();
  });

  it("asks for a code, shows it with the command for each system, the port, and a countdown", async () => {
    await mount();
    await click(button("Connect your computer")!);
    expect(apiPost).toHaveBeenCalledWith(`${URL_TUNNEL}/pair`, {});
    const setup = q("tunnel-setup")!;
    expect(setup.textContent).toContain("Code ABCD-EFGH: works once, for 10:00 more.");
    expect(q("command-unix")!.textContent).toBe(`curl -fsSL ${window.location.origin}/api/tunnel/connector.mjs -o ttf-watch-connect.mjs && node ttf-watch-connect.mjs --server ${window.location.origin} --code ABCD-EFGH --app 3000`);
    expect(q("command-windows")!.textContent).toContain("Invoke-WebRequest");
    expect(q("command-windows")!.textContent).toContain("--code ABCD-EFGH --app 3000");
    expect(button("New code")).toBeDefined();
    await tick(61_000);
    expect(q("tunnel-code-clock")!.textContent).toContain("works once, for 8:59 more.");
  });

  it("puts the builder's own port into the command, remembers it, and refuses a port that is not one", async () => {
    await mount();
    await click(button("Connect your computer")!);
    const port = document.body.querySelector('[aria-label="App port"]')!;
    await type(port, "3001");
    expect(q("command-unix")!.textContent).toContain("--app 3001");
    expect(window.localStorage.getItem("forge.watch.appPort.p1")).toBe("3001");
    await type(port, "abc");
    expect(q("command-unix"), "no command for a port that is not a port").toBeNull();
    expect(text()).toContain("That is not a port");
    expect(window.localStorage.getItem("forge.watch.appPort.p1")).toBe("3001");
  });

  it("says when the code has run out and offers a new one", async () => {
    apiPost.mockResolvedValue({ code: "ABCD-EFGH", expiresAt: Math.floor(Date.now() / 1000) + 3 });
    await mount();
    await click(button("Connect your computer")!);
    await tick(5000);
    expect(q("tunnel-code-clock")!.textContent).toBe("Code ABCD-EFGH: expired. Press New code.");
    apiPost.mockResolvedValue({ code: "WXYZ-2345", expiresAt: Math.floor(Date.now() / 1000) + 600 });
    await click(button("New code")!);
    expect(q("tunnel-code-clock")!.textContent).toContain("Code WXYZ-2345");
  });

  it("follows the tunnel by itself: a connector starting enables Connect and closes the setup box", async () => {
    await mount();
    await click(button("Connect your computer")!);
    expect(q("tunnel-setup")).not.toBeNull();
    tunnel = { enabled: true, registered: true, connected: true, appPort: 3001, clientIp: "1.2.3.4", label: "Ana laptop" };
    await tick(5200);
    expect(q("tunnel-state")!.textContent).toBe("Connected: Ana laptop (1.2.3.4), app on port 3001.");
    expect(q("tunnel-state")!.getAttribute("data-tone")).toBe("good");
    expect(q("tunnel-setup"), "the setup box has done its job").toBeNull();
    expect(button("Connect")!.disabled).toBe(false);
    expect(button("Connect again")).toBeDefined();
  });

  it("keeps the connection in a popup, so the panel is for the chats", async () => {
    await mount("idle", false);
    expect(q("watch-dialog"), "nothing is in the way of the chats until it is asked for").toBeNull();
    expect(q("watch-tunnel")).toBeNull();
    expect(q("watch-chats")).not.toBeNull();
    expect(q("watch-summary")!.textContent).toBe("No computer connected yet.");
    await click(q("watch-open-connection")!);
    expect(q("watch-dialog")).not.toBeNull();
    expect(q("watch-dialog")!.querySelector('[data-testid="watch-tunnel"]'), "Your computer is inside the popup").not.toBeNull();
    expect(q("watch-top")!.querySelector('[data-testid="watch-tunnel"]'), "and not in the bar above the chats").toBeNull();
    expect(q("watch-top")!.className).not.toContain("overflow");
  });

  it("closes the popup by itself once the watch is connected, and a second code opened while connected can be hidden", async () => {
    tunnel = { enabled: true, registered: true, connected: true, appPort: 3001, clientIp: "1.2.3.4", label: "Ana laptop" };
    await mount("idle");
    expect(q("watch-dialog")).not.toBeNull();
    await mount("connected", false);
    expect(q("watch-dialog"), "connected: the popup has done its job").toBeNull();
    expect(q("watch-link")!.textContent).toContain("Connected");
    await click(q("watch-open-connection")!);
    expect(q("tunnel-setup")).toBeNull();
    await click(button("Connect again")!);
    expect(q("tunnel-setup"), "Connect again shows the code even though a computer is connected").not.toBeNull();
    await click(q("tunnel-setup-hide")!);
    expect(q("tunnel-setup"), "Hide puts it away").toBeNull();
    expect(q("tunnel-state")!.textContent).toContain("Connected");
  });

  it("connects through the tunnel, never through an address, and remembers whom to watch", async () => {
    tunnel = { enabled: true, registered: true, connected: true, appPort: 3001, clientIp: "1.2.3.4" };
    await mount();
    await click(button("Connect")!);
    expect(connect).toHaveBeenCalledWith("tunnel", {});
    expect(window.localStorage.getItem("forge.liveRun.app.p1"), "no address is kept: there is none").toBeNull();
  });

  it("notices a network drop and says to run the connector again, then notices it come back", async () => {
    tunnel = { enabled: true, registered: true, connected: true, appPort: 3001, clientIp: "1.2.3.4" };
    await mount();
    expect(q("tunnel-state")!.getAttribute("data-tone")).toBe("good");
    tunnel = { ...tunnel, connected: false };
    await tick(5200);
    expect(q("tunnel-state")!.getAttribute("data-tone")).toBe("warn");
    expect(q("tunnel-state")!.textContent).toContain("is paired but not connected right now");
    expect(button("Connect")!.disabled).toBe(true);
    tunnel = { ...tunnel, connected: true };
    await tick(5200);
    expect(q("tunnel-state")!.getAttribute("data-tone")).toBe("good");
  });

  it("keeps what it knew when a check fails, says so, and recovers by itself", async () => {
    tunnel = { enabled: true, registered: true, connected: true, appPort: 3001, clientIp: "1.2.3.4" };
    await mount();
    apiGet.mockImplementation(async (u: string) => { if (u === URL_TUNNEL) throw new Error("Network error"); return OPTIONS; });
    await tick(5200);
    expect(q("tunnel-state")!.textContent, "the last known state stays").toContain("Connected");
    expect(q("tunnel-problem")!.textContent).toBe("Network error");
    apiGet.mockImplementation(async (u: string) => (u === URL_TUNNEL ? tunnel : OPTIONS));
    await tick(5200);
    expect(q("tunnel-problem")).toBeNull();
  });

  it("says why a code could not be made, and forgets a computer when asked", async () => {
    tunnel = { enabled: true, registered: true, connected: false, label: "Ana laptop", clientIp: "1.2.3.4" };
    apiPost.mockRejectedValue(new Error("This platform has no tunnel service."));
    await mount();
    await click(button("Connect again")!);
    expect(q("tunnel-problem")!.textContent).toBe("This platform has no tunnel service.");
    tunnel = { enabled: true, registered: false, connected: false };
    await click(q("tunnel-forget")!);
    expect(apiDelete).toHaveBeenCalledWith(URL_TUNNEL);
    expect(q("tunnel-state")!.textContent).toBe("No computer connected yet.");
  });

  it("mentions a Vercel deployment without offering to watch it", async () => {
    tunnel = { enabled: true, registered: false, connected: false, hosted: { vercel: { url: "https://my-app.vercel.app" } } };
    await mount();
    expect(q("tunnel-vercel")!.textContent).toContain("also hosted on Vercel (https://my-app.vercel.app)");
    expect(q("tunnel-vercel")!.textContent).toContain("not available yet");
    tunnel = { enabled: true, registered: true, connected: true, hosted: { vercel: { url: "https://my-app.vercel.app" } } };
    await tick(5200);
    expect(q("tunnel-vercel"), "once a computer is connected there is nothing to explain").toBeNull();
  });

  it("is quiet and the address box stays exactly as it was when the platform has no tunnel", async () => {
    tunnel = { enabled: false, registered: false, connected: false };
    await mount();
    expect(q("watch-tunnel")).toBeNull();
    expect(document.body.querySelector('[aria-label="App address"]')).not.toBeNull();
    expect(button("Connect")!.disabled).toBe(false);
    await click(button("Connect")!);
    expect(connect).toHaveBeenCalledWith("http://localhost:3000", {});
  });

  it("copies the command and says so", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true });
    await mount();
    await click(button("Connect your computer")!);
    await click(q("copy-unix")!);
    expect(write).toHaveBeenCalledWith(q("command-unix")!.textContent);
    expect(q("copy-unix")!.textContent).toBe("Copied");
    await tick(2100);
    expect(q("copy-unix")!.textContent).toBe("Copy");
  });
});
