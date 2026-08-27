# Authoring guide — runtime context bundle

**File:** `backend/runtime/context_bundles/<capability_name>/bundle.json` (+ optional provider template).
**Read first:** the existing 15 bundles under that directory.

A runtime context bundle names an **OS-level platform capability** (camera, biometric_auth, calendar_access, wallet_pass, …) and packages what the generated app needs to use it: iOS/Android permissions, Expo plugin declarations, native/web imports, an optional React provider template to mount at the root, and integration-key names the platform Settings must supply. The `runtime_context` axis in `reference_apps.json` and in the planner output is drawn *only* from names in this directory — so a bundle without a directory is invisible.

## When to add one

- The gap review or a plan output referenced a capability that maps 1:1 to a real OS API (unambiguous — the promotion threshold is 1 sighting).
- The mobile scaffolding needs to declare additional permissions/plugins that aren't yet grouped.
- A new class of hardware surface (nfc, ar, ble) becomes broadly useful.

Do NOT add:
- Web-only libraries (`stripe.js`) — those are integrations, not runtime context.
- SaaS API integrations (`resend`, `openai`) — those go through the platform_integrations model.
- A pseudo-capability like `fast_boot` that names an outcome, not a system API.

## Anatomy

Directory: `backend/runtime/context_bundles/<snake_case_name>/`.

Required: `bundle.json`:

```json
{
  "capability": "snake_case_name — MUST match the directory name",
  "permissions": {
    "ios": {"NSXxxUsageDescription": "One user-facing sentence explaining why we ask."},
    "android": ["android.permission.XXX"],
    "expo_plugins": ["expo-plugin-name"]
  },
  "native_imports": {
    "expo": ["expo-plugin-name"],
    "web": []
  },
  "provider": {
    "template_path": "providers/XxxProvider.tsx.tmpl",
    "wrap_at": "root",
    "hook_names": ["useXxx"]
  },
  "integration_keys": ["ENV_VAR_KEY_1"]
}
```

Optional: `providers/XxxProvider.tsx.tmpl` at the path you reference. The runtime injector copies this into the generated app and wraps `<body>` or the app root per `wrap_at`.

## Field discipline

- **`capability`** — snake_case, matches the directory name exactly. Case-sensitive.
- **iOS `permissions.ios`** — one `NSXxxUsageDescription` per required permission; the *value* is the sentence App Store review will read. Keep it plain and user-facing.
- **Android `permissions.android`** — fully-qualified Android permission strings.
- **`expo_plugins`** — plugin names that go into `app.json`'s `plugins` array. Empty if the capability is header-only.
- **`native_imports`** — module names the codegen may import. Split by `expo` (React Native) vs `web` (Next.js), because they diverge.
- **`provider`** — omit the whole block if no wrapper is needed. When present, the template must actually exist at the referenced path; the codegen fails hard on a missing template.
- **`integration_keys`** — env-var names the platform's Integrations settings must populate for the capability to *work* (e.g. `APPLE_WALLET_PASS_TYPE_ID`). Leave empty for capabilities that need only permission grants.

## After adding

1. `ls backend/runtime/context_bundles/` — confirm the new directory shows up alongside the existing 15.
2. `python3 -c "import json; print(json.load(open('backend/runtime/context_bundles/<name>/bundle.json'))['capability'])"` — verify JSON parses and the capability matches the dir name.
3. Reference the bundle from at least one entry in `reference_apps.json` so the planner sees it in context.
4. If the bundle ships a provider template, regen a test app that needs the capability and verify the provider mounts and the hook resolves.
