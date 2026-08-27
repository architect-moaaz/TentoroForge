import { create } from "zustand";
import type { DeviceSize, ElementInfo, SectionNode } from "@/types/visual-editor";

interface VisualEditorState {
  currentRoute: string | null;
  selectedElement: ElementInfo | null;
  hoveredElement: ElementInfo | null;
  devicePreview: DeviceSize;
  isEditing: boolean;
  editProgress: string | null;

  showActionPopover: boolean;
  actionPopoverPosition: { top: number; left: number } | null;
  quickStyleTarget: "bg" | "text" | "spacing" | "font" | "border" | null;

  leftPanelOpen: boolean;
  rightPanelOpen: boolean;
  sectionTree: SectionNode[];
  selectedSectionId: string | null;

  setCurrentRoute: (route: string | null) => void;
  setSelectedElement: (el: ElementInfo | null) => void;
  setHoveredElement: (el: ElementInfo | null) => void;
  setDevicePreview: (device: DeviceSize) => void;
  setIsEditing: (editing: boolean) => void;
  setEditProgress: (msg: string | null) => void;
  setShowActionPopover: (show: boolean, pos?: { top: number; left: number }) => void;
  setQuickStyleTarget: (target: "bg" | "text" | "spacing" | "font" | "border" | null) => void;
  setLeftPanelOpen: (open: boolean) => void;
  setRightPanelOpen: (open: boolean) => void;
  setSectionTree: (tree: SectionNode[]) => void;
  setSelectedSectionId: (id: string | null) => void;
  reset: () => void;
}

export const useVisualEditorStore = create<VisualEditorState>((set) => ({
  currentRoute: null,
  selectedElement: null,
  hoveredElement: null,
  devicePreview: "desktop",
  isEditing: false,
  editProgress: null,
  showActionPopover: false,
  actionPopoverPosition: null,
  quickStyleTarget: null,
  leftPanelOpen: true,
  rightPanelOpen: true,
  sectionTree: [],
  selectedSectionId: null,

  setCurrentRoute: (route) => set({ currentRoute: route }),
  setSelectedElement: (el) => set({ selectedElement: el }),
  setHoveredElement: (el) => set({ hoveredElement: el }),
  setDevicePreview: (device) => set({ devicePreview: device }),
  setIsEditing: (editing) => set({ isEditing: editing }),
  setEditProgress: (msg) => set({ editProgress: msg }),
  setShowActionPopover: (show, pos) =>
    set({
      showActionPopover: show,
      actionPopoverPosition: pos ?? null,
      quickStyleTarget: show ? null : null,
    }),
  setQuickStyleTarget: (target) => set({ quickStyleTarget: target }),
  setLeftPanelOpen: (open) => set({ leftPanelOpen: open }),
  setRightPanelOpen: (open) => set({ rightPanelOpen: open }),
  setSectionTree: (tree) => set({ sectionTree: tree }),
  setSelectedSectionId: (id) => set({ selectedSectionId: id }),
  reset: () =>
    set({
      currentRoute: null,
      selectedElement: null,
      hoveredElement: null,
      devicePreview: "desktop",
      isEditing: false,
      editProgress: null,
      showActionPopover: false,
      actionPopoverPosition: null,
      quickStyleTarget: null,
      leftPanelOpen: true,
      rightPanelOpen: true,
      sectionTree: [],
      selectedSectionId: null,
    }),
}));
