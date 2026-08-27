/**
 * Tests for the portal Zustand store.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { usePortalStore } from "@/stores/portal";

describe("usePortalStore", () => {
  beforeEach(() => {
    usePortalStore.getState().reset();
  });

  it("starts with empty state", () => {
    const state = usePortalStore.getState();
    expect(state.apps).toEqual([]);
    expect(state.tasks).toEqual([]);
    expect(state.activity).toEqual([]);
    expect(state.isLoading).toBe(false);
    expect(state.commandPaletteOpen).toBe(false);
    expect(state.onboarding.dismissed).toBe(false);
  });

  it("setApps replaces apps", () => {
    const apps = [{ id: "a1", name: "App1" }] as any[];
    usePortalStore.getState().setApps(apps);
    expect(usePortalStore.getState().apps).toHaveLength(1);
  });

  it("setTasks replaces tasks", () => {
    const tasks = [{ id: "t1", title: "Fix bug" }] as any[];
    usePortalStore.getState().setTasks(tasks);
    expect(usePortalStore.getState().tasks).toHaveLength(1);
  });

  it("setActivity replaces activity", () => {
    const activity = [{ id: "act1", type: "commit" }] as any[];
    usePortalStore.getState().setActivity(activity);
    expect(usePortalStore.getState().activity).toHaveLength(1);
  });

  it("setLoading toggles loading state", () => {
    usePortalStore.getState().setLoading(true);
    expect(usePortalStore.getState().isLoading).toBe(true);
    usePortalStore.getState().setLoading(false);
    expect(usePortalStore.getState().isLoading).toBe(false);
  });

  it("setCommandPaletteOpen toggles palette", () => {
    usePortalStore.getState().setCommandPaletteOpen(true);
    expect(usePortalStore.getState().commandPaletteOpen).toBe(true);
  });

  it("setCommandItems sets items", () => {
    const items = [
      { id: "cmd1", label: "Go to Chat", category: "navigation" as const, action: () => {} },
    ];
    usePortalStore.getState().setCommandItems(items);
    expect(usePortalStore.getState().commandItems).toHaveLength(1);
  });

  it("setOnboardingStep updates current step", () => {
    usePortalStore.getState().setOnboardingStep("add_people");
    expect(usePortalStore.getState().onboarding.currentStep).toBe("add_people");
  });

  it("completeOnboardingStep adds to completed without duplicates", () => {
    usePortalStore.getState().completeOnboardingStep("create_org");
    usePortalStore.getState().completeOnboardingStep("create_org");
    usePortalStore.getState().completeOnboardingStep("add_people");
    const completed = usePortalStore.getState().onboarding.completedSteps;
    expect(completed).toHaveLength(2);
    expect(completed).toContain("create_org");
    expect(completed).toContain("add_people");
  });

  it("dismissOnboarding sets dismissed flag", () => {
    usePortalStore.getState().dismissOnboarding();
    expect(usePortalStore.getState().onboarding.dismissed).toBe(true);
  });

  it("reset restores all defaults", () => {
    usePortalStore.getState().setApps([{ id: "a1" }] as any[]);
    usePortalStore.getState().setCommandPaletteOpen(true);
    usePortalStore.getState().dismissOnboarding();
    usePortalStore.getState().reset();
    const state = usePortalStore.getState();
    expect(state.apps).toEqual([]);
    expect(state.commandPaletteOpen).toBe(false);
    expect(state.onboarding.dismissed).toBe(false);
  });
});
