"""Spec registry — the single source of truth for which secrets each
workflow action type needs.

Used by three consumers:

1. `env_scaffold` (post-generate) — writes a sectioned `.env.local` with
   commented headers per provider and correct required/optional annotations.
2. `integrations_scaffold` (post-generate) — emits the /settings/integrations
   page schema. One Card per provider actually used by the plan's workflows,
   with form fields derived from the ConfigKey entries here.
3. `binding_validator` / plan validation — flags workflows referencing action
   types the runtime can service but for which no key source (DB or env) is
   configured; a warn-level signal for the reviewer, not a hard fail.

Every workflow action type whose runtime handler reads a secret MUST have
an entry here. Types that read no secrets (`db_insert`, `http_call`, `custom`,
`send_notification`) intentionally have none — `providers_for_action()` returns
`[]` for them and callers skip them.

Providers grouped in v1: `resend` (email), `anthropic` (AI), `s3` (uploads).
`twilio` and `stripe` are placeholders shipped to prove the shape for future
node types — they have no runtime handler yet, so nothing reads their keys,
but the settings page will render their cards when a plan references
`send_sms` / `stripe_charge` in a future release.

Design: docs/superpowers/specs/2026-07-22-integrations-settings.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


# --------------------------------------------------------------------------- #
# Types
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ConfigKey:
    """One env var / integrations-row that a workflow action type needs.

    Fields:
      key         — the env var name (UPPER_SNAKE_CASE), also used as the
                    `key` column value in the `integrations` table.
      provider    — logical grouping. All keys with the same provider share
                    one Card on the settings page and one HKDF subkey for
                    encryption. Lower-case, hyphenless.
      label       — human-readable label for the settings-page form field.
      kind        — form-field type: `password` (masked input, never echoed
                    back from the API), `text`, `url`, or `select` (dropdown).
      required    — whether the action's handler will error without it. UI
                    marks required fields with an asterisk; env scaffolder
                    uses this for the `# REQUIRED` comment.
      default     — a documented default string, or None. When set, the
                    resolver falls back to this if both DB and env are empty.
      help_url    — optional link to the provider's docs (e.g. "how to get
                    a Resend API key"). Rendered as a small help link on
                    the form field.
      options     — for kind='select', the list of allowed values. UI
                    renders a dropdown; API rejects any PUT whose value
                    isn't in this list. Ignored for other kinds.
    """

    key: str
    provider: str
    label: str
    kind: str  # "password" | "text" | "url" | "select"
    required: bool
    default: str | None = None
    help_url: str | None = None
    options: tuple[str, ...] | None = None


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #

# Mapping: workflow action type → list of ConfigKey.
# Cross-referenced against runtime handlers in:
#   standalone-app/src/lib/workflows/index.ts  (send_email, ...)
#   standalone-app/src/lib/workflows/ai.ts     (ai_generate, ai_classify, ai_extract, ai_decide)
#   standalone-app/src/lib/storage.ts          (S3 uploads — indirect via file API)
NODE_CONFIG_SPECS: dict[str, list[ConfigKey]] = {
    # --- Email --------------------------------------------------------- #
    # Two providers, mutually exclusive: SMTP wins when SMTP_HOST is set,
    # Resend is used otherwise. FORGE_EMAIL_FROM is shared (it lives under
    # `resend` in the registry but the runtime reads it for either path).
    "send_email": [
        # Resend
        ConfigKey(
            key="RESEND_API_KEY",
            provider="resend",
            label="Resend API key",
            kind="password",
            required=False,  # optional because SMTP is an alternative
            help_url="https://resend.com/api-keys",
        ),
        ConfigKey(
            key="FORGE_EMAIL_FROM",
            provider="resend",
            label="From address",
            kind="text",
            required=False,
            default="onboarding@resend.dev",
            help_url="https://resend.com/docs/dashboard/domains/introduction",
        ),
        # SMTP — overrides Resend when SMTP_HOST is set
        ConfigKey(
            key="SMTP_HOST",
            provider="smtp",
            label="SMTP host",
            kind="text",
            required=False,
            help_url="https://nodemailer.com/smtp/",
        ),
        ConfigKey(
            key="SMTP_PORT",
            provider="smtp",
            label="Port",
            kind="text",
            required=False,
            default="587",
        ),
        ConfigKey(
            key="SMTP_USER",
            provider="smtp",
            label="Username",
            kind="text",
            required=False,
        ),
        ConfigKey(
            key="SMTP_PASSWORD",
            provider="smtp",
            label="Password",
            kind="password",
            required=False,
        ),
    ],

    # --- AI actions — all four share ANTHROPIC_API_KEY --------------- #
    # The Anthropic card renders ONE row per key, deduped across actions.
    "ai_generate": [
        ConfigKey(
            key="ANTHROPIC_API_KEY",
            provider="anthropic",
            label="Anthropic API key",
            kind="password",
            required=True,
            help_url="https://console.anthropic.com/settings/keys",
        ),
        ConfigKey(
            key="FORGE_AI_MODEL",
            provider="anthropic",
            label="Model",
            kind="select",
            required=False,
            default="claude-sonnet-4-6",
            help_url="https://docs.anthropic.com/en/docs/about-claude/models",
            # Ordered most-capable → fastest. Version-pinned ids are the
            # values that actually go into ANTHROPIC_MODEL; the dropdown
            # shows a friendlier label to the user via the frontend map.
            options=(
                "claude-opus-4-8",
                "claude-opus-4-7",
                "claude-sonnet-5",
                "claude-sonnet-4-6",
                "claude-haiku-4-5-20251001",
                "claude-fable-5",
            ),
        ),
    ],
    "ai_classify": [
        ConfigKey(
            key="ANTHROPIC_API_KEY",
            provider="anthropic",
            label="Anthropic API key",
            kind="password",
            required=True,
            help_url="https://console.anthropic.com/settings/keys",
        ),
    ],
    "ai_extract": [
        ConfigKey(
            key="ANTHROPIC_API_KEY",
            provider="anthropic",
            label="Anthropic API key",
            kind="password",
            required=True,
            help_url="https://console.anthropic.com/settings/keys",
        ),
    ],
    "ai_decide": [
        ConfigKey(
            key="ANTHROPIC_API_KEY",
            provider="anthropic",
            label="Anthropic API key",
            kind="password",
            required=True,
            help_url="https://console.anthropic.com/settings/keys",
        ),
    ],
    # --- Document OCR (PaddleOCR sidecar) ------------------------------- #
    # First-class OCR primitive. Runs against a PaddleOCR HTTP sidecar the
    # operator hosts (e.g. paddlepaddle/paddleocr container behind a thin
    # /ocr wrapper) so on-prem / air-gapped banking + healthcare + doc-
    # intelligence apps can extract text + bounding-boxes without shipping
    # documents to a cloud LLM. URL is required; API key is optional (only
    # needed when the sidecar sits behind an auth proxy). The runtime
    # handler auto-chooses body shape: {file_url} when the document lives
    # in the app's file store, {file_b64} fallback for inline uploads.
    "ocr_document": [
        ConfigKey(
            key="PADDLEOCR_URL",
            provider="paddleocr",
            label="PaddleOCR sidecar URL",
            kind="url",
            required=True,
            help_url="https://github.com/PaddlePaddle/PaddleOCR",
        ),
        ConfigKey(
            key="PADDLEOCR_API_KEY",
            provider="paddleocr",
            label="Sidecar API key (optional)",
            kind="password",
            required=False,
        ),
    ],
    # Vision preset — specialisation of ai_extract that takes a forge_files
    # image id and returns strict {brand, model, category, attributes[,confidence]}
    # JSON. Shares the same Anthropic key + model dropdown as the other
    # ai_* actions; the FORGE_AI_MODEL entry is duplicated here (not just on
    # ai_generate) so a plan that only uses this preset still surfaces the
    # model picker on the settings page.
    "ai_identify_product": [
        ConfigKey(
            key="ANTHROPIC_API_KEY",
            provider="anthropic",
            label="Anthropic API key",
            kind="password",
            required=True,
            help_url="https://console.anthropic.com/settings/keys",
        ),
        ConfigKey(
            key="FORGE_AI_MODEL",
            provider="anthropic",
            label="Model",
            kind="text",
            required=False,
            default="claude-sonnet-4-6",
            help_url="https://docs.anthropic.com/en/docs/about-claude/models",
        ),
    ],

    # --- File storage (S3) ------------------------------------------- #
    # Used by `generate_document` (uploads the PDF) and by the built-in
    # /api/files upload route (fed by FileUpload components in forms and by
    # `file_upload` workflow nodes). All five keys are OPTIONAL: an empty
    # bucket falls back to the local disk path in FORGE_UPLOAD_DIR — fine
    # for dev, but for prod deployments you point at real S3.
    "generate_document": [
        ConfigKey(
            key="FORGE_S3_BUCKET",
            provider="s3",
            label="S3 bucket",
            kind="text",
            required=False,
            help_url="https://docs.aws.amazon.com/AmazonS3/latest/userguide/creating-bucket.html",
        ),
        ConfigKey(
            key="FORGE_S3_REGION",
            provider="s3",
            label="S3 region",
            kind="text",
            required=False,
            default="us-east-1",
        ),
        ConfigKey(
            key="FORGE_S3_PREFIX",
            provider="s3",
            label="Key prefix",
            kind="text",
            required=False,
            default="uploads/",
        ),
        ConfigKey(
            key="AWS_ACCESS_KEY_ID",
            provider="s3",
            label="AWS access key id",
            kind="password",
            required=False,
            help_url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html",
        ),
        ConfigKey(
            key="AWS_SECRET_ACCESS_KEY",
            provider="s3",
            label="AWS secret access key",
            kind="password",
            required=False,
        ),
    ],
    # `file_upload` — currently no runtime handler by that name (files enter
    # via UI), but declared so any future workflow node that uploads a file
    # inherits the same S3 card. Keys are identical to generate_document.
    "file_upload": [
        ConfigKey(
            key="FORGE_S3_BUCKET",
            provider="s3",
            label="S3 bucket",
            kind="text",
            required=False,
        ),
        ConfigKey(
            key="FORGE_S3_REGION",
            provider="s3",
            label="S3 region",
            kind="text",
            required=False,
            default="us-east-1",
        ),
        ConfigKey(
            key="FORGE_S3_PREFIX",
            provider="s3",
            label="Key prefix",
            kind="text",
            required=False,
            default="uploads/",
        ),
        ConfigKey(
            key="AWS_ACCESS_KEY_ID",
            provider="s3",
            label="AWS access key id",
            kind="password",
            required=False,
        ),
        ConfigKey(
            key="AWS_SECRET_ACCESS_KEY",
            provider="s3",
            label="AWS secret access key",
            kind="password",
            required=False,
        ),
    ],

    # --- Scheduled workflows ----------------------------------------- #
    # CRON_SECRET gates /api/cron/tick. Optional: without it, the tick
    # endpoint is unauthenticated (fine when you're the only one calling
    # it, dangerous once the app is publicly reachable). Included when the
    # plan contains any workflow whose trigger.type === "schedule" — see
    # providers_used_by_plan below.
    "__cron__": [
        ConfigKey(
            key="CRON_SECRET",
            provider="cron",
            label="Cron secret (bearer token)",
            kind="password",
            required=False,
            help_url="https://vercel.com/docs/cron-jobs#securing-cron-jobs",
        ),
    ],

    # --- Sensitive-column encryption (Slice-4) ---------------------- #
    # Synthetic "action type": no workflow node calls "__encryption__",
    # but every generated app that declares a `sensitive: true` column
    # needs SENSITIVE_ENCRYPTION_KEY to encrypt-at-rest and decrypt on
    # unmask. Registered here so the settings page + env writer surface
    # + persist it via the same crypto path as every other integration.
    #
    # A per-app 32-byte AES-256 key is auto-generated at runtime_injector
    # time when the plan uses sensitive columns AND the org hasn't set
    # its own; the user can rotate later by pasting a new base64 key on
    # /settings/integrations. See TODO(sensitive-rotation) in
    # templates/runtime/sensitive-crypto.ts — versioned rotation is a
    # separate slice.
    "__encryption__": [
        ConfigKey(
            key="SENSITIVE_ENCRYPTION_KEY",
            provider="encryption",
            label="Sensitive-column encryption key (base64, 32 bytes)",
            kind="password",
            required=False,
            help_url=None,
        ),
    ],

    # --- MCP servers (Agent Builder tool_type=mcp) ------------------- #
    # Synthetic "action type": individual MCP server secrets are
    # dynamic (one env var per server row in platform_mcp_servers),
    # so this static registry only records the presence of the "mcp"
    # provider. `env_writer.write_env_local_from_platform` walks
    # PlatformMcpServer rows and emits MCP_SERVER_<id>_URL /
    # _TRANSPORT / _AUTH_KIND / _SECRET / _AUTH_HEADER per row.
    #
    # A single placeholder ConfigKey exists so `all_providers()`
    # includes "mcp" and the integrations catalog UI doesn't have to
    # special-case its absence. It's not user-editable via the
    # per-key PUT endpoint — MCP servers are managed via
    # /api/orgs/{id}/mcp-servers (routers/platform_mcp_servers.py).
    "__mcp__": [
        ConfigKey(
            key="MCP_SERVERS_MANAGED",
            provider="mcp",
            label="MCP servers (managed separately)",
            kind="text",
            required=False,
            help_url=None,
        ),
    ],

    # --- Mobile builds (MOBILE-B) ------------------------------------ #
    # Synthetic "action type": no workflow ever calls "mobile_build", but
    # the credentials it needs share the registry shape so they surface
    # in the same /settings/integrations UI, use the same crypto, and are
    # queried by the same API. Slice C reads these to call the EAS
    # Build REST API on the user's behalf; Slice D adds the Publish-dialog
    # buttons that trigger it.
    #
    # Expo EAS
    #   EXPO_EAS_TOKEN     — access token from expo.dev → account settings.
    #                        Grants Slice C the ability to enqueue builds.
    # Apple App Store Connect (for iOS store submission)
    #   APPLE_TEAM_ID      — 10-char team id, becomes part of bundle-id
    #                        namespace; visible on Apple Developer portal.
    #   APPLE_ASC_KEY_ID   — 10-char App Store Connect API key id.
    #   APPLE_ASC_ISSUER_ID — UUID from ASC → Users and Access → Integrations.
    #   APPLE_ASC_PRIVATE_KEY — full .p8 file contents (multiline). EAS
    #                        submit reads this to sign the IPA + submit.
    # Google Play Console (for Android store submission)
    #   GOOGLE_PLAY_SERVICE_ACCOUNT_JSON — full service-account JSON blob
    #                        from Google Play Console → Setup → API access.
    "mobile_build": [
        ConfigKey(
            key="EXPO_EAS_TOKEN",
            provider="expo_eas",
            label="Expo EAS access token",
            kind="password",
            required=True,
            help_url="https://expo.dev/accounts/[account]/settings/access-tokens",
        ),
        ConfigKey(
            key="APPLE_TEAM_ID",
            provider="apple_asc",
            label="Apple team id",
            kind="text",
            required=False,
            help_url="https://developer.apple.com/account/",
        ),
        ConfigKey(
            key="APPLE_ASC_KEY_ID",
            provider="apple_asc",
            label="App Store Connect API key id",
            kind="text",
            required=False,
            help_url="https://appstoreconnect.apple.com/access/api",
        ),
        ConfigKey(
            key="APPLE_ASC_ISSUER_ID",
            provider="apple_asc",
            label="App Store Connect issuer id",
            kind="text",
            required=False,
            help_url="https://appstoreconnect.apple.com/access/api",
        ),
        ConfigKey(
            key="APPLE_ASC_PRIVATE_KEY",
            provider="apple_asc",
            label="App Store Connect .p8 private key",
            kind="password",
            required=False,
            help_url="https://appstoreconnect.apple.com/access/api",
        ),
        ConfigKey(
            key="GOOGLE_PLAY_SERVICE_ACCOUNT_JSON",
            provider="google_play",
            label="Google Play service account JSON",
            kind="password",
            required=False,
            help_url="https://play.google.com/console/",
        ),
    ],

    # --- Event bus nodes (R3) — no secrets --------------------------- #
    # Registered explicitly (rather than omitted) so validators + the
    # editor recognise them as known runtime action types.
    #
    # emit_event config fields (runtime/events/emit-node.ts):
    #   event    — event type to emit, e.g. "order.approved" ({{refs}} ok)
    #   payload  — field → value map, values support {{refs}}
    #   entity   — optional entity slug the event concerns
    #   entityId — optional entity id ({{refs}} ok)
    "emit_event": [],
    # wait_for_event config fields (runtime/workflows/engine.ts):
    #   event     — event type to wait for, e.g. "payment.received"
    #   timeoutMs — optional; surfaced as the pending task's due_at
    "wait_for_event": [],
}


# --------------------------------------------------------------------------- #
# Query helpers — used by env_scaffold, integrations_scaffold, validators
# --------------------------------------------------------------------------- #

def providers_for_action(action_type: str) -> list[str]:
    """Return the sorted-unique list of providers this action type needs.
    Empty list for actions with no secrets (db_insert, http_call, custom,
    send_notification) OR for unknown action types — never raises."""
    entries = NODE_CONFIG_SPECS.get(action_type, [])
    return sorted({e.provider for e in entries})


def providers_used_by_plan(plan: dict[str, Any] | None) -> list[str]:
    """Walk every workflow in the plan and return the union of providers
    referenced. Used by the settings-page emitter so a plan that never
    calls `send_email` doesn't get a Resend card on its settings page.

    Tolerates both plan shapes:
      - planner output (`workflow.steps` before translation)
      - translator output (`workflow.nodes` after translation)

    Malformed nodes/configs are silently skipped — plans in the wild
    have inconsistent shapes and this helper runs in gen-pipeline code
    that must never crash on bad input.
    """
    if not isinstance(plan, dict):
        return []
    workflows = plan.get("workflows") or []
    if not isinstance(workflows, list):
        return []

    provs: set[str] = set()
    for wf in workflows:
        if not isinstance(wf, dict):
            continue
        # Workflow-level trigger.type=schedule → cron. Both the top-level
        # `trigger` (translator shape) and `definition.trigger` (some
        # emitters) are checked.
        for tkey in ("trigger", "definition"):
            t = wf.get(tkey)
            if isinstance(t, dict):
                trig = t.get("trigger") if tkey == "definition" else t
                if isinstance(trig, dict) and trig.get("type") == "schedule":
                    provs.update(providers_for_action("__cron__"))
        # Both shapes: prefer 'nodes' (post-translate) then fall back to 'steps' (planner).
        for shape_key in ("nodes", "steps"):
            nodes = wf.get(shape_key)
            if not isinstance(nodes, list):
                continue
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                # Trigger nodes carry their own `type: "schedule"` in some shapes.
                if node.get("type") == "trigger":
                    n_cfg = node.get("config") or node.get("data", {}).get("config", {})
                    if isinstance(n_cfg, dict) and (
                        n_cfg.get("type") == "schedule"
                        or n_cfg.get("triggerType") == "schedule"
                    ):
                        provs.update(providers_for_action("__cron__"))
                config = node.get("config")
                if not isinstance(config, dict):
                    continue
                at = config.get("actionType")
                if not isinstance(at, str):
                    continue
                provs.update(providers_for_action(at))
    return sorted(provs)


def providers_used_by_app(output_dir: str | "Path") -> list[str]:  # type: ignore[name-defined]
    """Union of ``providers_used_by_plan(plan)`` with capability signals
    read from the generated app's file system:

      - any page schema references the ``FileUpload`` component
        → include ``s3`` (the /api/files upload target is S3-or-disk).

    Runs from the settings-page scaffolder so the /settings/integrations
    page picks up S3 even when the plan has no explicit workflow node
    that uploads (the common case: users upload via UI forms).

    Never raises — a missing / unreadable app dir returns whatever
    signals were parseable.
    """
    import json as _json
    from pathlib import Path as _Path

    root = _Path(output_dir)
    provs: set[str] = set()

    # Plan-based signals (existing behavior).
    plan: dict[str, object] = {}
    for rel in ("src/contracts/plan.json", "contracts/plan.json"):
        p = root / rel
        if p.is_file():
            try:
                data = _json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    plan = data
            except (OSError, ValueError):
                pass
            break
    provs.update(providers_used_by_plan(plan))

    # Capability signal: FileUpload component in any page schema → S3.
    schemas_dir = root / "src" / "schemas"
    if schemas_dir.is_dir():
        for schema_path in schemas_dir.rglob("*.json"):
            try:
                if '"FileUpload"' in schema_path.read_text(encoding="utf-8"):
                    provs.update(providers_for_action("file_upload"))
                    break
            except OSError:
                continue

    return sorted(provs)


def keys_for_provider(provider: str) -> list[ConfigKey]:
    """Return all unique ConfigKey entries for one provider, deduped by
    `key` field. Used by the settings UI: one Card per provider, one form
    field per unique key. Dedup matters because e.g. ANTHROPIC_API_KEY
    appears under all four ai_* actions in the registry — the card must
    show it once, not four times.

    Dedup preserves the FIRST occurrence's metadata (label/required/help_url),
    which lets us have richer entries on the primary action type (ai_generate)
    and terser ones on the shared types.
    """
    seen: dict[str, ConfigKey] = {}
    for entries in NODE_CONFIG_SPECS.values():
        for entry in entries:
            if entry.provider != provider:
                continue
            if entry.key in seen:
                continue
            seen[entry.key] = entry
    return list(seen.values())


def all_providers() -> list[str]:
    """Every provider mentioned anywhere in the registry, sorted."""
    provs: set[str] = set()
    for entries in NODE_CONFIG_SPECS.values():
        for entry in entries:
            provs.add(entry.provider)
    return sorted(provs)
