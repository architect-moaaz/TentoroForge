import { cloneElement, isValidElement, type ReactNode } from "react";
import { renderNode, type DispatchContext } from "../../runtime/dispatch";
import { evalExpression } from "../../runtime/bindings";

// Attach a stable React key to each renderNode() output when mapping over
// schema children into a fragment. Prefers the schema node's id; falls back
// to `<type>-<index>` so LLM-composed schemas without ids (page_composer.py)
// don't trigger React's "unique key" / "same key" warnings.
function withKey(rendered: ReactNode, child: any, i: number): ReactNode {
  const key = child?.id ?? `${child?.type ?? "node"}-${i}`;
  return isValidElement(rendered) ? cloneElement(rendered, { key }) : rendered;
}

/**
 * Conditional — renders one of a set of children based on data.
 *
 * Two supported schema shapes (both live in the wild, both must work):
 *
 *   1. LEGACY / when-else — single condition, two possible branches:
 *
 *      { type: "Conditional",
 *        props: { when: "user.role === 'admin'" },
 *        children: [ /* rendered when truthy *\/ ],
 *        else:     [ /* rendered when falsy   *\/ ] }
 *
 *   2. BRANCHES — first-match wins across N conditions (the stateful
 *      single-page pattern uses this):
 *
 *      { type: "Conditional",
 *        props: { branches: [
 *          { if: "!scan",                          node: {...} },
 *          { if: "scan.status === 'processing'",   node: {...} },
 *          { if: "scan.status === 'completed'",    node: {...} },
 *          { if: "scan",                           node: {...} }   // catch-all
 *        ] } }
 *
 *      Each branch has an `if` expression (evaluated in data-scope) and a
 *      `node` schema. The first branch whose `if` evaluates truthy is
 *      rendered; everything else is skipped. If no branch matches, the
 *      Conditional renders null. A common practice is to make the LAST
 *      branch a catch-all (e.g. `if: "true"` or `if: "scan"`) — the
 *      component does nothing special for it, so keep that discipline
 *      in schema.
 *
 * The runtime accepts `branches` either on `props.branches` (canonical,
 * matches how ARIA/other spec objects nest) OR at the top level `node.branches`
 * (LLM authors sometimes drop it there). Both resolve to the same behaviour.
 */
export function Conditional({ node, ctx }: { node: any; ctx: DispatchContext }) {
  const props = (node.props ?? {}) as Record<string, unknown>;

  // Shape 2: branches array — first-match wins.
  const branchesSrc =
    (Array.isArray(props.branches) ? props.branches : undefined) ??
    (Array.isArray(node.branches) ? node.branches : undefined);
  if (branchesSrc && branchesSrc.length > 0) {
    const scope = { ...ctx.data, user: ctx.user };
    for (const b of branchesSrc) {
      if (!b || typeof b !== "object") continue;
      const cond = (b as any).if ?? (b as any).when ?? (b as any).condition;
      // A branch without a condition is a catch-all (rendered if nothing
      // above matched). Same convention as `default:` in a switch.
      const matches = cond === undefined ? true : !!evalExpression(String(cond), scope);
      if (matches) {
        const branchNode = (b as any).node ?? (b as any).children;
        if (!branchNode) return null;
        if (Array.isArray(branchNode)) {
          return (
            <>
              {branchNode.map((c: any, i: number) =>
                withKey(renderNode({ ...c, id: c?.id ?? `__c_${i}` }, ctx), c, i),
              )}
            </>
          );
        }
        return <>{renderNode(branchNode, ctx)}</>;
      }
    }
    return null;
  }

  // Shape 1: legacy when + children/else. Distinguish "no condition
  // authored at all" (fall back to rendering children so an editor
  // preview doesn't crash) from "condition present and resolved to a
  // falsy value" (an interpolated `{{document.errorMessage}}` with a
  // null column comes back as null / "" — that's a genuine false and
  // must hide the branch, not render it unconditionally).
  const whenPresent = "when" in props || "condition" in props;
  const whenExpr = props.when ?? props.condition;
  if (!whenPresent) {
    const fallbackChildren = node.children;
    if (!fallbackChildren) return null;
    return <>{fallbackChildren.map((c: any, i: number) => withKey(renderNode(c, ctx), c, i))}</>;
  }
  // Resolve the presence-vs-value distinction and, for values that
  // reached us as strings, decide whether to run them through FEEL-lite
  // (real expression) or treat them as JS truthy (post-interpolation
  // resolved value like a URL / filename / id — FEEL-lite would choke
  // on those and wrongly return false, hiding the branch).
  let truthy: boolean;
  if (
    whenExpr == null ||
    whenExpr === "" ||
    whenExpr === "null" ||
    whenExpr === "undefined" ||
    whenExpr === false ||
    whenExpr === "false" ||
    whenExpr === 0 ||
    whenExpr === "0"
  ) {
    truthy = false;
  } else if (typeof whenExpr !== "string") {
    truthy = !!whenExpr;
  } else if (/[=!<>]=|&&|\|\||\s(and|or|not)\s/.test(whenExpr)) {
    truthy = !!evalExpression(whenExpr, { ...ctx.data, user: ctx.user });
  } else {
    // Post-interpolation resolved value (URL, id, filename, arbitrary text).
    truthy = true;
  }
  const branch = truthy ? node.children : node.else;
  if (!branch) return null;
  return <>{branch.map((c: any, i: number) => withKey(renderNode(c, ctx), c, i))}</>;
}
