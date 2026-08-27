// Registry-declared entity aliases. Generated from resource-registry.json so
// the data engine registers each entity under every known form (Pascal name,
// snake table, kebab slug, camel accessor) — authority, not a heuristic guess.
const ENTITY_ALIASES: Record<string, string[]> = {
  "document": ["Document", "documents", "document"],
  "documents": ["Document", "documents", "document"],
  "processdocumentjob": ["ProcessDocumentJob", "process_document_jobs", "process-document-jobs", "processDocumentJob", "process-document-job"],
  "processdocumentjobs": ["ProcessDocumentJob", "process_document_jobs", "process-document-jobs", "processDocumentJob", "process-document-job"],
  "user": ["User", "users", "user"],
  "users": ["User", "users", "user"]
};

function canonKey(s: string): string {
  return (s || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
}

/** Every registry-declared form of the entity a schema export identifies. */
export function aliasesFor(name: string): string[] {
  return ENTITY_ALIASES[canonKey(name)] || [];
}
