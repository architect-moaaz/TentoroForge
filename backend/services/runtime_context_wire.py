"""Runtime-context wire pass — reads ``plan.runtime_context`` and
computes the platform-side additions the generated app needs
(permissions, native imports, provider hooks, integration-key
requirements).

Pure planner: **returns a data structure**, doesn't touch files.
Callers in generate.py / mobile_scaffolding / platform_integrations
consume the result and emit their side of the artifacts:

- ``permissions_by_platform`` → merge into ``app.json`` /
  ``Info.plist`` / ``AndroidManifest.xml``
- ``native_imports`` → append to ``package.json`` / Expo config
- ``providers`` → wrap the root layout
- ``integration_keys_required`` → surface in ``/settings/integrations``

Keeping the compute pure means unit tests exercise every capability
without touching disk, and generate.py stays a thin coordinator.

See spec P1 runtime_context section and plan IRF-M3-T8.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


_BUNDLES_DIR = Path(__file__).resolve().parents[1] / "runtime" / "context_bundles"


# ══════════════════════════════════════════════════════════════════
# Types
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class IntegrationKey:
    provider: str
    env_var: str
    optional: bool
    docs: str


@dataclass(frozen=True)
class ProviderSpec:
    capability: str          # source capability (e.g. "geo")
    template_path: str       # bundle-relative path to provider template
    wrap_at: str             # "root" | future: "layout" | "page"
    hook_names: tuple[str, ...]


@dataclass(frozen=True)
class WirePlan:
    """The full compute output for a plan's runtime_context. Consumers
    read whichever slice they need. Every list is deduplicated;
    stable order = insertion order of the capabilities in the plan."""
    capabilities: tuple[str, ...]
    permissions_ios: dict[str, str]      # key → usage description
    permissions_android: tuple[str, ...]
    expo_plugins: tuple[str, ...]
    native_imports_expo: tuple[str, ...]
    native_imports_web: tuple[str, ...]
    providers: tuple[ProviderSpec, ...]
    integration_keys_required: tuple[IntegrationKey, ...]
    app_json_extras: dict[str, Any] = field(default_factory=dict)
    missing_bundles: tuple[str, ...] = ()  # declared capabilities with no bundle folder yet


# ══════════════════════════════════════════════════════════════════
# Bundle loader
# ══════════════════════════════════════════════════════════════════


@lru_cache(maxsize=32)
def _load_bundle(capability: str) -> dict[str, Any] | None:
    bundle_path = _BUNDLES_DIR / capability / "bundle.json"
    if not bundle_path.exists():
        return None
    try:
        return json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def clear_bundle_cache() -> None:
    """Test hook — reset the on-disk bundle cache."""
    _load_bundle.cache_clear()


def _dedupe(items) -> tuple:
    """Preserve first-seen order while dropping duplicates. Works on
    hashable items."""
    seen: set = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


# ══════════════════════════════════════════════════════════════════
# Compute — the public entry point
# ══════════════════════════════════════════════════════════════════


def compute_wire_plan(runtime_context: list[str] | None) -> WirePlan:
    """Read a plan's ``runtime_context`` list and return the resolved
    wire plan.

    Unknown / missing bundle for a declared capability is recorded in
    ``missing_bundles`` — the caller decides whether to warn (dev
    environments) or halt (strict CI). The wire pass itself never
    raises.

    Empty / None ``runtime_context`` yields an empty WirePlan — safe
    for apps that need no platform capabilities.
    """
    if not runtime_context:
        return WirePlan(
            capabilities=(),
            permissions_ios={},
            permissions_android=(),
            expo_plugins=(),
            native_imports_expo=(),
            native_imports_web=(),
            providers=(),
            integration_keys_required=(),
        )

    permissions_ios: dict[str, str] = {}
    permissions_android: list[str] = []
    expo_plugins: list[str] = []
    imports_expo: list[str] = []
    imports_web: list[str] = []
    providers: list[ProviderSpec] = []
    integration_keys: list[IntegrationKey] = []
    app_json_extras: dict[str, Any] = {}
    missing: list[str] = []
    resolved: list[str] = []

    for cap in runtime_context:
        bundle = _load_bundle(cap)
        if bundle is None:
            missing.append(cap)
            continue
        resolved.append(cap)

        perms = bundle.get("permissions") or {}
        ios = perms.get("ios") or {}
        if isinstance(ios, dict):
            for key, value in ios.items():
                # Convention: keys starting with "$" are meta
                # (associated domains list, etc). Route into
                # app_json_extras rather than the string-description
                # permissions dict.
                if key.startswith("$"):
                    app_json_extras.setdefault(f"ios_{key.lstrip('$')}", []).extend(
                        value if isinstance(value, list) else [value]
                    )
                else:
                    permissions_ios.setdefault(key, str(value))
        for android in perms.get("android") or []:
            permissions_android.append(str(android))
        for plugin in perms.get("expo_plugins") or []:
            expo_plugins.append(str(plugin))
        extras = perms.get("app_json_extras")
        if isinstance(extras, dict):
            for k, v in extras.items():
                app_json_extras.setdefault(k, v)

        native = bundle.get("native_imports") or {}
        for imp in native.get("expo") or []:
            imports_expo.append(str(imp))
        for imp in native.get("web") or []:
            imports_web.append(str(imp))

        provider = bundle.get("provider")
        if isinstance(provider, dict):
            providers.append(ProviderSpec(
                capability=cap,
                template_path=str(provider.get("template_path", "")),
                wrap_at=str(provider.get("wrap_at", "root")),
                hook_names=tuple(str(h) for h in provider.get("hook_names") or []),
            ))

        for key_spec in bundle.get("integration_keys") or []:
            if not isinstance(key_spec, dict):
                continue
            integration_keys.append(IntegrationKey(
                provider=str(key_spec.get("provider", "")),
                env_var=str(key_spec.get("env_var", "")),
                optional=bool(key_spec.get("optional", False)),
                docs=str(key_spec.get("docs", "")),
            ))

    return WirePlan(
        capabilities=_dedupe(resolved),
        permissions_ios=permissions_ios,
        permissions_android=_dedupe(permissions_android),
        expo_plugins=_dedupe(expo_plugins),
        native_imports_expo=_dedupe(imports_expo),
        native_imports_web=_dedupe(imports_web),
        providers=tuple(providers),
        integration_keys_required=tuple(integration_keys),
        app_json_extras=app_json_extras,
        missing_bundles=tuple(missing),
    )


# ══════════════════════════════════════════════════════════════════
# app.json merge helper — small deterministic transform
# ══════════════════════════════════════════════════════════════════


def merge_into_app_json(app_json: dict[str, Any], plan: WirePlan) -> dict[str, Any]:
    """Return a fresh dict with the wire plan merged into an existing
    ``app.json`` shape (Expo). Merges into ``expo.ios.infoPlist``,
    ``expo.android.permissions``, ``expo.plugins``, and any declared
    ``app_json_extras`` at ``expo.scheme`` / ``expo.ios.associatedDomains``.

    Never mutates the input; safe to use in test setup + real emit."""
    out = _deep_copy(app_json)
    expo = out.setdefault("expo", {})
    ios = expo.setdefault("ios", {})
    info_plist = ios.setdefault("infoPlist", {})
    for key, val in plan.permissions_ios.items():
        info_plist.setdefault(key, val)

    if plan.app_json_extras.get("ios_associated_domains"):
        assoc = ios.setdefault("associatedDomains", [])
        for domain in plan.app_json_extras["ios_associated_domains"]:
            if domain not in assoc:
                assoc.append(domain)

    android = expo.setdefault("android", {})
    perms = android.setdefault("permissions", [])
    for p in plan.permissions_android:
        if p not in perms:
            perms.append(p)

    plugins = expo.setdefault("plugins", [])
    for p in plan.expo_plugins:
        if p not in plugins:
            plugins.append(p)

    scheme = plan.app_json_extras.get("scheme")
    if scheme and "scheme" not in expo:
        expo["scheme"] = scheme

    return out


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value
