"use client";
import * as React from "react";
import { ChevronDown } from "lucide-react";
import { useEditorStore } from "@/lib/editor-store";

const sectionLabelCls =
  "block px-3 py-2 text-[10px] font-semibold tracking-wider text-muted-foreground uppercase";

// Token-style dropdown — visually matches the reference's chrome
function DropdownField({
  value,
  onChange,
  options,
  placeholder,
}: {
  value?: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  placeholder?: string;
}) {
  return (
    <div className="relative mx-3 mb-2">
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none bg-background border rounded-md pl-3 pr-8 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-foreground/30"
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown
        size={14}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
      />
    </div>
  );
}

// Freeform size input (Width/Height/Min/Max). Values are RAW CSS strings
// ("240px", "50%", "auto", "32rem") written to node.style — the renderer emits
// them verbatim. Commits on blur / Enter (not per-keystroke) so a size edit is a
// single undo step, and an empty value clears the key.
function SizeField({
  label,
  value,
  onCommit,
  placeholder,
}: {
  label: string;
  value?: string;
  onCommit: (v: string) => void;
  placeholder?: string;
}) {
  const [local, setLocal] = React.useState(value ?? "");
  React.useEffect(() => {
    setLocal(value ?? "");
  }, [value]);
  const commit = () => {
    const next = local.trim();
    if (next !== (value ?? "")) onCommit(next);
  };
  return (
    <div>
      <label className="block text-[10px] tracking-wide text-muted-foreground uppercase mb-1">
        {label}
      </label>
      <input
        type="text"
        value={local}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
        placeholder={placeholder}
        className="w-full bg-background border rounded-md px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-foreground/30"
      />
    </div>
  );
}

// Option values are TOKEN REFS (e.g. "spacing.4") that applyStyleSlot compiles
// to var(--token-spacing-4) — the CSS vars the canvas injects via compileTokens.
const BACKGROUND_OPTIONS = [
  { value: "", label: "(none)" },
  { value: "color.primary.500", label: "Primary · 500" },
  { value: "color.primary.100", label: "Primary · 100" },
  { value: "color.primary.50", label: "Primary · 50" },
  { value: "color.secondary.500", label: "Secondary · 500" },
  { value: "color.accent.500", label: "Accent · 500" },
];

const SPACING_OPTIONS = [
  { value: "", label: "—" },
  { value: "spacing.2", label: "xs" },
  { value: "spacing.3", label: "sm" },
  { value: "spacing.4", label: "md" },
  { value: "spacing.6", label: "lg" },
  { value: "spacing.8", label: "xl" },
];

const RADIUS_OPTIONS = [
  { value: "", label: "—" },
  { value: "radius.sm", label: "sm" },
  { value: "radius.md", label: "md" },
  { value: "radius.lg", label: "lg" },
  { value: "radius.full", label: "full" },
];

const SHADOW_OPTIONS = [
  { value: "", label: "—" },
  { value: "shadow.sm", label: "sm" },
  { value: "shadow.md", label: "md" },
  { value: "shadow.lg", label: "lg" },
];

// Must match the schema's Motion enum (packages/schema style-slot.ts):
// z.enum(["none","fade-in","fade-up","stagger","slide-in"]). The old
// fast/base/slow values failed StyleSlot validation and got rejected.
const MOTION_OPTIONS = [
  { value: "", label: "(none)" },
  { value: "fade-in", label: "fade in" },
  { value: "fade-up", label: "fade up" },
  { value: "stagger", label: "stagger" },
  { value: "slide-in", label: "slide in" },
];

const DENSITY_OPTIONS = [
  { value: "compact", label: "compact" },
  { value: "comfortable", label: "comfortable" },
  { value: "cozy", label: "cozy" },
];

const ELEVATION_OPTIONS = [
  { value: "flat", label: "flat" },
  { value: "bordered", label: "bordered" },
  { value: "layered", label: "layered" },
  { value: "floating", label: "floating" },
];

const RADIUS_SCALE_OPTIONS = [
  { value: "sharp", label: "sharp" },
  { value: "soft", label: "soft" },
  { value: "rounded", label: "rounded" },
  { value: "pill", label: "pill" },
];

function findNodeAndPage(
  artifacts: any,
  nodeId: string | null,
): { pageId: string; node: any } | null {
  if (!nodeId || !artifacts) return null;
  for (const [pageId, page] of Object.entries(artifacts.pageSchemas ?? {})) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if (n.id === nodeId) return { pageId, node: n };
      if (Array.isArray(n.children)) stack.push(...n.children);
      if (n.slots && typeof n.slots === "object") {
        for (const arr of Object.values(n.slots) as any[]) {
          if (Array.isArray(arr)) stack.push(...arr);
        }
      }
    }
  }
  return null;
}

// Style tab — per-node StyleSlot controls + node-independent Design System.
export function StylePanel() {
  const artifacts = useEditorStore((s) => s.artifacts);
  const selectedNodeId = useEditorStore((s) => s.selectedNodeId);
  const selectedCount = useEditorStore((s) => s.selectedNodeIds.length);
  const dispatch = useEditorStore((s) => s.dispatch);

  const hit = findNodeAndPage(artifacts, selectedNodeId);
  // Node-specific controls apply only to a single selected node. The Design
  // System block below is node-independent and always shows.
  const showNodeControls = !!hit && selectedCount <= 1;

  // Style controls write the node's top-level StyleSlot envelope (`node.style`)
  // — the field the renderer resolves via applyStyleSlot (structural nodes) and
  // the `style` prop (library nodes). Values are token refs (e.g. "spacing.4")
  // that applyStyleSlot compiles to var(--token-spacing-4). Writing node.props
  // (the old behaviour) had no effect because the renderer ignores props.style.
  const style = (hit?.node?.style ?? {}) as Record<string, string>;
  const writeStyle = (key: string, value: string) => {
    if (!hit) return;
    dispatch({
      type: "updateStyle",
      pageId: hit.pageId,
      nodeId: selectedNodeId!,
      styleKey: key,
      value: value || undefined,
    });
  };

  // Design-system tokens cascade from the tokens artifact, not per-node.
  // For v1 we just show the current values and update via updateToken when the
  // tokens artifact has a "system" group.
  const designSystem = (artifacts?.tokens as any)?.system ?? {};
  const writeSystemToken = (key: string, value: string) => {
    dispatch({ type: "updateToken", path: ["system", key], value });
  };

  return (
    <div className="py-2">
      {!showNodeControls ? (
        <p className="px-3 py-3 text-sm text-muted-foreground">
          {selectedCount > 1
            ? `${selectedCount} nodes selected — select a single node to edit its style.`
            : "Select a node to edit its style."}
        </p>
      ) : (
      <>
      <span className={sectionLabelCls}>Size</span>
      <div className="px-3 mb-2 grid grid-cols-2 gap-2">
        <SizeField
          label="Width"
          value={(style as any).width}
          onCommit={(v) => writeStyle("width", v)}
          placeholder="auto"
        />
        <SizeField
          label="Height"
          value={(style as any).height}
          onCommit={(v) => writeStyle("height", v)}
          placeholder="auto"
        />
        <SizeField
          label="Min W"
          value={(style as any).minWidth}
          onCommit={(v) => writeStyle("minWidth", v)}
          placeholder="—"
        />
        <SizeField
          label="Max W"
          value={(style as any).maxWidth}
          onCommit={(v) => writeStyle("maxWidth", v)}
          placeholder="—"
        />
        <SizeField
          label="Min H"
          value={(style as any).minHeight}
          onCommit={(v) => writeStyle("minHeight", v)}
          placeholder="—"
        />
        <SizeField
          label="Max H"
          value={(style as any).maxHeight}
          onCommit={(v) => writeStyle("maxHeight", v)}
          placeholder="—"
        />
      </div>
      <p className="px-3 -mt-1 mb-2 text-[10px] text-muted-foreground">
        Any CSS unit — px, %, rem, auto
      </p>

      <span className={sectionLabelCls}>Background</span>
      <DropdownField
        value={(style as any).background}
        onChange={(v) => writeStyle("background", v)}
        options={BACKGROUND_OPTIONS}
      />

      <span className={sectionLabelCls}>Padding</span>
      <DropdownField
        value={(style as any).padding}
        onChange={(v) => writeStyle("padding", v)}
        options={SPACING_OPTIONS}
      />

      <span className={sectionLabelCls}>Radius</span>
      <DropdownField
        value={(style as any).radius}
        onChange={(v) => writeStyle("radius", v)}
        options={RADIUS_OPTIONS}
      />

      <span className={sectionLabelCls}>Shadow</span>
      <DropdownField
        value={(style as any).shadow}
        onChange={(v) => writeStyle("shadow", v)}
        options={SHADOW_OPTIONS}
      />

      <span className={sectionLabelCls}>Motion</span>
      <DropdownField
        value={(style as any).motion}
        onChange={(v) => writeStyle("motion", v)}
        options={MOTION_OPTIONS}
      />
      </>
      )}

      <div className="h-px bg-border mx-3 my-3" />

      <div className="px-3 mb-2">
        <h4 className="text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
          Design System
        </h4>
        <p className="text-[10px] text-muted-foreground mt-0.5">
          System-wide · cascades from root node
        </p>
      </div>

      <div className="text-[10px] tracking-wide text-muted-foreground uppercase px-3 mb-1">
        Density
      </div>
      <DropdownField
        value={designSystem.density ?? "comfortable"}
        onChange={(v) => writeSystemToken("density", v)}
        options={DENSITY_OPTIONS}
      />

      <div className="text-[10px] tracking-wide text-muted-foreground uppercase px-3 mb-1">
        Elevation
      </div>
      <DropdownField
        value={designSystem.elevation ?? "layered"}
        onChange={(v) => writeSystemToken("elevation", v)}
        options={ELEVATION_OPTIONS}
      />

      <div className="text-[10px] tracking-wide text-muted-foreground uppercase px-3 mb-1">
        Radius scale
      </div>
      <DropdownField
        value={designSystem.radiusScale ?? "soft"}
        onChange={(v) => writeSystemToken("radiusScale", v)}
        options={RADIUS_SCALE_OPTIONS}
      />
    </div>
  );
}
