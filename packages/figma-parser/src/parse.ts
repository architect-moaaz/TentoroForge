import * as parser from "@babel/parser";
import type { ParsedResult, SchemaNode } from "./types.js";
import { tailwindToTokens } from "./tailwind-tokens.js";
import { applyCodeConnect } from "./code-connect.js";
import { createRequire } from "module";

const _require = createRequire(import.meta.url);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const traverse: (ast: any, visitors: any) => void = (() => {
  const mod = _require("@babel/traverse");
  return mod.default ?? mod;
})();

let nodeIdCounter = 0;
function genId(): string {
  return `n${++nodeIdCounter}`;
}

// Reset counter (useful for testing)
export function _resetIdCounter(): void {
  nodeIdCounter = 0;
}

const BLOCK_TAGS = new Set([
  "div", "section", "header", "footer", "main", "article", "aside", "nav",
]);

function getAttr(el: unknown, name: string): string | null {
  const element = el as {
    openingElement: { attributes?: Array<{ type: string; name: { name: string }; value?: { type: string; value: string } }> };
  };
  for (const a of element.openingElement.attributes ?? []) {
    if (
      a.type === "JSXAttribute" &&
      a.name.name === name &&
      a.value?.type === "StringLiteral"
    ) {
      return a.value.value;
    }
  }
  return null;
}

function walkJsxElement(el: unknown, unmapped: ParsedResult["unmappedNodes"]): SchemaNode {
  const element = el as {
    openingElement: { name: { name: string }; attributes: unknown[] };
    children?: unknown[];
  };
  const tag = element.openingElement.name.name as string;
  const id = genId();

  // Parse className for style tokens
  const className = getAttr(el, "className");
  let style: Record<string, string> | undefined;
  if (className) {
    const tokenResult = tailwindToTokens(className);
    if (Object.keys(tokenResult.style).length > 0) {
      style = tokenResult.style;
    }
    if (tokenResult.unmapped.length > 0) {
      unmapped.push({
        id,
        reason: `unmapped tailwind classes: ${tokenResult.unmapped.join(", ")}`,
        jsx: `<${tag} className="${className}" />`,
      });
    }
  }

  const children: SchemaNode[] = (element.children ?? [])
    .map((c: unknown) => {
      const child = c as { type: string; value?: string };
      if (child.type === "JSXElement") return walkJsxElement(c, unmapped);
      if (child.type === "JSXText" && child.value && child.value.trim()) {
        return {
          id: genId(),
          type: "Text",
          props: { content: child.value.trim() },
        } as SchemaNode;
      }
      return null;
    })
    .filter((c): c is SchemaNode => c !== null);

  if (tag === "img") {
    const src = getAttr(el, "src") ?? "";
    const alt = getAttr(el, "alt") ?? "";
    const node: SchemaNode = { id, type: "Image", props: { src, alt } };
    if (style) node.style = style;
    return node;
  }

  if (tag === "button") {
    const label = children.find((c) => c.type === "Text")?.props?.content ?? "";
    const node: SchemaNode = { id, type: "Button", props: { label: label as string } };
    if (style) node.style = style;
    return node;
  }

  if (BLOCK_TAGS.has(tag)) {
    const node: SchemaNode = {
      id,
      type: "Box",
      props: { as: tag },
      children,
    };
    if (style) node.style = style;
    return node;
  }

  // Fallback: unknown element → Box
  const node: SchemaNode = {
    id,
    type: "Box",
    props: { as: "div" },
    children,
  };
  if (style) node.style = style;
  return node;
}

function walkRoot(
  ast: unknown,
  unmapped: ParsedResult["unmappedNodes"]
): SchemaNode {
  let root: SchemaNode | null = null;
  traverse(ast, {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    JSXElement(path: any) {
      if (!root) {
        root = walkJsxElement(path.node, unmapped);
      }
      path.stop();
    },
  });
  return root ?? { id: genId(), type: "Box", children: [] };
}

export type CodeConnectMappings = Record<
  string,
  { libraryName: string; propsTransform: (props: Record<string, unknown>) => Record<string, unknown> }
>;

export function parseJsxToSchema(
  jsx: string,
  codeConnectMappings?: CodeConnectMappings
): ParsedResult {
  _resetIdCounter();
  if (!jsx.trim()) {
    return {
      schema: { root: { id: genId(), type: "Box", children: [] } },
      unmappedNodes: [],
    };
  }

  const ast = parser.parse(jsx, {
    sourceType: "module",
    plugins: ["jsx", "typescript"],
  });

  const unmapped: ParsedResult["unmappedNodes"] = [];
  let root = walkRoot(ast, unmapped);

  if (codeConnectMappings) {
    root = applyCodeConnect(root, codeConnectMappings);
  }

  return { schema: { root }, unmappedNodes: unmapped };
}
