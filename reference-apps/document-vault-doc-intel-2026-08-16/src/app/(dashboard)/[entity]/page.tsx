import { renderSchemaPage } from "@/lib/schema-page";
import { schemas } from "@/schemas/registry";
import { notFound } from "next/navigation";
import { promises as fs } from "node:fs";
import path from "node:path";

export default async function EntityListPage({
  params,
}: {
  params: Promise<{ entity: string }>;
}) {
  const { entity } = await params;
  // registry is keyed by ROUTE ("/tasks"); the home page lives at "/".
  const route = entity === "home" ? "/" : `/${entity}`;
  if (!(route in schemas)) {
    // Not in the compiled registry — but a page added AFTER generation (e.g.
    // via the visual editor) has a schema file on disk that renderSchemaPage
    // resolves. Render it when the file exists; only 404 when it truly doesn't.
    const safe = entity && !entity.includes("..");
    const file = safe
      ? path.join(process.cwd(), "src", "schemas", `${entity}.json`)
      : "";
    let exists = false;
    if (file) {
      try { await fs.access(file); exists = true; } catch { /* missing */ }
    }
    if (!exists) notFound();
  }
  return renderSchemaPage(route);
}
