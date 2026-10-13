"""The native app's project: an Expo (React Native) app beside the web one.

`<output_dir>/native/` is written from two halves.

* The FIXED half is `templates/native` — the Expo project, the cookie-session
  SDK and the component kit, identical for every application. It is copied
  with the application's name, bundle id and brand colour put in.
* The GENERATED half is this application, said in TypeScript the fixed half
  imports (its README is the contract): the typed `schema`, `workflows`,
  `pages` and `widgets` — the SAME modules the web's `app_sdk` emits, so a
  workflow input the web form collects is one the native form must collect —
  plus the design tokens, the application's config, and one screen per page
  with the route file that serves it.

Deterministic and idempotent: the same Blueprint writes the same bytes, and a
screen whose page is gone is removed. Written only when `mobile.native.enabled`.
The WebView shell (`services.mobile_scaffold`, `mobile/`) is a different
thing in a different folder and is not touched.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The fixed half.
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "native"

#: Where the project lives, beside the web app (`<output_dir>/app`).
NATIVE_DIR = "native"

#: What the template carries for its own sake and an application does not get.
_NOT_SHIPPED_DIRS = {"_placeholders", "__tests__", "node_modules", ".expo"}
_NOT_SHIPPED_FILES = {"run-native-tests.sh"}

#: Files with `__NAME__` placeholders (the same names `templates/mobile` uses).
_SUBSTITUTED = {"app.json", "package.json", "README.md"}

#: Files the fixed half owns at the top of `app/`: a Blueprint page whose route
#: lands on one is not drawn natively — the sign-in is the SDK's, and a
#: generated route must never overwrite them.
FIXED_ROUTES = frozenset({"login", "organisation", "_layout", "+not-found"})

#: What the projector wrote for the pages, so a page that goes takes its files.
MANIFEST = ".forge-generated.json"

_HEADER = ("// Generated from the Living Blueprint — the native app's own half. Edit the\n"
           "// Blueprint, not this file.\n")


def enabled(doc: dict) -> bool:
    mobile = doc.get("mobile") if isinstance(doc.get("mobile"), dict) else {}
    native = mobile.get("native") if isinstance(mobile.get("native"), dict) else {}
    return native.get("enabled") is True


def native_root(output_dir: str | Path) -> Path:
    return Path(output_dir) / NATIVE_DIR


def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def slug(doc: dict) -> str:
    name = str((doc.get("application") or {}).get("name") or "app")
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "app"


def bundle_id(doc: dict) -> str:
    """The id the stores know: the owner's (`mobile.store.bundleId`), else one
    made from the name."""
    store = ((doc.get("mobile") or {}).get("store") or {}) if isinstance(doc.get("mobile"), dict) else {}
    said = str(store.get("bundleId") or "").strip()
    return said or f"com.tentoro.{slug(doc).replace('-', '')}"


def brand_hex(doc: dict) -> str:
    from services.blueprint.projection import mobile_policy
    return str(mobile_policy(doc).get("themeColor") or "#4F46E5").upper()


# ---------------------------------------------------------------------------
# Writing, only when it changed
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def _copy(src: Path, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dst.read_bytes() == src.read_bytes():
            return False
    except OSError:
        pass
    shutil.copyfile(src, dst)
    return True


def _prior_eas_id(app_json: Path) -> str:
    try:
        return str((((json.loads(app_json.read_text("utf-8")).get("expo") or {}).get("extra") or {}).get("eas") or {})
                   .get("projectId") or "")
    except (OSError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# The fixed half
# ---------------------------------------------------------------------------

def project_fixed_half(doc: dict, output_dir: str | Path) -> list[str]:
    """Copy `templates/native` into `<output_dir>/native`, putting this
    application's name, slug, bundle id and brand colour into the files that
    carry placeholders. An `eas init` project id already in `app.json` is kept."""
    root = native_root(output_dir)
    name = str((doc.get("application") or {}).get("name") or "App")
    prior = _prior_eas_id(root / "app.json")
    subs = {
        "__APP_NAME__": name, "__APP_SLUG__": slug(doc), "__BUNDLE_ID__": bundle_id(doc),
        "__BRAND_COLOR__": brand_hex(doc),
        # Where the web app is is known when it is published; the build is handed it then
        # (`EXPO_PUBLIC_APP_URL`), and a person running it locally writes a `.env`.
        "__DEPLOYED_URL__": "", "__EAS_PROJECT_ID__": prior,
    }
    written: list[str] = []
    for src in sorted(TEMPLATE_DIR.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(TEMPLATE_DIR)
        if rel.parts[0] in _NOT_SHIPPED_DIRS or rel.name in _NOT_SHIPPED_FILES:
            continue
        dst = root / rel
        if rel.name in _SUBSTITUTED and len(rel.parts) == 1:
            text = src.read_text(encoding="utf-8")
            for placeholder, value in subs.items():
                text = text.replace(placeholder, value)
            changed = _write(dst, text)
        else:
            changed = _copy(src, dst)
        if changed:
            written.append(rel.as_posix())
    return written + _placeholder_icons(doc, root)


def _placeholder_icons(doc: dict, root: Path) -> list[str]:
    """The icon, adaptive icon, splash and favicon `app.json` names: solid
    brand-colour PNGs, so the project builds before anyone draws a mark. Never
    over a file that is there — a person's own icon, or the monogram
    `mobile_branding` made, stays."""
    from services.mobile_scaffold import _write_solid_png
    brand = brand_hex(doc)
    written = []
    for name, w, h in (("icon.png", 1024, 1024), ("adaptive-icon.png", 1024, 1024),
                       ("splash.png", 1242, 2436), ("favicon.png", 48, 48)):
        path = root / "assets" / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_solid_png(path, w, h, brand)
            written.append(f"assets/{name}")
    return written


# ---------------------------------------------------------------------------
# The generated half: modules the fixed half imports
# ---------------------------------------------------------------------------

def _ts(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def theme_module(doc: dict) -> str:
    """`src/theme.generated.ts`: the design tokens the web app projects
    (`project_design_tokens`), by camelCase name, as the HSL triplets the web
    gives its CSS. Read back from what that projection writes, so the two apps
    cannot disagree about a colour."""
    import tempfile
    from services.blueprint.projection import project_design_tokens

    colors: dict[str, str] = {}
    radius = 8.0
    with tempfile.TemporaryDirectory() as tmp:
        project_design_tokens(doc, tmp)
        css = next(iter(Path(tmp).rglob("tokens.css")), None)
        text = css.read_text(encoding="utf-8") if css else ""
    for name, value in re.findall(r"^\s*--([a-z0-9-]+):\s*([^;]+);", text, re.M):
        value = value.strip()
        if name == "radius":
            m = re.fullmatch(r"([0-9.]+)(rem|px)", value)
            if m:
                radius = float(m.group(1)) * (16 if m.group(2) == "rem" else 1)
            continue
        if name.startswith(("chart-", "font-", "radius-", "spacing-", "shadow-")):
            continue
        # A token the fixed half reads is a colour: an HSL triplet or a hex.
        if re.fullmatch(r"[0-9.]+\s+[0-9.]+%\s+[0-9.]+%", value) or re.fullmatch(r"#[0-9a-fA-F]{3,8}", value):
            camel = re.sub(r"-([a-z0-9])", lambda m: m.group(1).upper(), name)
            colors[camel] = value
    return (_HEADER + "\n" + "export const colors: Record<string, string> = " + _ts(colors) + ";\n\n"
            + f"export const radius: number = {round(radius, 2):g};\n\n"
            + "export const fonts: { body?: string; heading?: string } = {};\n")


def config_module(doc: dict) -> str:
    """`src/config.generated.ts`: what the Blueprint says about the application
    that the fixed half needs (see the template's README)."""
    from services.blueprint.account_model import account_entity, account_fields, home_route
    from services.blueprint.languages import base, languages
    from services.blueprint.languages import _rtl as _rtl_tags
    from services.blueprint.projection import access_map, currency_of, is_location_field

    tags = languages(doc)
    rows = [{"tag": t, "dir": "rtl" if base(t) in _rtl_tags() else "ltr"} for t in tags]
    ent = account_entity(doc)
    location = next((f.get("name") for f in (ent or {}).get("fields") or [] if is_location_field(f)), None)
    account = None if ent is None else {"entity": ent.get("name"), "fields": account_fields(doc),
                                        "labelField": ent.get("labelField"), "locationField": location}
    public = access_map(doc)["public"]
    return (_HEADER + "\n"
            + f"export const APP_NAME: string = {json.dumps(str((doc.get('application') or {}).get('name') or 'App'), ensure_ascii=False)};\n"
            + f"export const CURRENCY: string = {json.dumps(currency_of(doc))};\n"
            + f"export const LOCALE: string = {json.dumps(tags[0])};\n"
            + f"export const LANGUAGES: readonly {{ tag: string; dir: \"ltr\" | \"rtl\" }}[] = {_ts(rows)};\n"
            + f"export const PRIMARY: string = {json.dumps(tags[0])};\n"
            + f"export const HOME: string = {json.dumps(home_route(doc))};\n"
            + f"export const PUBLIC_ROUTES: readonly string[] = {_ts(public)};\n"
            + "export const ACCOUNT: null | {\n  entity: string;\n"
              "  fields: { name: string; label: string; kind: string; required: boolean; options?: { label: string; value: string }[] }[];\n"
              "  labelField: string | null;\n  locationField: string | null;\n} = "
            + _ts(account) + ";\n")


def project_generated_modules(doc: dict, output_dir: str | Path) -> list[str]:
    """The typed SDK modules (the web's own), the tokens and the config."""
    from services.blueprint.app_sdk import SDK_DIR, sdk_files

    root = native_root(output_dir)
    written: list[str] = []
    for rel, content in sdk_files(doc).items():
        stem = Path(rel).name
        # The web's `index.ts` also re-exports its server-side `files` and `picture`; the
        # native SDK's own index re-exports exactly these four.
        if stem == "index.ts":
            continue
        if _write(root / SDK_DIR / stem, content):
            written.append(f"{SDK_DIR}/{stem}")
    for rel, text in (("src/theme.generated.ts", theme_module(doc)), ("src/config.generated.ts", config_module(doc))):
        if _write(root / rel, text):
            written.append(rel)
    return written


# ---------------------------------------------------------------------------
# Screens and their routes
# ---------------------------------------------------------------------------

def route_file(route: str) -> str | None:
    """The expo-router file that serves a Blueprint route, or None when the
    fixed half already owns that path. `/` is `index`, `/orders/[id]` is
    `orders/[id].tsx` — a dynamic segment keeps its brackets."""
    parts = [p for p in str(route or "/").split("/") if p]
    if not parts:
        return "app/index.tsx"
    if parts[0] in FIXED_ROUTES and len(parts) == 1:
        return None
    return "app/" + "/".join(parts) + ".tsx"


def screen_path(page_id: str) -> str:
    return f"src/screens/{page_id}.tsx"


def drawn_pages(doc: dict) -> list[dict]:
    """The pages that get a native screen: the ones the web writes code for,
    without the sign-in and sign-up pages — signing in is the SDK's."""
    from services.blueprint.orchestrator import native_page_subjects
    wanted = set(native_page_subjects(doc))
    return [p for p in _live(doc.get("pages")) if str(p.get("id")) in wanted]


def project_screens(doc: dict, output_dir: str | Path) -> list[str]:
    """One `src/screens/<PAGE-ID>.tsx` (and its parts) for each `nativeCode`
    row, and the `app/<route>.tsx` that serves it. A page with no row has no
    route yet: the check that every page has a screen says which. Files the
    last projection wrote for a page that is gone are removed."""
    root = native_root(output_dir)
    pages = {str(p.get("id")): p for p in drawn_pages(doc)}
    written: list[str] = []
    expected: set[str] = set()
    for row in _live(doc.get("nativeCode")):
        pid = str(row.get("page") or "")
        page = pages.get(pid)
        if page is None or not row.get("screen"):
            continue
        files = {screen_path(pid): str(row["screen"])}
        for key, code in (row.get("parts") or {}).items():
            files[f"src/screens/{pid}/{key}.tsx"] = str(code)
        target = route_file(str(page.get("route") or "/"))
        if target:
            files[target] = f'export {{ default }} from "@/screens/{pid}";\n'
        for rel, text in files.items():
            expected.add(rel)
            if _write(root / rel, text if text.endswith("\n") else text + "\n"):
                written.append(rel)
    # A page that is gone takes its screen and its route with it.
    manifest = root / MANIFEST
    try:
        before = set(json.loads(manifest.read_text("utf-8")))
    except (OSError, ValueError):
        before = set()
    for rel in sorted(before - expected):
        stale = root / rel
        if stale.is_file():
            stale.unlink()
            written.append(f"-{rel}")
    if expected != before:
        _write(manifest, json.dumps(sorted(expected), indent=2) + "\n")
    return written


def project_native(doc: dict, output_dir: str | Path) -> dict[str, Any]:
    """Everything, in order: the fixed half, the generated modules, the screens."""
    if not enabled(doc):
        return {"files": [], "enabled": False}
    files = (project_fixed_half(doc, output_dir)
             + project_generated_modules(doc, output_dir)
             + project_screens(doc, output_dir))
    return {"files": files, "enabled": True, "dir": NATIVE_DIR}


def ensure_native_project(doc: dict, output_dir: str | Path) -> Path:
    """What the native engineer compiles a screen against: the fixed half and
    the modules generated from `doc`, written if they are not there (screens
    are its to write). Returns the project's folder."""
    project_fixed_half(doc, output_dir)
    project_generated_modules(doc, output_dir)
    return native_root(output_dir)
