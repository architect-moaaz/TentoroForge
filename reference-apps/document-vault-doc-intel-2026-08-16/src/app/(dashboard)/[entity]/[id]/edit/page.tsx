import { renderSchemaPage } from "@/lib/schema-page";
import { schemas } from "@/schemas/registry";
import { notFound } from "next/navigation";

export default async function EntityEditPage({
  params,
}: {
  params: Promise<{ entity: string; id: string }>;
}) {
  const { entity, id } = await params;
  const route = `/${entity}/[id]/edit`;
  if (!(route in schemas)) notFound();
  return renderSchemaPage(
    route,
    new Request(`internal:?id=${encodeURIComponent(id)}&mode=edit`),
  );
}
