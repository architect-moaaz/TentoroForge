// Landing page: renders src/schemas/index.json (Document Vault upload form)
// inside the (dashboard) route group so the shell layout (SideNav + header)
// wraps it. Replaces the previous role-based redirect.
import { renderSchemaPage } from "@/lib/schema-page";

export default async function RootPage() {
  return renderSchemaPage("/");
}
