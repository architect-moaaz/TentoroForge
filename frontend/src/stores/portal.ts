import { create } from "zustand";
import type {
  PortalApp,
  PortalTask,
  PortalActivity,
  PortalStats,
  SuggestedApp,
  OnboardingStep,
  OnboardingState,
  CommandItem,
} from "@/types/portal";

interface PortalState {
  // Portal data
  apps: PortalApp[];
  tasks: PortalTask[];
  activity: PortalActivity[];
  stats: PortalStats | null;
  suggestions: SuggestedApp[];
  isLoading: boolean;

  // Search / filters
  searchQuery: string;
  taskFilter: { appId?: string; status?: string };
  activityFilter: { appId?: string };

  // Command palette
  commandPaletteOpen: boolean;
  commandItems: CommandItem[];

  // Onboarding
  onboarding: OnboardingState;

  // Actions — data
  setApps: (apps: PortalApp[]) => void;
  setTasks: (tasks: PortalTask[]) => void;
  setActivity: (activity: PortalActivity[]) => void;
  setStats: (stats: PortalStats) => void;
  setSuggestions: (suggestions: SuggestedApp[]) => void;
  setLoading: (loading: boolean) => void;

  // Actions — search / filters
  setSearchQuery: (query: string) => void;
  setTaskFilter: (filter: { appId?: string; status?: string }) => void;
  setActivityFilter: (filter: { appId?: string }) => void;

  // Actions — command palette
  setCommandPaletteOpen: (open: boolean) => void;
  setCommandItems: (items: CommandItem[]) => void;

  // Actions — onboarding
  setOnboardingStep: (step: OnboardingStep) => void;
  completeOnboardingStep: (step: OnboardingStep) => void;
  dismissOnboarding: () => void;

  reset: () => void;
}

const defaultOnboarding: OnboardingState = {
  currentStep: "welcome",
  completedSteps: [],
  dismissed: false,
};

export const usePortalStore = create<PortalState>((set) => ({
  apps: [],
  tasks: [],
  activity: [],
  stats: null,
  suggestions: [],
  isLoading: false,

  searchQuery: "",
  taskFilter: {},
  activityFilter: {},

  commandPaletteOpen: false,
  commandItems: [],

  onboarding: defaultOnboarding,

  setApps: (apps) => set({ apps }),
  setTasks: (tasks) => set({ tasks }),
  setActivity: (activity) => set({ activity }),
  setStats: (stats) => set({ stats }),
  setSuggestions: (suggestions) => set({ suggestions }),
  setLoading: (loading) => set({ isLoading: loading }),

  setSearchQuery: (query) => set({ searchQuery: query }),
  setTaskFilter: (filter) => set({ taskFilter: filter }),
  setActivityFilter: (filter) => set({ activityFilter: filter }),

  setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
  setCommandItems: (items) => set({ commandItems: items }),

  setOnboardingStep: (step) =>
    set((state) => ({
      onboarding: { ...state.onboarding, currentStep: step },
    })),
  completeOnboardingStep: (step) =>
    set((state) => ({
      onboarding: {
        ...state.onboarding,
        completedSteps: [...new Set([...state.onboarding.completedSteps, step])],
      },
    })),
  dismissOnboarding: () =>
    set((state) => ({
      onboarding: { ...state.onboarding, dismissed: true },
    })),

  reset: () =>
    set({
      apps: [],
      tasks: [],
      activity: [],
      stats: null,
      suggestions: [],
      isLoading: false,
      searchQuery: "",
      taskFilter: {},
      activityFilter: {},
      commandPaletteOpen: false,
      commandItems: [],
      onboarding: defaultOnboarding,
    }),
}));
