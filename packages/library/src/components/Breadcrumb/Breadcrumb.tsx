import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity } from "../../theme/tokens-context";
import type { BreadcrumbItem } from "./Breadcrumb.schema";

type Props = {
  items: BreadcrumbItem[];
  separator?: string;
  style?: StyleSlotT;
};

// gap-x values in rem: compact=0.25, comfortable=0.25 (today's default), spacious=0.5
const BREADCRUMB_GAP: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "0.125rem",
  comfortable: "0.25rem",
  spacious:    "0.5rem",
};

export function Breadcrumb({ items, separator = "/", style }: Props) {
  const density = useDensity();
  const gap = BREADCRUMB_GAP[density];
  return (
    <nav aria-label="Breadcrumb" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <ol style={{ display: "flex", flexWrap: "wrap", listStyle: "none", margin: 0, padding: 0, gap, alignItems: "center" }}>
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`} style={{ display: "flex", alignItems: "center", gap }}>
              {index > 0 && (
                <span aria-hidden="true" style={{ color: "#888", userSelect: "none" }}>
                  {separator}
                </span>
              )}
              {item.href && !isLast ? (
                <a href={item.href} style={{ textDecoration: "underline" }}>
                  {item.label}
                </a>
              ) : (
                <span aria-current={isLast ? "page" : undefined}>
                  {item.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
