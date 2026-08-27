import { EditorMount } from "@/components/schema-editor/EditorMount";

/**
 * Main editor route — renders the editor with a specific schema pre-loaded.
 *
 * URL: /editor/<projectId>/<...schemaPath>
 * Example: /editor/test-app/products/list → schemaPath = "products/list"
 */
export default async function EditorPage({
  params,
}: {
  params: Promise<{ projectId: string; slug: string[] }>;
}) {
  const { projectId, slug } = await params;
  const schemaPath = (slug ?? []).join("/");
  return <EditorMount projectId={projectId} schemaPath={schemaPath} />;
}
