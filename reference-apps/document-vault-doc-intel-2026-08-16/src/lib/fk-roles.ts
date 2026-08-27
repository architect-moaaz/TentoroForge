// FK-role authority for the runtime. Generated from the canonical registry
// (resource-registry.json) so auto-fill/form-exclusion read the REAL FK role
// instead of matching the column NAME. A domain FK (target != users) is never
// auto-filled with the current user's id.
export const FK_ROLES: Record<string, Record<string, string>> = {
  "documents": { "id": "plain", "originalFilename": "plain", "fileUrl": "plain", "mimeType": "plain", "fileSizeBytes": "plain", "status": "plain", "ocrText": "plain", "extractedFields": "plain", "confidence": "plain", "pageCount": "plain", "uploadedBy": "actor", "processedAt": "plain", "errorMessage": "plain", "createdAt": "plain", "updatedAt": "plain", "uploadedByName": "plain" },
  "process_document_jobs": { "id": "plain", "documentId": "domain", "step": "plain", "startedAt": "plain", "completedAt": "plain", "error": "plain", "createdAt": "plain", "updatedAt": "plain" },
  "users": { "id": "plain", "email": "plain", "name": "plain", "role": "plain", "createdAt": "plain", "updatedAt": "plain", "password": "plain", "isActive": "plain" }
};

export function fkRole(table: string, col: string): string {
  return FK_ROLES[table]?.[col] || "plain";
}

export function isAutoFillFk(table: string, col: string): boolean {
  const r = fkRole(table, col); return r === "actor" || r === "tenancy";
}

export function isDomainFk(table: string, col: string): boolean {
  return fkRole(table, col) === "domain";
}
