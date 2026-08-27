/**
 * Content node → Annotated HTML emitters: Text, Icon, Image, Avatar, Badge,
 * Tag, Button, StatCard, EmptyState, Skeleton
 */

import type {
  TextNode, IconNode, ImageNode, AvatarNode, BadgeNode, TagNode,
  ButtonNode, StatCardNode, EmptyStateNode, SkeletonNode,
} from "@tentoroforge/ir";
import {
  buildClasses, resolveTypography, textColorClass,
  iconSizeClass, avatarSizeClass, radiusClass,
} from "@tentoroforge/ir";
import { indent } from "../ir-to-html.js";

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------

export function emitTextHtml(node: TextNode, depth: number): string {
  const typo = resolveTypography(node.typography || "body");
  const classes = buildClasses([
    typo.classes,
    node.weight && `font-${node.weight}`,
    node.color && textColorClass(node.color),
    node.align && `text-${node.align}`,
    node.truncate && node.truncate > 0 ? (node.truncate === 1 ? "truncate" : `line-clamp-${node.truncate}`) : false,
    node.monospace && "font-mono",
  ]);

  const tag = typo.element;
  const pad = indent(depth);
  return `${pad}<${tag} class="${classes}">${node.content}</${tag}>`;
}

// ---------------------------------------------------------------------------
// Icon
// ---------------------------------------------------------------------------

export function emitIconHtml(node: IconNode, depth: number): string {
  const classes = buildClasses([
    iconSizeClass(node.size || "md"),
    node.color && textColorClass(node.color),
  ]);

  const pad = indent(depth);
  // Use data attribute to identify the icon by name (lucide)
  return `${pad}<span class="${classes}" data-icon="${node.name}"></span>`;
}

// ---------------------------------------------------------------------------
// Image
// ---------------------------------------------------------------------------

export function emitImageHtml(node: ImageNode, depth: number): string {
  const classes = buildClasses([
    node.fit && `object-${node.fit}`,
    node.radius && radiusClass(node.radius),
    node.width && `w-[${node.width}]`,
    node.height && `h-[${node.height}]`,
  ]);

  const pad = indent(depth);
  return `${pad}<img src="${node.src}" alt="${node.alt || ""}" class="${classes}" />`;
}

// ---------------------------------------------------------------------------
// Avatar
// ---------------------------------------------------------------------------

export function emitAvatarHtml(node: AvatarNode, depth: number): string {
  const sizeClass = avatarSizeClass(node.size || "md");
  const shape = node.shape === "rounded" ? "rounded-md" : "rounded-full";
  const classes = buildClasses([sizeClass, shape, "bg-muted flex items-center justify-center overflow-hidden"]);

  const pad = indent(depth);
  if (node.src) {
    return `${pad}<div class="${classes}"><img src="${node.src}" alt="${node.name || ""}" class="h-full w-full object-cover" /></div>`;
  }
  const initials = node.name ? `{{${node.name} | initials}}` : "?";
  return `${pad}<div class="${classes}"><span class="text-xs font-medium">${initials}</span></div>`;
}

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

export function emitBadgeHtml(node: BadgeNode, depth: number): string {
  const variantClasses: Record<string, string> = {
    default: "bg-secondary text-secondary-foreground",
    primary: "bg-primary text-primary-foreground",
    success: "bg-green-100 text-green-800",
    warning: "bg-amber-100 text-amber-800",
    danger: "bg-destructive text-destructive-foreground",
    outline: "border border-current bg-transparent",
  };
  const variant = node.variant || "default";
  const classes = buildClasses([
    "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
    variantClasses[variant] || variantClasses.default,
    node.size === "sm" && "text-xs px-1.5 py-0.5",
  ]);

  const pad = indent(depth);
  if (node.colorMap) {
    return `${pad}<span class="${classes}" data-component-props='${JSON.stringify({ colorMap: node.colorMap })}'>${node.content}</span>`;
  }
  return `${pad}<span class="${classes}">${node.content}</span>`;
}

// ---------------------------------------------------------------------------
// Tag
// ---------------------------------------------------------------------------

export function emitTagHtml(node: TagNode, depth: number): string {
  const classes = buildClasses([
    "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors",
    node.variant === "outline" ? "border-current" : "border-transparent bg-secondary text-secondary-foreground",
  ]);

  const pad = indent(depth);
  const removeBtn = node.removable
    ? ` <button class="ml-1 rounded-full outline-none">×</button>`
    : "";
  return `${pad}<span class="${classes}">${node.content}${removeBtn}</span>`;
}

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

export function emitButtonHtml(node: ButtonNode, depth: number): string {
  const variantClasses: Record<string, string> = {
    primary: "bg-primary text-primary-foreground hover:bg-primary/90",
    secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
    ghost: "hover:bg-accent hover:text-accent-foreground",
    outline: "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
    danger: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
    link: "text-primary underline-offset-4 hover:underline",
  };
  const sizeClasses: Record<string, string> = {
    sm: "h-8 px-3 text-xs",
    md: "h-10 px-4 py-2",
    lg: "h-11 px-8",
  };

  const variant = node.variant || "primary";
  const size = node.size || "md";
  const classes = buildClasses([
    "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors",
    variantClasses[variant] || variantClasses.primary,
    sizeClasses[size] || sizeClasses.md,
    node.width === "full" && "w-full",
  ]);

  const attrs: string[] = [`class="${classes}"`];

  // Action annotations
  if (node.action) {
    attrs.push(`data-action="${node.action.type}"`);
    if (node.action.type === "navigate" && "to" in node.action) {
      attrs.push(`data-action-to="${node.action.to}"`);
    }
    if (node.action.type === "mutate" && "source" in node.action) {
      attrs.push(`data-action-source="${node.action.source}"`);
      if ("confirm" in node.action && node.action.confirm) {
        attrs.push(`data-action-confirm="${node.action.confirm}"`);
      }
    }
    if (node.action.type === "openModal" && "modal" in node.action) {
      attrs.push(`data-modal-trigger="${node.action.modal}"`);
    }
  }

  if (node.submit) attrs.push(`type="submit"`);
  if (node.disabled) {
    attrs.push(typeof node.disabled === "boolean" ? "disabled" : `data-visible="${node.disabled}"`);
  }

  const pad = indent(depth);
  const iconHtml = node.icon
    ? `<span data-icon="${node.icon}" class="h-4 w-4"></span> `
    : "";

  if (node.iconPosition === "right") {
    return `${pad}<button ${attrs.join(" ")}>${node.label} ${iconHtml.trim()}</button>`;
  }
  return `${pad}<button ${attrs.join(" ")}>${iconHtml}${node.label}</button>`;
}

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------

export function emitStatCardHtml(node: StatCardNode, depth: number): string {
  const pad = indent(depth);
  const attrs: string[] = [`class="rounded-lg border bg-card p-6"`, `data-component="StatCard"`];

  if (node.action) {
    attrs.push(`data-action="${node.action.type}"`);
    if (node.action.type === "navigate" && "to" in node.action) {
      attrs.push(`data-action-to="${node.action.to}"`);
    }
  }

  const iconHtml = node.icon
    ? `<span data-icon="${node.icon}" class="h-5 w-5 text-muted-foreground"></span>`
    : "";

  const trendHtml = node.trend
    ? `\n${indent(depth + 2)}<span class="text-xs text-muted-foreground">${node.trend}</span>`
    : "";

  return `${pad}<div ${attrs.join(" ")}>
${indent(depth + 1)}<div class="flex items-center justify-between">
${indent(depth + 2)}<span class="text-sm text-muted-foreground">${node.label}</span>
${indent(depth + 2)}${iconHtml}
${indent(depth + 1)}</div>
${indent(depth + 1)}<div class="mt-2 text-2xl font-bold">${node.value}</div>${trendHtml}
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------

export function emitEmptyStateHtml(node: EmptyStateNode, depth: number): string {
  const pad = indent(depth);
  const iconHtml = node.icon
    ? `\n${indent(depth + 1)}<span data-icon="${node.icon}" class="h-10 w-10 text-muted-foreground"></span>`
    : "";
  const titleHtml = node.title
    ? `\n${indent(depth + 1)}<h3 class="text-lg font-medium">${node.title}</h3>`
    : "";
  const actionHtml = node.action
    ? `\n${indent(depth + 1)}<button class="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-10 px-4 py-2 text-sm font-medium" data-action="${node.action.action.type}">${node.action.label}</button>`
    : "";

  return `${pad}<div class="flex flex-col items-center justify-center py-12 text-center gap-3" data-component="EmptyState">${iconHtml}${titleHtml}
${indent(depth + 1)}<p class="text-sm text-muted-foreground">${node.message}</p>${actionHtml}
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

export function emitSkeletonHtml(node: SkeletonNode, depth: number): string {
  const pad = indent(depth);
  const lines = node.lines || 3;
  const variant = node.variant || "text";

  if (variant === "text") {
    const lineEls = Array.from({ length: lines }, (_, i) => {
      const width = i === lines - 1 ? "w-3/4" : "w-full";
      return `${indent(depth + 1)}<div class="${width} h-4 rounded bg-muted animate-pulse"></div>`;
    }).join("\n");
    return `${pad}<div class="space-y-2">\n${lineEls}\n${pad}</div>`;
  }

  if (variant === "card") {
    return `${pad}<div class="rounded-lg border p-4 space-y-3">
${indent(depth + 1)}<div class="h-4 w-3/4 rounded bg-muted animate-pulse"></div>
${indent(depth + 1)}<div class="h-4 w-1/2 rounded bg-muted animate-pulse"></div>
${indent(depth + 1)}<div class="h-20 rounded bg-muted animate-pulse"></div>
${pad}</div>`;
  }

  if (variant === "avatar") {
    return `${pad}<div class="h-10 w-10 rounded-full bg-muted animate-pulse"></div>`;
  }

  // table
  const rows = Array.from({ length: lines }, () =>
    `${indent(depth + 1)}<div class="h-8 w-full rounded bg-muted animate-pulse"></div>`,
  ).join("\n");
  return `${pad}<div class="space-y-2">\n${rows}\n${pad}</div>`;
}
