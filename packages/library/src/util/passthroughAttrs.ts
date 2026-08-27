/**
 * Schema-supplied passthrough attributes. validateProps preserves a node's
 * `className` and `data-*` props universally (they never fail strict schemas);
 * components must actually render them or the guarantee dies at the render
 * layer — app CSS then has to resort to fragile :has() selectors to target
 * layout wrappers. Layout primitives (Cluster/Section/Card/…) call this on
 * their rest props and spread the result onto their root element.
 */
export function dataAttrProps(rest: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(rest)) {
    if (k.startsWith("data-")) out[k] = rest[k];
  }
  return out;
}

/** Join computed classes with an optional caller-supplied className (caller last so its utilities win ties in the cascade-order-independent cases). */
export function withCallerClass(computed: string, className?: string): string {
  return className ? `${computed} ${className}` : computed;
}
