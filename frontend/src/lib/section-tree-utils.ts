import type { SectionNode } from "@/types/visual-editor";

/**
 * Semantic HTML tags that should always be treated as section roots.
 */
const SEMANTIC_TAGS = new Set([
  "header",
  "nav",
  "main",
  "section",
  "article",
  "aside",
  "footer",
]);

interface RawBridgeNode {
  tagName: string;
  className?: string;
  textContent?: string;
  id?: string;
  xpath: string;
  source?: {
    file: string;
    line: number;
    component: string | null;
  } | null;
  children?: RawBridgeNode[];
  depth?: number;
}

/**
 * Determine if a bridge DOM node should be treated as a section root
 * in the outline panel.
 */
function isSectionRoot(node: RawBridgeNode, depth: number): boolean {
  // Always show semantic tags
  if (SEMANTIC_TAGS.has(node.tagName.toLowerCase())) return true;
  // Elements with source annotations are significant
  if (node.source) return true;
  // Top-level div children of body
  if (depth <= 1 && node.tagName.toLowerCase() === "div") return true;
  return false;
}

/**
 * Transform the raw bridge DOM tree into a cleaned SectionNode tree.
 * Filters to meaningful section roots and their children.
 */
export function transformBridgeTree(rawTree: RawBridgeNode): SectionNode[] {
  if (!rawTree || !rawTree.children) return [];

  function buildNode(raw: RawBridgeNode, depth: number): SectionNode | null {
    const children: SectionNode[] = [];

    if (raw.children) {
      for (const child of raw.children) {
        if (isSectionRoot(child, depth + 1)) {
          const node = buildNode(child, depth + 1);
          if (node) children.push(node);
        } else if (child.children) {
          // Recurse into non-section children to find nested sections
          for (const grandchild of child.children) {
            if (isSectionRoot(grandchild, depth + 2)) {
              const node = buildNode(grandchild, depth + 2);
              if (node) children.push(node);
            }
          }
        }
      }
    }

    // Get text preview — truncate to 30 chars
    let textPreview: string | null = null;
    if (raw.textContent) {
      const trimmed = raw.textContent.trim();
      if (trimmed.length > 0) {
        textPreview = trimmed.length > 30 ? trimmed.slice(0, 30) + "..." : trimmed;
      }
    }

    return {
      id: raw.xpath,
      tagName: raw.tagName.toLowerCase(),
      className: raw.className || "",
      textPreview,
      source: raw.source || null,
      children: children.length > 0 ? children : null,
      depth,
    };
  }

  // rawTree is typically the <body> or <html> element
  // Process its children as potential section roots
  const sections: SectionNode[] = [];
  const rootChildren = rawTree.children || [];

  for (const child of rootChildren) {
    if (isSectionRoot(child, 0)) {
      const node = buildNode(child, 0);
      if (node) sections.push(node);
    } else if (child.children) {
      // Look one level deeper for section roots
      for (const grandchild of child.children) {
        if (isSectionRoot(grandchild, 0)) {
          const node = buildNode(grandchild, 0);
          if (node) sections.push(node);
        }
      }
    }
  }

  return sections;
}

/**
 * Find a section node by its xpath (id).
 */
export function findSectionByXPath(
  tree: SectionNode[],
  xpath: string,
): SectionNode | null {
  for (const node of tree) {
    if (node.id === xpath) return node;
    if (node.children) {
      const found = findSectionByXPath(node.children, xpath);
      if (found) return found;
    }
  }
  return null;
}
