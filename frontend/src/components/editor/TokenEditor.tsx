"use client";
import { useEditorStore } from "@/lib/editor-store";

const labelCls = "text-xs uppercase tracking-wide text-muted-foreground";

export function TokenEditor() {
  const tokens = useEditorStore(s => s.artifacts?.tokens);
  const dispatch = useEditorStore(s => s.dispatch);

  if (!tokens) {
    return <div className="p-4 text-sm text-muted-foreground">No tokens loaded.</div>;
  }

  return (
    <div className="p-3 space-y-4">
      {/* Color tokens */}
      <ColorSection
        title="Color"
        category={tokens.color ?? {}}
        onUpdate={(path, value) => dispatch({ type: "updateToken", path, value })}
        onRemove={(path) => dispatch({ type: "removeToken", path })}
      />

      {/* Spacing tokens — flat key/value */}
      <FlatSection
        title="Spacing"
        category={tokens.spacing ?? {}}
        path={["spacing"]}
        onUpdate={(path, value) => dispatch({ type: "updateToken", path, value: Number(value) })}
        valueType="number"
      />

      {/* Radius */}
      <FlatSection
        title="Radius"
        category={tokens.radius ?? {}}
        path={["radius"]}
        onUpdate={(path, value) => dispatch({ type: "updateToken", path, value: Number(value) })}
        valueType="number"
      />

      {/* Typography — fontFamily (nested) + scale (flat) */}
      <TypographySection
        tokens={tokens.typography ?? {}}
        onUpdate={(path, value) => dispatch({ type: "updateToken", path, value })}
      />

      {/* Shadow + motion — simple flat key/value strings */}
      <FlatSection
        title="Shadow"
        category={tokens.shadow ?? {}}
        path={["shadow"]}
        onUpdate={(path, value) => dispatch({ type: "updateToken", path, value })}
        valueType="text"
      />
      <FlatSection
        title="Motion"
        category={tokens.motion ?? {}}
        path={["motion"]}
        onUpdate={(path, value) => dispatch({ type: "updateToken", path, value })}
        valueType="text"
      />
    </div>
  );
}

// ----- Sub-components -----

interface ColorSectionProps {
  title: string;
  category: Record<string, Record<string, string>>;
  onUpdate: (path: string[], value: string) => void;
  onRemove: (path: string[]) => void;
}

function ColorSection({ title, category, onUpdate, onRemove }: ColorSectionProps) {
  return (
    <fieldset className="space-y-2">
      <legend className={labelCls}>{title}</legend>
      {Object.entries(category).map(([group, swatches]) => (
        <div key={group} className="space-y-1">
          <div className="text-xs font-medium">{group}</div>
          {Object.entries(swatches).map(([name, hex]) => (
            <div key={name} className="flex gap-2 items-center">
              <input
                type="color"
                value={typeof hex === "string" && hex.startsWith("#") ? hex : "#000000"}
                onChange={(e) => onUpdate(["color", group, name], e.target.value)}
                className="h-6 w-12 border rounded cursor-pointer"
              />
              <span className="text-xs flex-1 truncate" title={hex as string}>
                {name}: {String(hex)}
              </span>
              <button
                onClick={() => onRemove(["color", group, name])}
                className="text-xs text-muted-foreground hover:text-destructive"
                title="Remove token"
                aria-label={`Remove ${group}.${name}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      ))}
    </fieldset>
  );
}

interface FlatSectionProps {
  title: string;
  category: Record<string, string | number>;
  path: string[];
  onUpdate: (path: string[], value: string | number) => void;
  valueType: "text" | "number";
}

function FlatSection({ title, category, path, onUpdate, valueType }: FlatSectionProps) {
  return (
    <fieldset className="space-y-2">
      <legend className={labelCls}>{title}</legend>
      {Object.entries(category).map(([name, value]) => (
        <label key={name} className="flex gap-2 items-center text-xs">
          <span className="w-12 truncate">{name}</span>
          <input
            type={valueType}
            value={value as any}
            onChange={(e) => onUpdate([...path, name], e.target.value)}
            className="flex-1 border rounded px-2 py-0.5 bg-background"
          />
        </label>
      ))}
    </fieldset>
  );
}

interface TypographySectionProps {
  tokens: Record<string, any>;
  onUpdate: (path: string[], value: any) => void;
}

function TypographySection({ tokens, onUpdate }: TypographySectionProps) {
  return (
    <fieldset className="space-y-2">
      <legend className={labelCls}>Typography</legend>
      {/* fontFamily */}
      <div className="space-y-1">
        <div className="text-xs font-medium">Font family</div>
        {Object.entries(tokens.fontFamily ?? {}).map(([name, value]) => (
          <label key={name} className="flex gap-2 items-center text-xs">
            <span className="w-16 truncate">{name}</span>
            <input
              type="text"
              value={value as string}
              onChange={(e) => onUpdate(["typography", "fontFamily", name], e.target.value)}
              className="flex-1 border rounded px-2 py-0.5 bg-background font-mono text-[10px]"
            />
          </label>
        ))}
      </div>
      {/* scale */}
      <div className="space-y-1">
        <div className="text-xs font-medium">Scale (px)</div>
        {Object.entries(tokens.scale ?? {}).map(([name, value]) => (
          <label key={name} className="flex gap-2 items-center text-xs">
            <span className="w-12 truncate">{name}</span>
            <input
              type="number"
              value={value as number}
              onChange={(e) => onUpdate(["typography", "scale", name], Number(e.target.value))}
              className="flex-1 border rounded px-2 py-0.5 bg-background"
            />
          </label>
        ))}
      </div>
    </fieldset>
  );
}
