import { renderSchemaPage } from "@/lib/schema-page";
import { schemas } from "@/schemas/registry";
import { notFound } from "next/navigation";

// Catch-all for verb-suffixed record routes such as /sessions/[id]/book,
// /appointments/[id]/checkout, /invoices/[id]/approve. Literal `edit` still
// wins because Next.js prefers a static segment over a dynamic one, so
// /sessions/abc/edit continues to hit the edit route rather than this file.
export default async function EntityActionPage({
  params,
}: {
  params: Promise<{ entity: string; id: string; action: string }>;
}) {
  const { entity, id, action } = await params;
  // Literal three-segment route wins first (e.g. /tasks/board/detail),
  // then the dynamic /entity/[id]/action shape.
  const literal = `/${entity}/${id}/${action}`;
  if (literal in schemas) return renderSchemaPage(literal, new Request("internal:"));
  const route = `/${entity}/[id]/${action}`;
  if (!(route in schemas)) notFound();
  return renderSchemaPage(
    route,
    new Request(`internal:?id=${encodeURIComponent(id)}&action=${encodeURIComponent(action)}`),
  );
}
