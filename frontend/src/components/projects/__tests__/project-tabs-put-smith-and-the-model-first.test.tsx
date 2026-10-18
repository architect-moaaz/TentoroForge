/**
 * The project page's tabs: Smith, Data Model, Editor, Workflows and Agents
 * across the top; Files, Versions, Preview and Settings behind "More", first.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

import { MORE_TABS, PRIMARY_TABS, TabRow, type Tab } from "../ProjectTabs";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const picked: Tab[] = [];

beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); picked.length = 0; });
afterEach(() => { act(() => root.unmount()); host.remove(); });

const render = (active: Tab = "chat") => act(() => {
  root.render(<TabRow tabs={PRIMARY_TABS} more={MORE_TABS} active={active} onPick={(t) => picked.push(t)} allowed={() => true} />);
});
const labels = () => [...host.querySelectorAll(":scope > div > button")].map((b) => b.textContent?.trim());

describe("project tabs", () => {
  it("shows Smith and the four model views across the top, and the tools behind More", () => {
    render();
    expect(labels()).toEqual(["Smith", "Data Model", "Editor", "Workflows", "Agents", "More"]);
    expect(MORE_TABS.slice(0, 4).map((t) => t.label)).toEqual(["Files", "Versions", "Preview", "Settings"]);
    expect(host.textContent).not.toContain("Chat");
  });

  it("opens More and picks a tab from it", () => {
    render();
    const more = [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === "More")!;
    act(() => { more.click(); });
    const preview = [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Preview")!;
    act(() => { preview.click(); });
    expect(picked).toEqual(["preview"]);
  });

  it("names the open tab from More in place of the word More", () => {
    render("versions");
    expect([...host.querySelectorAll("button")].some((b) => b.textContent?.trim() === "Versions")).toBe(true);
    expect([...host.querySelectorAll("button")].some((b) => b.textContent?.trim() === "More")).toBe(false);
  });
});
