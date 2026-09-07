// The canonical metadata shape for every component in Tentoro Forge.

export type ControlType =
  | "text" | "textarea" | "number" | "select" | "toggle"
  | "color" | "spacing" | "binding" | "actionPicker" | "iconPicker"
  // Raw-JSON escape hatch for props whose value is a structured object the
  // pickers cannot express — today the four AppShell composition slots, which
  // take a schema sub-tree. They were wired to "actionPicker", whose only
  // output is an action object; rendering that in a React child position threw
  // "Objects are not valid as a React child" and blanked the entire page (see
  // docs/editor-audit/containment.md finding #1). A prop the panel can only
  // fill with a crashing value needs an editor that can express the real one.
  | "json"
  // "image" gets the drop-target / upload control instead of a URL text box.
  // Declared here rather than sniffed from the prop's NAME in the editor: a
  // name list ("photoUrl", "avatarUrl", …) silently misses every image prop a
  // future component adds, and the registry is already the one place that
  // says what a prop means.
  | "image";

/**
 * How an image-valued prop stores its URL. Only meaningful when
 * `control: "image"`, and required there, because the three shapes are not
 * interchangeable — see packages/schema/src/nodes/foundation.ts.
 *
 *   "url"     — the prop IS the url string        (Avatar.photoUrl)
 *   "overlay" — { url, overlay }                  (Hero.backgroundImage)
 *   "media"   — { kind, src, alt }                (Hero.media)
 */
export type ImageShape = "url" | "overlay" | "media";

export interface PropDescriptor {
  // "array" is a first-class prop type, not a stringly-typed stand-in.
  // `Select.options` and `RadioGroup.options` are `z.array(...).min(1)` in the
  // schema; Select shipped as a `textarea` storing a comma-separated string, so
  // every dropped Select was invalid and rendered zero options, and RadioGroup
  // had no control at all. Both are edited through the `json` control.
  //
  // "object" is the same story one shape over. `MetricTile.delta`
  // (`{ value, direction }`), `Form.defaultValues`, `EditableLineGrid.totals`
  // and the CTA wrappers (`EmptyState.action`, `FeatureCard.cta`, …) are
  // structured records, and every one of them was declared `type: "action"`
  // with an `actionPicker` control — a control whose only output is
  // `{ action: "navigate" | "workflow", … }`, which carries none of the keys
  // those schemas want. The prop was then blanked by validateProps' step-3
  // coercion, so the control could only ever destroy what it was pointed at.
  // Saying "object" lets them be typed honestly and edited through `json`.
  type: "string" | "number" | "boolean" | "enum" | "action" | "object" | "binding" | "array";
  default?: unknown;
  options?: readonly string[];          // for enum
  control: ControlType;
  imageShape?: ImageShape;              // for control: "image"
  group: "content" | "style" | "state" | "behavior" | "data";
  description?: string;
}

export type SlotRule =
  | { type: "leaf" }
  | { type: "single"; accepts?: readonly string[] }
  | { type: "list"; accepts?: readonly string[]; rejects?: readonly string[]; maxChildren?: number };

export interface RegistryEntry {
  name: string;
  category: "layout" | "input" | "display" | "navigation" | "feedback" | "data";
  icon?: string;
  description?: string;
  /**
   * Structural components the editor creates on the user's behalf and that must
   * never appear in the drag-from palette (GridCell is the first). They are
   * still full registry entries: validateForCommit's registry-type closure
   * rejects a page containing an unknown type, so "hide it from the palette" and
   * "leave it out of the registry" are not the same thing.
   */
  hidden?: boolean;
  slots: SlotRule;
  props: Record<string, PropDescriptor>;
}

export type Registry = Record<string, RegistryEntry>;
