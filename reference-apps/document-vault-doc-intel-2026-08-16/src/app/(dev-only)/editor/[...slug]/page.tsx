// (dev-only) — excluded from production builds via next.config.ts webpack rule.
// Server component wrapper that resolves the route slug then mounts the
// client editor. Library registry and theme tokens are imported in the
// client wrapper (lib/editor-mount.tsx) so the registry's function-bearing
// objects don't have to cross the RSC boundary.
import { EditorMount } from "@/lib/editor-mount";

export default async function EditorPage({
  params,
}: {
  params: Promise<{ slug: string[] }>;
}) {
  const { slug } = await params;
  const schemaPath = (slug ?? []).join("/");
  return <EditorMount schemaPath={schemaPath} />;
}
