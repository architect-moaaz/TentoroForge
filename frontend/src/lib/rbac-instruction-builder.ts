import type { FieldAccessPolicy, FieldAccessMatrixTarget } from "@/types/rules";

/**
 * Generates comprehensive RBAC instructions from field_access_policies + record scope rules.
 * These instructions are sent to the code_editor agent to generate middleware in the app.
 */
export function buildRbacInstruction(
  policies: FieldAccessPolicy[],
  targets: FieldAccessMatrixTarget[],
): string {
  const targetMap = new Map(targets.map((t) => [t.id, t]));

  // Group policies by model
  const byModel = new Map<string, FieldAccessPolicy[]>();
  for (const p of policies) {
    const existing = byModel.get(p.model_name) || [];
    existing.push(p);
    byModel.set(p.model_name, existing);
  }

  const parts: string[] = [
    "Implement comprehensive field-level RBAC (Role-Based Access Control) for the application.",
    "",
    "## Requirements:",
    "",
  ];

  // 1. Middleware
  parts.push("### 1. RBAC Middleware (src/middleware/rbac.ts)");
  parts.push("Create middleware that:");
  parts.push("- Extracts the current user's role from the session/JWT");
  parts.push("- Filters API response fields based on role permissions");
  parts.push("- Rejects writes to read-only fields");
  parts.push("");

  // Per-model rules
  for (const [modelName, modelPolicies] of byModel) {
    parts.push(`#### Model: ${modelName}`);

    // Group by target
    const byTarget = new Map<string, FieldAccessPolicy[]>();
    for (const p of modelPolicies) {
      const key = p.target_id;
      const existing = byTarget.get(key) || [];
      existing.push(p);
      byTarget.set(key, existing);
    }

    for (const [targetId, targetPolicies] of byTarget) {
      const target = targetMap.get(targetId);
      const targetName = target?.name || targetId;

      const hiddenFields = targetPolicies
        .filter((p) => !p.can_view)
        .map((p) => p.field_name);
      const readOnlyFields = targetPolicies
        .filter((p) => p.can_view && !p.can_edit)
        .map((p) => p.field_name);

      if (hiddenFields.length > 0) {
        parts.push(`- Role "${targetName}": HIDE fields: ${hiddenFields.join(", ")}`);
      }
      if (readOnlyFields.length > 0) {
        parts.push(`- Role "${targetName}": READ-ONLY fields: ${readOnlyFields.join(", ")}`);
      }
    }
    parts.push("");
  }

  // 2. Permissions endpoint
  parts.push("### 2. Permissions Endpoint (src/app/api/me/permissions/route.ts)");
  parts.push("Create GET /api/me/permissions that returns:");
  parts.push("```json");
  parts.push("{");
  parts.push('  "role": "current_role",');
  parts.push('  "permissions": {');
  parts.push('    "ModelName": {');
  parts.push('      "field_name": { "view": true, "edit": false }');
  parts.push("    }");
  parts.push("  }");
  parts.push("}");
  parts.push("```");
  parts.push("");

  // 3. React hook
  parts.push("### 3. useFieldPermissions Hook (src/hooks/useFieldPermissions.ts)");
  parts.push("Create a React hook that:");
  parts.push('- Fetches /api/me/permissions on mount');
  parts.push("- Returns { canView(model, field), canEdit(model, field), isLoading }");
  parts.push("- Caches permissions for the session");
  parts.push("");

  // 4. UI integration
  parts.push("### 4. UI Integration");
  parts.push("- In list views: hide columns the user cannot view");
  parts.push("- In forms: disable/hide fields the user cannot edit");
  parts.push("- In detail views: hide fields the user cannot view");

  return parts.join("\n");
}

/**
 * Builds a concise instruction for applying field access changes to a single model.
 */
export function buildFieldAccessApplyInstruction(
  modelName: string,
  changes: { fieldName: string; targetName: string; canView: boolean; canEdit: boolean }[],
): string {
  const parts: string[] = [
    `Update field-level access control for model "${modelName}":`,
    "",
  ];

  for (const change of changes) {
    if (!change.canView) {
      parts.push(`- Hide "${change.fieldName}" from role "${change.targetName}"`);
    } else if (!change.canEdit) {
      parts.push(`- Make "${change.fieldName}" read-only for role "${change.targetName}"`);
    }
  }

  parts.push("");
  parts.push("Apply these changes to the RBAC middleware, API response filtering, and form field visibility.");

  return parts.join("\n");
}
