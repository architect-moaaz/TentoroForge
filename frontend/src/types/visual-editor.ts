/** Bridge protocol types — shared between bridge.js and the React host. */

export interface ElementInfo {
  tagName: string;
  className: string;
  textContent: string;
  id: string | null;
  rect: { top: number; left: number; width: number; height: number };
  source: { file: string; line: number; component: string | null } | null;
  xpath: string;
}

export type DeviceSize = "desktop" | "tablet" | "mobile";

export type QuickStyleCategory = "color" | "spacing" | "typography" | "border" | "layout";

export interface SectionNode {
  id: string;           // xpath as unique identifier
  tagName: string;
  className: string;
  textPreview: string | null;
  source: { file: string; line: number; component: string | null } | null;
  children: SectionNode[] | null;
  depth: number;
}
