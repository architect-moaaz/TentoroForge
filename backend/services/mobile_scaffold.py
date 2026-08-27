"""Emit an Expo React Native mobile shell into every generated app.

MOBILE-A. Runs as a post-generate pass. Produces a ``mobile/`` folder
that can be built into APK / AAB / IPA by EAS Build (Slice C wires the
platform to call EAS automatically; today the user runs
``npx eas build`` themselves).

The shell is a thin WebView pointed at the deployed URL, so every
generated app gets a store-submittable native binary without a
separate React Native codebase. Slice E later replaces the placeholder
icon/splash with real ones derived from ``design_spec.json``.

Files emitted (all under ``<output_dir>/mobile/``):

    app.json           Expo config, name/icon/splash/bundle ids
    App.tsx            WebView shell
    eas.json           dev / preview / production build profiles
    package.json       deps + scripts
    tsconfig.json
    babel.config.js
    .gitignore
    README.md          manual-build + store-submit instructions
    assets/icon.png            (1024x1024 placeholder)
    assets/adaptive-icon.png   (1024x1024 placeholder, Android)
    assets/splash.png          (1242x2436 placeholder)
    assets/favicon.png         (48x48 placeholder)

All placeholders are neutral solid-color PNGs. Slice E rewrites them
with brand-derived icons.

Idempotent: re-runs overwrite ``app.json`` with fresh substitutions
(picks up a new deployed URL / brand color) but never touches
``node_modules`` or an ``eas init``-produced project id already saved
in ``app.json``.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import struct
import zlib
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger(__name__)


_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "mobile"

# Placeholders that the scaffolder substitutes in file bodies.
_APP_NAME_PLACEHOLDER = "__APP_NAME__"
_APP_SLUG_PLACEHOLDER = "__APP_SLUG__"
_BUNDLE_ID_PLACEHOLDER = "__BUNDLE_ID__"
_BRAND_COLOR_PLACEHOLDER = "__BRAND_COLOR__"
_DEPLOYED_URL_PLACEHOLDER = "__DEPLOYED_URL__"
_EAS_PROJECT_ID_PLACEHOLDER = "__EAS_PROJECT_ID__"

# Files whose bytes we substitute. Everything else is copied verbatim.
_SUBSTITUTED_FILES = {
    "app.json",
    "App.tsx",
    "package.json",
    "README.md",
}

# Default brand color when the plan/design spec doesn't declare one.
_DEFAULT_BRAND_HEX = "#4F46E5"  # indigo — matches platform accent


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

def scaffold_mobile(
    output_dir: str,
    *,
    app_name: Optional[str] = None,
    deployed_url: str = "",
    brand_hex: Optional[str] = None,
    bundle_id: Optional[str] = None,
) -> dict[str, Any]:
    """Emit ``<output_dir>/mobile/`` with substituted placeholders.

    Args:
        output_dir: The generated app's root.
        app_name: Human name shown on the home screen icon. Falls back
            to the ``module_name`` from ``contracts/plan.json``, then to
            the folder name.
        deployed_url: The web app's deployed URL. May be empty at first
            gen (Publish hasn't run yet) — the shell handles that with a
            "not configured yet" screen at runtime.
        brand_hex: 6-hex-digit color for splash background + Android
            adaptive icon. Falls back to design_spec, then default.
        bundle_id: Reverse-DNS bundle identifier (e.g. ``com.acme.app``).
            Defaults to ``com.tentoro.<slug>``.

    Returns a summary dict for logging / SSE.
    """
    out = Path(output_dir)
    if not out.is_dir():
        raise ValueError(f"output_dir missing: {output_dir}")

    resolved_name = app_name or _infer_app_name(out)
    slug = _slugify(resolved_name)
    resolved_brand = _normalize_hex(brand_hex or _infer_brand_hex(out))
    resolved_bundle = bundle_id or f"com.tentoro.{slug.replace('-', '')}"
    resolved_url = (deployed_url or "").strip()

    mobile_dir = out / "mobile"
    (mobile_dir / "assets").mkdir(parents=True, exist_ok=True)

    # Preserve a prior eas_project_id if the user has already run
    # `eas init` — that value is captured in app.json's extra.eas.projectId.
    prior_eas_id = _read_prior_eas_project_id(mobile_dir / "app.json")

    substitutions = {
        _APP_NAME_PLACEHOLDER: resolved_name,
        _APP_SLUG_PLACEHOLDER: slug,
        _BUNDLE_ID_PLACEHOLDER: resolved_bundle,
        _BRAND_COLOR_PLACEHOLDER: resolved_brand,
        _DEPLOYED_URL_PLACEHOLDER: resolved_url,
        _EAS_PROJECT_ID_PLACEHOLDER: prior_eas_id or "",
    }

    files_written: list[str] = []
    for src in sorted(_TEMPLATE_DIR.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(_TEMPLATE_DIR)
        if any(part == "assets" for part in rel.parts):
            # Skip template assets — we synthesize placeholder PNGs below.
            continue
        dst = mobile_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.name in _SUBSTITUTED_FILES:
            text = src.read_text(encoding="utf-8")
            for placeholder, value in substitutions.items():
                text = text.replace(placeholder, value)
            dst.write_text(text, encoding="utf-8")
        else:
            shutil.copy2(src, dst)
        files_written.append(str(rel))

    # Stash the plan description into expo.extra.description so MOBILE-E's
    # store-listing generator has real copy to work with. Post-processed
    # (not via placeholder substitution) because the description contains
    # arbitrary text — quotes, newlines, angle brackets — that would
    # corrupt the JSON if spliced in as raw text. json.dumps handles it.
    description = _infer_app_description(out)
    if description:
        try:
            app_json_path = mobile_dir / "app.json"
            data = json.loads(app_json_path.read_text(encoding="utf-8"))
            expo = data.setdefault("expo", {})
            extra = expo.setdefault("extra", {})
            extra["description"] = description
            app_json_path.write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            # If app.json somehow doesn't parse, don't nuke the scaffold —
            # the store listing will just use the generic fallback.
            pass

    # IRF-M3-T9: merge plan.runtime_context into app.json — permissions,
    # native plugins, associated domains, scheme. Reads the resolved
    # WirePlan from services.runtime_context_wire (M3-T8). Idempotent.
    # No-op when plan has no runtime_context or app.json missing.
    try:
        from services.runtime_context_wire import compute_wire_plan, merge_into_app_json
        _plan_dict = _read_plan_dict(out)
        _rc = _plan_dict.get("runtime_context") if isinstance(_plan_dict, dict) else None
        if _rc:
            _app_json_path = mobile_dir / "app.json"
            if _app_json_path.exists():
                _current = json.loads(_app_json_path.read_text(encoding="utf-8"))
                _wire = compute_wire_plan(_rc)
                _merged = merge_into_app_json(_current, _wire)
                if _merged != _current:
                    _app_json_path.write_text(
                        json.dumps(_merged, indent=2) + "\n", encoding="utf-8",
                    )
                    logger.info(
                        "[mobile_scaffold] merged runtime_context=%s into app.json (%d expo plugins, %d ios keys)",
                        _rc, len(_wire.expo_plugins), len(_wire.permissions_ios),
                    )
    except Exception as _rc_exc:  # noqa: BLE001
        logger.warning("[mobile_scaffold] runtime_context merge skipped: %s", _rc_exc)

    # Placeholder PNG assets. Slice E replaces these with brand-derived icons.
    assets_dir = mobile_dir / "assets"
    _write_solid_png(assets_dir / "icon.png",           1024, 1024, resolved_brand)
    _write_solid_png(assets_dir / "adaptive-icon.png",  1024, 1024, resolved_brand)
    _write_solid_png(assets_dir / "splash.png",         1242, 2436, resolved_brand)
    _write_solid_png(assets_dir / "favicon.png",          48,   48, resolved_brand)
    for name in ("icon.png", "adaptive-icon.png", "splash.png", "favicon.png"):
        files_written.append(f"assets/{name}")

    logger.info(
        "[mobile_scaffold] wrote %d files to %s (app_name=%r, brand=%s, url=%r)",
        len(files_written), mobile_dir, resolved_name, resolved_brand, resolved_url,
    )
    return {
        "mobile_dir": str(mobile_dir),
        "files_written": files_written,
        "app_name": resolved_name,
        "slug": slug,
        "bundle_id": resolved_bundle,
        "brand_hex": resolved_brand,
        "deployed_url": resolved_url,
        "eas_project_id": prior_eas_id,
    }


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _read_plan_dict(out: Path) -> dict:
    """Load contracts/plan.json as a dict; empty dict on any failure.
    Used by the IRF-M3-T9 runtime_context merge above."""
    plan_path = out / "contracts" / "plan.json"
    try:
        if plan_path.is_file():
            data = json.loads(plan_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        pass
    return {}


def _infer_app_description(out: Path) -> str:
    """Read the plan's description so MOBILE-E can craft a real store
    listing instead of the generic fallback. Kept separate from
    ``_infer_app_name`` because the fallback for a missing description
    is an empty string (the branding module handles the fallback copy)."""
    plan_path = out / "contracts" / "plan.json"
    try:
        if plan_path.is_file():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            v = plan.get("description")
            if isinstance(v, str) and v.strip():
                return v.strip()
    except Exception:
        pass
    return ""


def _infer_app_name(out: Path) -> str:
    """Prefer the human name from the plan; fall back to folder name."""
    plan_path = out / "contracts" / "plan.json"
    try:
        if plan_path.is_file():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            for key in ("name", "app_name", "module_name"):
                v = plan.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    except Exception:
        pass
    return out.name


def _infer_brand_hex(out: Path) -> str:
    """Extract the primary brand color from design_spec.json.

    Looks for ``colorPalette.primary`` first, then falls back to
    ``theme.primary``, then to the default. Accepts either ``#rrggbb``
    or a raw ``rrggbb`` string, or an ``hsl(...)`` value we convert.
    """
    spec_path = out / "design_spec.json"
    try:
        if spec_path.is_file():
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            candidates = [
                (spec.get("colorPalette") or {}).get("primary"),
                (spec.get("theme") or {}).get("primary"),
                spec.get("primaryColor"),
            ]
            for c in candidates:
                hex_ = _normalize_hex(c)
                if hex_:
                    return hex_
    except Exception:
        pass
    return _DEFAULT_BRAND_HEX


def _normalize_hex(value: Any) -> str:
    """Coerce a colour value to ``#rrggbb`` uppercase. Returns default
    on anything unparseable."""
    if not isinstance(value, str):
        return _DEFAULT_BRAND_HEX
    v = value.strip()
    if not v:
        return _DEFAULT_BRAND_HEX
    m = re.match(r"^#?([0-9A-Fa-f]{6})$", v)
    if m:
        return "#" + m.group(1).upper()
    m3 = re.match(r"^#?([0-9A-Fa-f]{3})$", v)
    if m3:
        r, g, b = m3.group(1)
        return f"#{r}{r}{g}{g}{b}{b}".upper()
    return _DEFAULT_BRAND_HEX


def _slugify(name: str) -> str:
    """Turn 'Planters Nursery Management' → 'planters-nursery-management'.
    Restricted to lowercase kebab so it's safe as an Expo slug + Android
    package suffix."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s or "app"


def _read_prior_eas_project_id(app_json_path: Path) -> Optional[str]:
    """If the user has already run `eas init` and captured a project
    id in app.json, keep it across re-scaffolds."""
    try:
        if not app_json_path.is_file():
            return None
        data = json.loads(app_json_path.read_text(encoding="utf-8"))
        expo = data.get("expo") or {}
        extra = expo.get("extra") or {}
        eas = extra.get("eas") or {}
        pid = eas.get("projectId")
        if isinstance(pid, str) and pid and pid != _EAS_PROJECT_ID_PLACEHOLDER:
            return pid
    except Exception:
        pass
    return None


def _write_solid_png(path: Path, width: int, height: int, hex_color: str) -> None:
    """Write a minimal solid-color PNG. No PIL dependency — we synthesize
    the byte stream directly so the scaffolder runs on any Python.

    Uses PNG type 2 (RGB, 8-bit) with zlib-compressed IDAT. Small file
    (a few hundred bytes for 1024x1024) because zlib compresses uniform
    rows to almost nothing.
    """
    r, g, b = _hex_to_rgb(hex_color)
    # Each scanline is preceded by a filter byte (0 = None).
    row = bytes([0]) + bytes([r, g, b]) * width
    raw = row * height
    compressed = zlib.compress(raw, level=9)

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = signature + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")
    path.write_bytes(png)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
