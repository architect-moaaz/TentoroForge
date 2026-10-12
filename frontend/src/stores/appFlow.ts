import { create } from "zustand";

/**
 * "Show me this path": Smith's side panel asks for the App Flow tab, on one
 * flow, and the project page opens it.
 */
interface AppFlowState {
  /** The flow the tab should open on, or null for the whole map. */
  focus: string | null;
  /** Bumped on every request, so the same flow asked for twice still opens. */
  requested: number;
  open: (flowId: string | null) => void;
}

export const useAppFlowStore = create<AppFlowState>((set) => ({
  focus: null,
  requested: 0,
  open: (flowId) => set((s) => ({ focus: flowId, requested: s.requested + 1 })),
}));
