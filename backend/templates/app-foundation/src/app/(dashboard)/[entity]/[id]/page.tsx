import { renderSchemaPage } from "@/lib/schema-page";
import { schemas } from "@/schemas/registry";
import { notFound } from "next/navigation";

export default async function EntityDetailPage({
  params,
}: {
  params: Promise<{ entity: string; id: string }>;
}) {
  const { entity, id } = await params;
  // A literal nested page (e.g. /tasks/board) shares the /[entity]/[id] dynamic
  // segment with detail routes — match the concrete route FIRST so it isn't
  // mistaken for a record id and rendered as the detail page.
  // `path` lets renderer/resolveCrumbHrefs turn parameterised breadcrumb
  // ancestors (`/conferences/[id]`) back into links that resolve.
  const path = `/${entity}/${id}`;
  const literal = path;
  if (literal in schemas) {
    return renderSchemaPage(
      literal,
      new Request(`internal:?path=${encodeURIComponent(path)}`),
    );
  }
  const route = `/${entity}/[id]`;
  if (!(route in schemas)) notFound();
  return renderSchemaPage(
    route,
    new Request(
      `internal:?id=${encodeURIComponent(id)}&path=${encodeURIComponent(path)}`,
    )
  );
}
