/**
 * Content node emitters: Text, Icon, Image, Avatar, Badge, Tag, Button, StatCard, EmptyState, Skeleton
 */

import type {
  TextNode, IconNode, ImageNode, AvatarNode, BadgeNode, TagNode,
  ButtonNode, StatCardNode, EmptyStateNode, SkeletonNode,
} from "@tentoroforge/ir";
import { buildClasses, resolveTypography, textColorClass, iconSizeClass, avatarSizeClass, radiusClass } from "@tentoroforge/ir";
import { EmitContext } from "../context.js";
import { emitBinding, emitJSXContent } from "../bindings.js";
import { emitActionHandler } from "../actions.js";

// ---------------------------------------------------------------------------

function kebabToPascal(s: string): string {
  return s.split("-").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join("");
}

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------

export function emitText(node: TextNode, ctx: EmitContext): string {
  const typo = resolveTypography(node.typography || "body");
  const classes = buildClasses([
    typo.classes,
    node.weight && `font-${node.weight}`,
    node.color && textColorClass(node.color),
    node.align && `text-${node.align}`,
    node.truncate && node.truncate > 0 ? (node.truncate === 1 ? "truncate" : `line-clamp-${node.truncate}`) : false,
    node.monospace && "font-mono",
  ]);

  const content = emitJSXContent(node.content, ctx);
  const tag = typo.element;
  return `<${tag} className="${classes}">${content}</${tag}>`;
}

// ---------------------------------------------------------------------------
// Icon
// ---------------------------------------------------------------------------

export function emitIcon(node: IconNode, ctx: EmitContext): string {
  const componentName = kebabToPascal(node.name);
  ctx.ensureImport("lucide-react", componentName);

  const classes = buildClasses([
    iconSizeClass(node.size || "md"),
    node.color && textColorClass(node.color),
  ]);

  return `<${componentName} className="${classes}" />`;
}

// ---------------------------------------------------------------------------
// Image
// ---------------------------------------------------------------------------

export function emitImage(node: ImageNode, ctx: EmitContext): string {
  const src = emitBinding(node.src, ctx);
  const alt = node.alt || "";
  const classes = buildClasses([
    node.fit && `object-${node.fit}`,
    node.radius && radiusClass(node.radius),
    node.width && `w-[${node.width}]`,
    node.height && `h-[${node.height}]`,
  ]);

  const srcAttr = src.startsWith('"') ? `src=${src}` : `src={${src}}`;
  return `<img ${srcAttr} alt="${alt}" className="${classes}" />`;
}

// ---------------------------------------------------------------------------
// Avatar
// ---------------------------------------------------------------------------

export function emitAvatar(node: AvatarNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/avatar", "Avatar", "AvatarImage", "AvatarFallback");

  const sizeClass = avatarSizeClass(node.size || "md");
  const src = node.src ? emitBinding(node.src, ctx) : null;
  const name = node.name ? emitBinding(node.name, ctx) : null;

  // Generate initials helper
  const initialsExpr = name
    ? `${name.startsWith('"') ? name : name}.split(" ").map((n: string) => n[0]).join("").toUpperCase().slice(0, 2)`
    : '"?"';

  const srcTag = src
    ? `<AvatarImage src={${src.startsWith('"') ? src.slice(1, -1) : src}} />`
    : "";

  return `<Avatar className="${sizeClass}">
${srcTag}
<AvatarFallback>{${initialsExpr}}</AvatarFallback>
</Avatar>`;
}

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

export function emitBadge(node: BadgeNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/badge", "Badge");

  const content = emitJSXContent(node.content, ctx);
  const size = node.size === "sm" ? ' className="text-xs px-1.5 py-0.5"' : "";

  if (node.colorMap) {
    // Dynamic variant from colorMap
    const mapName = `variantMap_${Math.random().toString(36).slice(2, 8)}`;
    const mapEntries = Object.entries(node.colorMap)
      .map(([k, v]) => `${JSON.stringify(k)}: ${JSON.stringify(v)}`)
      .join(", ");

    ctx.addHelper(`const ${mapName}: Record<string, string> = { ${mapEntries} };`);

    const contentExpr = emitBinding(node.content, ctx);
    const variantExpr = `${mapName}[${contentExpr}] ?? "default"`;
    return `<Badge variant={${variantExpr} as any}${size}>{${contentExpr}}</Badge>`;
  }

  const variant = node.variant && node.variant !== "default" ? ` variant="${node.variant}"` : "";
  return `<Badge${variant}${size}>${content}</Badge>`;
}

// ---------------------------------------------------------------------------
// Tag
// ---------------------------------------------------------------------------

export function emitTag(node: TagNode, ctx: EmitContext): string {
  const content = emitJSXContent(node.content, ctx);
  const classes = buildClasses([
    "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors",
    node.variant === "outline" ? "border-current" : "border-transparent bg-secondary text-secondary-foreground",
  ]);

  let removeBtn = "";
  if (node.removable && node.onRemove) {
    const handler = emitActionHandler(node.onRemove, ctx);
    removeBtn = ` <button className="ml-1 rounded-full outline-none" onClick={${handler}}>×</button>`;
  }

  return `<span className="${classes}">${content}${removeBtn}</span>`;
}

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

export function emitButton(node: ButtonNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/button", "Button");

  const props: string[] = [];

  if (node.variant && node.variant !== "primary") {
    // Map IR variants to shadcn variants
    const variantMap: Record<string, string> = {
      primary: "default",
      secondary: "secondary",
      ghost: "ghost",
      outline: "outline",
      danger: "destructive",
      link: "link",
    };
    props.push(`variant="${variantMap[node.variant] || node.variant}"`);
  }

  if (node.size && node.size !== "md") {
    props.push(`size="${node.size}"`);
  }

  if (node.disabled) {
    const disabledExpr = typeof node.disabled === "boolean" ? "true" : emitBinding(node.disabled as string, ctx);
    props.push(`disabled={${disabledExpr}}`);
  }

  if (node.width === "full") {
    props.push(`className="w-full"`);
  }

  if (node.submit) {
    props.push(`type="submit"`);
  }

  if (node.action) {
    const handler = emitActionHandler(node.action, ctx);
    props.push(`onClick={${handler}}`);
  }

  const propsStr = props.length ? " " + props.join(" ") : "";

  // Icon + label
  if (node.icon) {
    const iconName = kebabToPascal(node.icon);
    ctx.ensureImport("lucide-react", iconName);
    const iconEl = `<${iconName} className="h-4 w-4" />`;

    if (node.iconPosition === "right") {
      return `<Button${propsStr}>${node.label} ${iconEl}</Button>`;
    }
    return `<Button${propsStr}>${iconEl} ${node.label}</Button>`;
  }

  return `<Button${propsStr}>${node.label}</Button>`;
}

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------

export function emitStatCard(node: StatCardNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/card", "Card", "CardContent");

  const value = emitBinding(node.value, ctx);
  const iconEl = node.icon
    ? (() => {
        const name = kebabToPascal(node.icon);
        ctx.ensureImport("lucide-react", name);
        return `<${name} className="h-5 w-5 text-muted-foreground" />`;
      })()
    : null;

  let actionProps = "";
  if (node.action) {
    const handler = emitActionHandler(node.action, ctx);
    actionProps = ` className="cursor-pointer hover:shadow-md transition-shadow" onClick={${handler}}`;
  }

  const trendEl = node.trend
    ? `<span className="text-xs text-muted-foreground">{${emitBinding(node.trend, ctx)}}</span>`
    : "";

  return `<Card${actionProps}>
<CardContent className="p-6">
<div className="flex items-center justify-between">
<span className="text-sm text-muted-foreground">${node.label}</span>
${iconEl || ""}
</div>
<div className="mt-2 text-2xl font-bold">{${value}}</div>
${trendEl}
</CardContent>
</Card>`;
}

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------

export function emitEmptyState(node: EmptyStateNode, ctx: EmitContext): string {
  const iconEl = node.icon
    ? (() => {
        const name = kebabToPascal(node.icon);
        ctx.ensureImport("lucide-react", name);
        return `<${name} className="h-10 w-10 text-muted-foreground" />`;
      })()
    : "";

  const titleEl = node.title
    ? `<h3 className="text-lg font-medium">${node.title}</h3>`
    : "";

  let actionEl = "";
  if (node.action) {
    ctx.ensureImport("@/components/ui/button", "Button");
    const handler = emitActionHandler(node.action.action, ctx);
    actionEl = `<Button onClick={${handler}}>${node.action.label}</Button>`;
  }

  return `<div className="flex flex-col items-center justify-center py-12 text-center gap-3">
${iconEl}
${titleEl}
<p className="text-sm text-muted-foreground">${node.message}</p>
${actionEl}
</div>`;
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

export function emitSkeleton(node: SkeletonNode, _ctx: EmitContext): string {
  const lines = node.lines || 3;
  const variant = node.variant || "text";

  if (variant === "text") {
    const lineEls = Array.from({ length: lines }, (_, i) => {
      const width = i === lines - 1 ? "w-3/4" : "w-full";
      return `<div className="${width} h-4 rounded bg-muted animate-pulse" />`;
    }).join("\n");
    return `<div className="space-y-2">\n${lineEls}\n</div>`;
  }

  if (variant === "card") {
    return `<div className="rounded-lg border p-4 space-y-3">
<div className="h-4 w-3/4 rounded bg-muted animate-pulse" />
<div className="h-4 w-1/2 rounded bg-muted animate-pulse" />
<div className="h-20 rounded bg-muted animate-pulse" />
</div>`;
  }

  if (variant === "avatar") {
    return `<div className="h-10 w-10 rounded-full bg-muted animate-pulse" />`;
  }

  // table
  return `<div className="space-y-2">
${Array.from({ length: lines }, () => '<div className="h-8 w-full rounded bg-muted animate-pulse" />').join("\n")}
</div>`;
}
