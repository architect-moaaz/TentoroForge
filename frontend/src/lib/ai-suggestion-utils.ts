import type { ElementInfo } from "@/types/visual-editor";

const SECTION_SUGGESTIONS = [
  "Add more content",
  "Change background",
  "Improve layout",
  "Add animation",
];

const BUTTON_SUGGESTIONS = [
  "Change color",
  "Make larger",
  "Add icon",
  "Add hover effect",
];

const HEADING_SUGGESTIONS = [
  "Change font size",
  "Change color",
  "Center text",
  "Make bold",
];

const IMAGE_SUGGESTIONS = [
  "Make rounded",
  "Add border",
  "Change size",
  "Add shadow",
];

const LINK_SUGGESTIONS = [
  "Change color",
  "Add underline",
  "Make bolder",
  "Add hover effect",
];

const INPUT_SUGGESTIONS = [
  "Add placeholder",
  "Change border",
  "Make larger",
  "Add focus ring",
];

const DEFAULT_SUGGESTIONS = [
  "Change style",
  "Edit content",
  "Add padding",
  "Change color",
];

const NO_SELECTION_SUGGESTIONS = [
  "Add a hero section",
  "Improve spacing",
  "Make responsive",
  "Add dark mode",
];

const TAG_MAP: Record<string, string[]> = {
  button: BUTTON_SUGGESTIONS,
  a: LINK_SUGGESTIONS,
  h1: HEADING_SUGGESTIONS,
  h2: HEADING_SUGGESTIONS,
  h3: HEADING_SUGGESTIONS,
  h4: HEADING_SUGGESTIONS,
  h5: HEADING_SUGGESTIONS,
  h6: HEADING_SUGGESTIONS,
  img: IMAGE_SUGGESTIONS,
  input: INPUT_SUGGESTIONS,
  textarea: INPUT_SUGGESTIONS,
  select: INPUT_SUGGESTIONS,
  section: SECTION_SUGGESTIONS,
  header: SECTION_SUGGESTIONS,
  footer: SECTION_SUGGESTIONS,
  main: SECTION_SUGGESTIONS,
  nav: SECTION_SUGGESTIONS,
  article: SECTION_SUGGESTIONS,
  aside: SECTION_SUGGESTIONS,
};

/**
 * Get context-aware AI suggestion chips based on the selected element.
 */
export function getSuggestions(
  element: ElementInfo | null,
  sectionId: string | null,
): string[] {
  if (!element && !sectionId) return NO_SELECTION_SUGGESTIONS;
  if (!element) return SECTION_SUGGESTIONS;

  const tag = element.tagName.toLowerCase();
  return TAG_MAP[tag] || DEFAULT_SUGGESTIONS;
}
