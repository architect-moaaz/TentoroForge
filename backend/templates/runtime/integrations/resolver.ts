/**
 * Runtime resolver for integration secrets.
 *
 *   getSecret("resend", "RESEND_API_KEY")  → string | undefined
 *
 * Precedence: process.env[key] > documented default.
 *
 * The generated app reads credentials only from its own environment. The
 * app creator configures credentials on the Forge platform's settings
 * page (once per org); the generation pipeline (or the manual "sync"
 * button on the project page) writes those values into `.env.local`.
 *
 * Handlers keep calling this thin abstraction — not `process.env.X` —
 * so the runtime never has to change if the platform later grows a
 * different provisioning mechanism (e.g. a mounted secrets file).
 *
 * Spec: docs/superpowers/specs/2026-07-22-integrations-settings.md.
 */

// Small mirror of ConfigKey.default from backend/services/node_config_specs.py.
// Only keys with a documented default belong here. Regeneration overwrites
// this file — hand-edits will be lost.
const DEFAULTS: Record<string, Record<string, string>> = {
  resend: {
    FORGE_EMAIL_FROM: "onboarding@resend.dev",
  },
  anthropic: {
    FORGE_AI_MODEL: "claude-sonnet-4-6",
  },
  s3: {
    FORGE_S3_REGION: "us-east-1",
    FORGE_S3_PREFIX: "uploads/",
  },
};

// Kept for API compatibility with earlier handler code that called
// `clearSecretCache()` after a PUT. The runtime no longer caches
// (there's nothing to cache — env is already in memory), so this is
// a no-op. Safe to remove once the callers stop referencing it.
export function clearSecretCache(): void {
  /* no-op */
}

export async function getSecret(
  provider: string,
  key: string,
): Promise<string | undefined> {
  const env = process.env[key];
  if (env) return env;
  return DEFAULTS[provider]?.[key];
}
