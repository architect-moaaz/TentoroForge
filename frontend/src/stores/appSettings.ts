import { create } from "zustand";

/**
 * "Manage in App settings": the Publish dialog asks for the App settings tab,
 * on one section, and the project page opens it.
 */
export type AppSettingsSection = "domains";

interface AppSettingsState {
  section: AppSettingsSection;
  /** Bumped on every request, so the same section asked for twice still opens. */
  requested: number;
  open: (section: AppSettingsSection) => void;
}

export const useAppSettingsStore = create<AppSettingsState>((set) => ({
  section: "domains",
  requested: 0,
  open: (section) => set((s) => ({ section, requested: s.requested + 1 })),
}));
