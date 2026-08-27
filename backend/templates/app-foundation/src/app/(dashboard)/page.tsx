import { renderSchemaPage } from "@/lib/schema-page";

// The dashboard index ("/") renders the generated home schema (registry key "/").
export default async function DashboardHome({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  return renderSchemaPage("/", undefined, await searchParams);
}
