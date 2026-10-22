"use client";
/** What is picked in the phone editor, and which screen it is on: written by the picture and the panels, read by all of them. */
import { create } from "zustand";

import type { Source } from "./phoneParts";
import type { PalettePart } from "./types";

/** What is picked, and which screen it is on: written by the picture, read by every panel. */
export interface Pick {
  /** The part picked in the picture. */
  source: Source | null;
  pageId: string | null;
  /** A part picked in Layers instead: it wins over the picture's. */
  listed: Source | null;
  /** A ready part being dragged in from the Add list. */
  dragging: PalettePart | null;
  /** The part just added: its words box takes the cursor, so what it says can be typed over at once. */
  fresh: string | null;
  set: (patch: Partial<Pick>) => void;
}

export const usePhonePick = create<Pick>((set) => ({ source: null, pageId: null, listed: null, dragging: null, fresh: null, set: (patch) => set(patch) }));

/** The type the Add list drags under: the picture's bridge answers to this one kind of drag and no other. */
export const PART_DRAG_TYPE = "application/x-forge-part";

