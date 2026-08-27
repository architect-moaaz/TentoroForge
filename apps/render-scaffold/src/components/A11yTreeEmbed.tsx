// apps/render-scaffold/src/components/A11yTreeEmbed.tsx
export function A11yTreeEmbed({ tree }: { tree: string }) {
  return (
    <script
      type="application/json"
      id="__a11y_tree__"
      // The tree is plain text; serialise as JSON-string so the contained
      // newlines and quotes survive HTML escaping.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(tree) }}
    />
  );
}
