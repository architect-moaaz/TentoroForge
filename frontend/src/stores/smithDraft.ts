import { create } from "zustand";

/**
 * "Ask Smith about this": a part of the editor (the phone preview) hands Smith's composer a request to finish and send.
 * The project page opens the chat; the composer shows the text and waits for the person to send it.
 */
interface SmithDraftState {
  text: string;
  /** Bumped on every request, so the same text asked twice still lands. */
  requested: number;
  ask: (text: string) => void;
}

export const useSmithDraftStore = create<SmithDraftState>((set) => ({
  text: "",
  requested: 0,
  ask: (text) => set((s) => ({ text, requested: s.requested + 1 })),
}));
