import { create } from "zustand";
import type {
  ScreenNodeSerialized,
  NavEdgeSerialized,
  NavLink,
  AppModule,
  ModuleDependencyEdge,
} from "@/types/navigation";

interface NavigationState {
  screens: ScreenNodeSerialized[];
  edges: NavEdgeSerialized[];
  sidebarLinks: NavLink[];
  topbarLinks: NavLink[];
  modules: AppModule[];
  moduleDependencies: ModuleDependencyEdge[];
  defaultScreen: string | null;
  errorScreen: string | null;
  selectedScreenId: string | null;
  selectedModuleId: string | null;
  activeSubTab: "screens" | "modules";
  isLoading: boolean;
  error: string | null;

  // Actions
  setScreens: (screens: ScreenNodeSerialized[]) => void;
  setEdges: (edges: NavEdgeSerialized[]) => void;
  setSidebarLinks: (links: NavLink[]) => void;
  setTopbarLinks: (links: NavLink[]) => void;
  setModules: (modules: AppModule[]) => void;
  setModuleDependencies: (deps: ModuleDependencyEdge[]) => void;
  setDefaultScreen: (id: string | null) => void;
  setErrorScreen: (id: string | null) => void;
  setSelectedScreenId: (id: string | null) => void;
  setSelectedModuleId: (id: string | null) => void;
  setActiveSubTab: (tab: "screens" | "modules") => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

export const useNavigationStore = create<NavigationState>((set) => ({
  screens: [],
  edges: [],
  sidebarLinks: [],
  topbarLinks: [],
  modules: [],
  moduleDependencies: [],
  defaultScreen: null,
  errorScreen: null,
  selectedScreenId: null,
  selectedModuleId: null,
  activeSubTab: "screens",
  isLoading: false,
  error: null,

  setScreens: (screens) => set({ screens }),
  setEdges: (edges) => set({ edges }),
  setSidebarLinks: (links) => set({ sidebarLinks: links }),
  setTopbarLinks: (links) => set({ topbarLinks: links }),
  setModules: (modules) => set({ modules }),
  setModuleDependencies: (deps) => set({ moduleDependencies: deps }),
  setDefaultScreen: (id) => set({ defaultScreen: id }),
  setErrorScreen: (id) => set({ errorScreen: id }),
  setSelectedScreenId: (id) => set({ selectedScreenId: id }),
  setSelectedModuleId: (id) => set({ selectedModuleId: id }),
  setActiveSubTab: (tab) => set({ activeSubTab: tab }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error, isLoading: false }),
  reset: () =>
    set({
      screens: [],
      edges: [],
      sidebarLinks: [],
      topbarLinks: [],
      modules: [],
      moduleDependencies: [],
      defaultScreen: null,
      errorScreen: null,
      selectedScreenId: null,
      selectedModuleId: null,
      activeSubTab: "screens",
      isLoading: false,
      error: null,
    }),
}));
