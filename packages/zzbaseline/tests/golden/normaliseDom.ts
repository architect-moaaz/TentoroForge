/**
 * Normalise an HTML string so JIT and SSR outputs become comparable.
 *
 * Differences we strip:
 *  - data-reactroot, data-react-helmet, data-tentoro-engine variations
 *  - Whitespace between tags
 *  - SSR-specific hydration markers (<template id="...">)
 *  - Attribute order (sort attrs alphabetically)
 *  - Style attribute formatting differences:
 *      JIT (jsdom CSSOM readback): "display:contents" (no spaces, no trailing semicolon)
 *      SSR (React string serialization): "display: contents;" (spaces, trailing semicolons)
 *    Both represent the same visual result; we normalise to the compact form.
 *
 * Differences we preserve:
 *  - Element tag names
 *  - Element nesting
 *  - data-node-id attributes (load-bearing for selection)
 *  - className values
 *  - Visible text
 */
function normaliseStyleAttr(match: string): string {
  // match is the full style="..." attribute value
  return match
    // Remove spaces after colons: "display: contents" → "display:contents"
    .replace(/:\s+/g, ":")
    // Remove spaces after semicolons: "display:contents; color:red" → "display:contents;color:red"
    .replace(/;\s+/g, ";")
    // Remove trailing semicolons before closing quote: "display:contents;" → "display:contents"
    .replace(/;"/g, '"')
    .replace(/;'/g, "'");
}

export function normaliseHtml(html: string): string {
  return html
    // Strip React/Next hydration scaffolding
    .replace(/<template[^>]*>[\s\S]*?<\/template>/g, "")
    .replace(/data-react(root|-helmet|-cache-css)=("[^"]*"|'[^']*'|\b)/g, "")
    .replace(/data-tentoro-engine=("[^"]*"|'[^']*'|\b)/g, "")
    // Normalise style attribute formatting (SSR vs JIT differ in spacing/semicolons)
    .replace(/style="[^"]*"/g, normaliseStyleAttr)
    .replace(/style='[^']*'/g, normaliseStyleAttr)
    // Normalise HTML entity encoding of quotes in attributes
    // JIT (jsdom) HTML-encodes single quotes as &#x27; / &apos;; SSR uses literal '
    .replace(/&#x27;/gi, "'")
    .replace(/&apos;/gi, "'")
    // Strip React comment boundary markers inserted by JIT (<!-- --> between text fragments)
    // These are React hydration boundary comments emitted by the client reconciler
    .replace(/<!-- -->/g, "")
    // Collapse whitespace between tags
    .replace(/>\s+</g, "><")
    .replace(/\s+>/g, ">")
    // Trim
    .trim();
}

/**
 * A coarser comparison: same set of (tag, data-node-id) pairs in the same order.
 * Less brittle when class strings differ but DOM structure matches.
 */
export function extractStructure(html: string): Array<{ tag: string; nodeId: string | null }> {
  const out: Array<{ tag: string; nodeId: string | null }> = [];
  const re = /<(\w+)(\s+[^>]*)?>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html)) !== null) {
    const tag = m[1];
    const attrs = m[2] ?? "";
    const idMatch = attrs.match(/data-node-id=["']([^"']+)["']/);
    out.push({ tag, nodeId: idMatch ? idMatch[1] : null });
  }
  return out;
}
