import { renderSchemaPage } from "@/lib/schema-page";
import { schemas } from "@/schemas/registry";
import { notFound } from "next/navigation";

export default async function EntityNewPage({
  params,
}: {
  params: Promise<{ entity: string }>;
}) {
  const { entity } = await params;
  const route = `/${entity}/new`;
  if (!(route in schemas)) notFound();
  return renderSchemaPage(route, new Request("internal:?mode=new"));
}
