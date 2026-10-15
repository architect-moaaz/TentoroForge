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
import os
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

#: The tab bar's layout is shipped only when the application HAS tabs (an empty route group is a
#: navigator with nothing in it); `project_screens` writes it with them.
TABS_LAYOUT = "app/(tabs)/_layout.tsx"
MORE_TAB = "app/(tabs)/more.tsx"
#: A drawer app has no tab group: its Account screen is an ordinary route (the same screen the account tab is).
ACCOUNT_ROUTE = "app/account.tsx"

#: The last tab of an app with a sign-in: who is signed in, and SIGN OUT. Written with the tabs, like the layout.
ACCOUNT_TAB = "app/(tabs)/account.tsx"
ACCOUNT_ICON = "person-circle-outline"

#: "/" forwards to where a signed-in person lands, when no page of the application is at "/".
ROOT_REDIRECT = "app/index.tsx"
ROOT_REDIRECT_SOURCE = (
    "// Generated from the Living Blueprint. The application has no page at \"/\": the root forwards to\n"
    "// where a signed-in person lands (the sign-in gate sends everyone else to /login).\n"
    "import { Redirect, type Href } from \"expo-router\";\n"
    "import { HOME } from \"@/config.generated\";\n\n"
    "export default function Index() {\n"
    "  return <Redirect href={HOME as Href} />;\n"
    "}\n")

#: Patterns that are not destinations: a form is an action reached from a list, a record is one thing
#: opened from a list. They stack above the tabs.
_NOT_A_TAB = ("form", "record_workspace", "auth", "audit_trail")

#: At most this many tabs (the platforms' own limit of comfort is five).
MAX_TABS = 5

#: Ionicons glyphs. A tab's icon is, in order: what the Blueprint's navigation calls it (a lucide name), a word
#: in the page's own name ("Invoices" is a receipt, "Pets" a paw), the page's pattern, else a plain grid. Two tabs
#: never share one: a bar of identical lists is a bar nobody can read.
_ICON_BY_NAME = {
    "Wrench": "construct", "Hammer": "hammer", "BarChart3": "stats-chart", "BarChart": "bar-chart", "LineChart": "trending-up",
    "PieChart": "pie-chart", "BookOpen": "book", "Book": "book", "Home": "home", "LayoutDashboard": "grid", "Users": "people",
    "User": "person", "UserRound": "person", "Settings": "settings", "Calendar": "calendar", "CalendarDays": "calendar",
    "ShoppingCart": "cart", "ShoppingBag": "bag", "Package": "cube", "Box": "cube", "Bell": "notifications", "Mail": "mail",
    "Map": "map", "MapPin": "location", "PawPrint": "paw", "Receipt": "receipt", "FileText": "document-text", "File": "document",
    "Folder": "folder", "ClipboardList": "clipboard", "CheckSquare": "checkbox", "ListChecks": "checkbox",
    "MessageSquare": "chatbubbles", "MessageCircle": "chatbubbles", "Heart": "heart", "HeartPulse": "pulse",
    "Stethoscope": "medkit", "Pill": "medkit", "CreditCard": "card", "Wallet": "wallet", "DollarSign": "cash",
    "Banknote": "cash", "Tag": "pricetag", "Tags": "pricetags", "Truck": "car", "Car": "car", "Plane": "airplane",
    "Utensils": "restaurant", "ChefHat": "restaurant", "GraduationCap": "school", "Briefcase": "briefcase",
    "Building": "business", "Store": "storefront", "Camera": "camera", "Image": "image", "Music": "musical-notes",
    "Dumbbell": "fitness", "Leaf": "leaf", "Bed": "bed", "Star": "star", "Bookmark": "bookmark", "Trophy": "trophy",
    "Ticket": "ticket", "Gift": "gift", "Shield": "shield-checkmark", "Search": "search", "Clock": "time",
    "Activity": "pulse", "Layers": "layers",
}
#: A word in a page's name -> a glyph, for a navigation that names no icon (or one this table does not know).
_ICON_BY_WORD = (
    ("pet", "paw"), ("paw", "paw"), ("invoice", "receipt"), ("bill", "receipt"), ("receipt", "receipt"),
    ("payment", "card"), ("order", "cart"), ("cart", "cart"), ("product", "pricetag"), ("customer", "people"),
    ("client", "people"), ("owner", "people"), ("patient", "medkit"), ("appointment", "calendar"),
    ("booking", "calendar"), ("schedule", "calendar"), ("calendar", "calendar"), ("event", "calendar"),
    ("message", "chatbubbles"), ("chat", "chatbubbles"), ("report", "bar-chart"), ("analytic", "analytics"),
    ("dashboard", "home"), ("home", "home"), ("setting", "settings"), ("task", "checkbox"), ("todo", "checkbox"),
    ("project", "folder"), ("document", "document-text"), ("inventory", "cube"), ("stock", "cube"),
    ("job", "construct"), ("crew", "people"), ("team", "people"), ("member", "people"), ("staff", "people"),
    ("ticket", "ticket"), ("course", "school"), ("lesson", "school"), ("recipe", "restaurant"),
    ("menu", "restaurant"), ("expense", "cash"), ("budget", "wallet"), ("map", "map"), ("location", "location"),
    ("notification", "notifications"), ("review", "star"), ("favourite", "heart"), ("favorite", "heart"),
    ("workout", "fitness"), ("vehicle", "car"), ("delivery", "car"), ("board", "albums"),
)
_ICON_BY_PATTERN = {"entity_list": "list", "dashboard": "stats-chart", "calendar": "calendar", "board": "albums",
                    "report": "bar-chart", "settings": "settings", "feed": "newspaper"}
#: What a tab takes when everything it would prefer is already on the bar.
_ICON_SPARE = ("apps", "grid", "layers", "folder", "albums", "ellipse")


def tab_icons(items: list[tuple[str | None, str, str]]) -> list[str]:
    """One distinct Ionicons glyph for each `(navigation icon, page name, pattern)`, in order."""
    used: set[str] = set()
    out: list[str] = []
    for nav_icon, name, pattern in items:
        words = re.sub(r"[^a-z ]", " ", str(name or "").lower())
        candidates = [_ICON_BY_NAME.get(str(nav_icon or ""))]
        candidates += [glyph for word, glyph in _ICON_BY_WORD if word in words]
        candidates += [_ICON_BY_PATTERN.get(str(pattern or ""))]
        candidates += list(_ICON_SPARE)
        pick = next(c for c in candidates if c and c not in used)
        used.add(pick)
        out.append(pick)
    return out

#: Files the fixed half owns at the top of `app/`: a Blueprint page whose route
#: lands on one is not drawn natively — the sign-in is the SDK's, and a
#: generated route must never overwrite them.
FIXED_ROUTES = frozenset({"login", "signup", "organisation", "_layout", "+not-found"})

#: The sign-in and sign-up screens: the fixed half ships a fallback at each, and the Blueprint's own page (drawn by
#: the native engineer as a frame around the kit's `SignInForm` / `SignUpForm`) replaces it when there is one.
AUTH_FILES = {"/login": "app/login.tsx", "/signup": "app/signup.tsx"}

#: What the projector wrote for the pages, so a page that goes takes its files.
MANIFEST = ".forge-generated.json"

_HEADER = ("// Generated from the Living Blueprint — the native app's own half. Edit the\n"
           "// Blueprint, not this file.\n")


#: Turns the native app on for every application that does not say otherwise:
#: `FORGE_NATIVE_APP=1`. The Blueprint's own `mobile.native.enabled` — set by the
#: owner, or by Smith — wins over it either way, so one application can opt out
#: of a platform that defaults to native, or in on one that does not.
NATIVE_ENV = "FORGE_NATIVE_APP"


def enabled(doc: dict) -> bool:
    mobile = doc.get("mobile") if isinstance(doc.get("mobile"), dict) else {}
    native = mobile.get("native") if isinstance(mobile.get("native"), dict) else {}
    if isinstance(native.get("enabled"), bool):
        return native["enabled"]
    return os.environ.get(NATIVE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


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
    drawn_auth = drawn_auth_files(doc)
    for src in sorted(TEMPLATE_DIR.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(TEMPLATE_DIR)
        if rel.parts[0] in _NOT_SHIPPED_DIRS or rel.name in _NOT_SHIPPED_FILES:
            continue
        if rel.as_posix() in (TABS_LAYOUT, ACCOUNT_TAB, MORE_TAB):
            continue                        # written with the tabs, by `project_screens`
        if rel.as_posix() in drawn_auth:
            continue                        # the Blueprint's own page is drawn: `project_screens` writes this one
        dst = root / rel
        if rel.name in _SUBSTITUTED and len(rel.parts) == 1:
            text = src.read_text(encoding="utf-8")
            for placeholder, value in subs.items():
                text = text.replace(placeholder, value)
            if rel.name == "package.json":
                text = _with_font_packages(text, doc)
            changed = _write(dst, text)
        else:
            changed = _copy(src, dst)
        if changed:
            written.append(rel.as_posix())
    return written + _placeholder_icons(doc, root)


def _with_font_packages(package_json: str, doc: dict) -> str:
    """The app's `package.json` with the `@expo-google-fonts/*` packages its typefaces are made of."""
    from services.blueprint.native_fonts import packages

    extra = packages(doc)
    if not extra:
        return package_json
    data = json.loads(package_json)
    deps = data.setdefault("dependencies", {})
    for name, version in extra.items():
        deps.setdefault(name, version)
    data["dependencies"] = dict(sorted(deps.items()))
    return json.dumps(data, indent=2) + "\n"


def _placeholder_icons(doc: dict, root: Path) -> list[str]:
    """The icon, adaptive icon, splash and favicon `app.json` names. WITH NO LOGO FROM THE OWNER the mark is the
    first letter of the app's name on the design's primary colour (the same tile the sign-in screen draws);
    the splash carries the name. Never over a file that is there: an owner's own logo stays."""
    from services import mobile_branding as mb
    from services.mobile_scaffold import _write_solid_png

    name = str((doc.get("application") or {}).get("name") or "App")
    primary = str(((doc.get("designSystem") or {}).get("colors") or {}).get("primary") or "")
    brand = (primary if re.fullmatch(r"#[0-9a-fA-F]{6}", primary) else brand_hex(doc)).upper()
    letter = next((c for c in name if c.isalpha()), "A").upper()
    tile, splash = mb.MobileSpec(name=letter, slug="app", brand_hex=brand), mb.MobileSpec(name=name, slug="app", brand_hex=brand)
    written = []
    for file, w, h, kind in (("icon.png", 1024, 1024, "icon"), ("adaptive-icon.png", 1024, 1024, "adaptive"),
                             ("splash.png", 1242, 2436, "splash"), ("favicon.png", 48, 48, "icon")):
        path = root / "assets" / file
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            mb._write_asset(path, (w, h), kind, splash if kind == "splash" else tile)
        except Exception:  # noqa: BLE001  - no imaging library: a solid colour still builds
            _write_solid_png(path, w, h, brand)
        written.append(f"assets/{file}")
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

    from services.blueprint.native_fonts import theme_fonts

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
    from services.blueprint import native_tokens as tk

    return (_HEADER + "\n" + "export const colors: Record<string, string> = " + _ts(colors) + ";\n\n"
            + f"export const radius: number = {tk.radii(doc)['md']};\n\n"
            # THE MEASURES ARE THE DESIGN'S (`native_tokens`): corner radii, the spacing scale and page margin,
            # three shadows, the type scale, the hairline. The kit draws from these and from nothing else.
            + "export const radii = " + _ts(tk.radii(doc)) + " as const;\n\n"
            + "export const spacing = " + _ts(tk.spacing(doc)) + " as const;\n\n"
            + f"export const pagePadding: number = {tk.page_padding(doc)};\n\n"
            + "export const shadows = " + _ts(tk.shadows(doc)) + ";\n\n"
            + f"export const typeScale: number = {tk.type_scale(doc)};\n\n"
            + f"export const borderWidth: number = {tk.border_width(doc)};\n\n"
            + "export const heading = " + _ts(tk.heading(doc)) + " as const;\n\n"
            + "export const fonts: {\n"
              "  body?: { regular: string; medium?: string; semibold?: string; bold?: string };\n"
              "  heading?: { regular: string; medium?: string; semibold?: string; bold?: string };\n"
              "} = " + _ts(theme_fonts(doc)) + ";\n")


def can_sign_up(doc: dict) -> bool:
    """Whether the phone can create an account: the application has a sign-up page and people hold passwords
    (the phone signs in with email and password; single sign-on and email links need a browser)."""
    from services.blueprint.account_model import is_auth_page, passwords_on
    if not passwords_on(doc):
        return False
    return any(is_auth_page(p) and re.search(r"sign.?up|regist|join|create.?account", f"{p.get('route')} {p.get('name')}", re.I)
               for p in _live(doc.get("pages")))


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
    from services.blueprint.account_model import after_signup_route
    home = phone_route(doc, home_route(doc))
    after_signup = phone_route(doc, after_signup_route(doc))
    return (_HEADER + "\n"
            + f"export const APP_NAME: string = {json.dumps(str((doc.get('application') or {}).get('name') or 'App'), ensure_ascii=False)};\n"
            + f"export const CURRENCY: string = {json.dumps(currency_of(doc))};\n"
            + f"export const LOCALE: string = {json.dumps(tags[0])};\n"
            + f"export const LANGUAGES: readonly {{ tag: string; dir: \"ltr\" | \"rtl\" }}[] = {_ts(rows)};\n"
            + f"export const PRIMARY: string = {json.dumps(tags[0])};\n"
            + f"export const HOME: string = {json.dumps(home)};\n"
            + f"export const CAN_SIGN_UP: boolean = {json.dumps(can_sign_up(doc))};\n"
            + f"export const AFTER_SIGNUP: string = {json.dumps(after_signup)};\n"
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
    from services.blueprint.native_fonts import fonts_module

    for rel, text in (("src/theme.generated.ts", theme_module(doc)), ("src/config.generated.ts", config_module(doc)),
                      ("src/navigation.generated.ts", navigation_module(doc)),
                      ("src/fonts.generated.ts", fonts_module(doc))):
        if _write(root / rel, text):
            written.append(rel)
    return written


# ---------------------------------------------------------------------------
# Screens and their routes
# ---------------------------------------------------------------------------

def _nav_items(nodes: Any) -> list[dict]:
    out: list[dict] = []
    for node in nodes or []:
        if isinstance(node, dict):
            out.append(node)
            out.extend(_nav_items(node.get("children")))
    return out


def has_account_tab(doc: dict) -> bool:
    """Whether the tab bar ends with the account tab: the application has a sign-in (so a person needs a way
    OUT of it), and no page of its own is at `/account`."""
    from services.blueprint.account_model import has_sign_in
    return has_sign_in(doc) and not any(str(p.get("route") or "").strip("/") == "account" for p in drawn_pages(doc))


def main_pages(doc: dict) -> list[dict]:
    """The application's MAIN pages: the pages its navigation lists (the rail the web app shows), in that
    order, that are destinations — not a form, not one record, nothing with a parameter in its route — and
    that get a native screen."""
    drawn = {str(p.get("id")): p for p in drawn_pages(doc)}
    out: list[dict] = []
    seen: set[str] = set()
    for item in _nav_items((doc.get("navigation") or {}).get("tree")):
        pid = str(item.get("page") or "")
        page = drawn.get(pid)
        if page is None or pid in seen:
            continue
        route = str(page.get("route") or "/")
        if "[" in route or str(page.get("pattern") or "") in _NOT_A_TAB or route_file(route, tab=True) is None:
            continue
        seen.add(pid)
        out.append({**page, "_icon": item.get("icon"), "_label": item.get("label")})
    return out


def nav_style(doc: dict) -> str:
    """`tabs` (a bottom bar) or `drawer` (a hamburger menu): how this application's phone navigates.

    The Blueprint's `navigation.mobile` - the navigation agent's own decision, which the web follows too - when
    it says. When it does not, a handful of main pages (four, with the account tab) is a bar and more is a menu:
    the same number the bar can hold."""
    said = str(((doc.get("navigation") or {}).get("mobile")) or "")
    if said in ("tabs", "drawer"):
        return said
    return "tabs" if len(main_pages(doc)) <= (MAX_TABS - 1 if has_account_tab(doc) else MAX_TABS) else "drawer"


def tab_layout(doc: dict) -> tuple[list[dict], list[dict]]:
    """`(tabs, more)`: the main pages that get a tab, and the ones that go behind the More tab.

    A bar holds MAX_TABS (the account tab is one of them). With the account tab one main page is a bar (two
    tabs); without it two are needed. When the main pages do not all fit, the first ones get a tab and the
    rest are LISTED on a More tab, which takes the last slot before Account: a long application is not left
    with no bar (and no way to reach its pages), nor with a bar too crowded to tap."""
    out = main_pages(doc)
    account = has_account_tab(doc)
    capacity = MAX_TABS - 1 if account else MAX_TABS
    if nav_style(doc) == "drawer" or len(out) < (1 if account else 2):
        return [], []
    if len(out) <= capacity:
        return out, []
    return out[:capacity - 1], out[capacity - 1:]


def tab_pages(doc: dict) -> list[dict]:
    """The pages that have a tab of their own."""
    return tab_layout(doc)[0]


def more_pages(doc: dict) -> list[dict]:
    """The main pages listed on the More tab; they open on top of the bar like any other page."""
    return tab_layout(doc)[1]


def is_tab(doc: dict, page_id: str) -> bool:
    return any(str(p.get("id")) == page_id for p in tab_pages(doc))


def is_menu_page(doc: dict, page_id: str) -> bool:
    """A main page of a drawer app: it is in the hamburger menu, so its header draws the hamburger, not a back arrow."""
    return nav_style(doc) == "drawer" and any(str(p.get("id")) == page_id for p in main_pages(doc))


def navigation_module(doc: dict) -> str:
    """`src/navigation.generated.ts`: the tabs, in order."""
    tabs = []
    pages_in_bar, listed = tab_layout(doc)
    shown = pages_in_bar + listed
    icons = tab_icons([(p.get("_icon"), str(p.get("_label") or p.get("name") or ""), str(p.get("pattern") or "")) for p in shown])
    for p, icon in zip(pages_in_bar, icons):
        route = str(p.get("route") or "/")
        name = (route.strip("/").split("/")[-1] or "index")
        tabs.append({"name": name, "title": str(p.get("_label") or p.get("name") or name), "icon": icon, "route": route})
    more = [{"title": str(p.get("_label") or p.get("name") or ""), "icon": icon, "route": str(p.get("route") or "/")}
            for p, icon in zip(listed, icons[len(pages_in_bar):])]
    if more:
        tabs.append({"name": "more", "title": "More", "icon": "ellipsis-horizontal", "route": "/more"})
    if pages_in_bar and has_account_tab(doc):
        tabs.append({"name": "account", "title": "Account", "icon": ACCOUNT_ICON, "route": "/account"})
    # The drawer's menu: every main page, in the navigation's order, then Account.
    menu: list[dict] = []
    if nav_style(doc) == "drawer":
        mains = main_pages(doc)
        menu = [{"title": str(p.get("_label") or p.get("name") or ""), "icon": icon, "route": str(p.get("route") or "/")}
                for p, icon in zip(mains, tab_icons([(p.get("_icon"), str(p.get("_label") or p.get("name") or ""),
                                                      str(p.get("pattern") or "")) for p in mains]))]
        if has_account_tab(doc):
            menu.append({"title": "Account", "icon": ACCOUNT_ICON, "route": "/account"})
    return (_HEADER + "\n"
            + "export const TABS: readonly { name: string; title: string; icon: string; route: string }[] = "
            + _ts(tabs) + ";\n\n"
            + "/** The main pages that do not fit the bar, listed on the More tab. */\n"
            + "export const MORE: readonly { title: string; icon: string; route: string }[] = " + _ts(more) + ";\n\n"
            + "/** How a phone navigates: a bottom bar of tabs, or a hamburger menu. */\n"
            + f"export const NAV_STYLE: \"tabs\" | \"drawer\" = {json.dumps(nav_style(doc))};\n\n"
            + "/** The drawer's menu: every main page, then Account. Empty for a tab app. */\n"
            + "export const MENU: readonly { title: string; icon: string; route: string }[] = " + _ts(menu) + ";\n")


def route_file(route: str, *, tab: bool = False) -> str | None:
    """The expo-router file that serves a Blueprint route, or None when the
    fixed half already owns that path. `/` is `index`, `/orders/[id]` is
    `orders/[id].tsx` — a dynamic segment keeps its brackets."""
    parts = [p for p in str(route or "/").split("/") if p]
    if not parts:
        return "app/(tabs)/index.tsx" if tab else "app/index.tsx"
    if parts[0] in FIXED_ROUTES and len(parts) == 1:
        return None
    # A tab lives in the `(tabs)` group, which is not part of the address: `/jobs` is still `/jobs`.
    return ("app/(tabs)/" if tab else "app/") + "/".join(parts) + ".tsx"


def screen_path(page_id: str) -> str:
    return f"src/screens/{page_id}.tsx"


def drawn_pages(doc: dict) -> list[dict]:
    """The pages that get a native screen: the ones the web writes code for,
    without the sign-in and sign-up pages — signing in is the SDK's."""
    from services.blueprint.orchestrator import native_page_subjects
    wanted = set(native_page_subjects(doc))
    return [p for p in _live(doc.get("pages")) if str(p.get("id")) in wanted]


def auth_file(page: dict) -> str | None:
    """The fixed sign-in / sign-up file a page of the Blueprint stands in for, or None."""
    if str(page.get("pattern") or "") != "auth":
        return None
    return AUTH_FILES.get("/" + str(page.get("route") or "").strip("/"))


def screen_gaps(doc: dict) -> list[dict]:
    """THE CHECK: the pages of a native application that have no phone screen of their own.

    A native app has one screen per page. When the writer could not produce one (it did not compile in its
    rounds, it needed a workflow that does not exist, or the run stopped first) the page is simply missing from the
    phone: a tab or a menu entry that led to "This screen does not exist". The sign-in and sign-up pages are not
    gaps: the fixed ones stand in. Empty for an app that is not native."""
    if not enabled(doc):
        return []
    have = {str(r.get("page")) for r in _live(doc.get("nativeCode")) if r.get("screen")}
    return [p for p in drawn_pages(doc) if str(p.get("id")) not in have and not auth_file(p)]


#: What a page with no phone screen opens: its name, a plain sentence, and a way to the web page.
MISSING_SCREEN = (
    'import {{ MissingScreen }} from "@/ui";\n\n'
    "export default function Screen() {{\n"
    "  return <MissingScreen title={title} route={route} />;\n"
    "}}\n")


def phone_route(doc: dict, route: str) -> str:
    """A route the phone can OPEN: "/" only when a page really is "/".

    `app/index.tsx` forwards "/" to `HOME`, so a `HOME` of "/" in an app with no page there sent the root to itself for
    ever: the person saw the loading circle and the log said "Maximum update depth exceeded" (Iron Log, 2026-10-15; every
    app that has no page at "/"). The web has no such loop: it sends "/" to its landing page. The phone does the same."""
    if route != "/":
        return route
    from services.blueprint.projection import landing_route
    if any(str(p.get("route")) == "/" for p in _live(doc.get("pages"))):
        return route
    return landing_route(doc) or route


def drawn_auth_files(doc: dict) -> set[str]:
    """The fixed auth files that a drawn page replaces: the page is a native page and has its screen."""
    rows = {str(r.get("page")) for r in _live(doc.get("nativeCode")) if r.get("screen")}
    return {f for p in drawn_pages(doc) if (f := auth_file(p)) and str(p.get("id")) in rows}


def project_screens(doc: dict, output_dir: str | Path) -> list[str]:
    """One `src/screens/<PAGE-ID>.tsx` (and its parts) for each `nativeCode`
    row, and the `app/<route>.tsx` that serves it. A page with no row has no
    route yet: the check that every page has a screen says which. Files the
    last projection wrote for a page that is gone are removed."""
    root = native_root(output_dir)
    pages = {str(p.get("id")): p for p in drawn_pages(doc)}
    tabs = {str(p.get("id")) for p in tab_pages(doc)}
    written: list[str] = []
    expected: set[str] = set()
    if tabs:
        layout = (TEMPLATE_DIR / TABS_LAYOUT).read_text(encoding="utf-8")
        expected.add(TABS_LAYOUT)
        if _write(root / TABS_LAYOUT, layout):
            written.append(TABS_LAYOUT)
        if has_account_tab(doc):
            expected.add(ACCOUNT_TAB)
            if _write(root / ACCOUNT_TAB, (TEMPLATE_DIR / ACCOUNT_TAB).read_text(encoding="utf-8")):
                written.append(ACCOUNT_TAB)
        if more_pages(doc):
            expected.add(MORE_TAB)
            if _write(root / MORE_TAB, (TEMPLATE_DIR / MORE_TAB).read_text(encoding="utf-8")):
                written.append(MORE_TAB)
    elif nav_style(doc) == "drawer" and main_pages(doc) and has_account_tab(doc):
        # No tab group: the menu lists Account, and its screen is an ordinary route.
        expected.add(ACCOUNT_ROUTE)
        if _write(root / ACCOUNT_ROUTE, (TEMPLATE_DIR / ACCOUNT_TAB).read_text(encoding="utf-8")):
            written.append(ACCOUNT_ROUTE)
    for row in _live(doc.get("nativeCode")):
        pid = str(row.get("page") or "")
        page = pages.get(pid)
        if page is None or not row.get("screen"):
            continue
        files = {screen_path(pid): str(row["screen"])}
        for key, code in (row.get("parts") or {}).items():
            files[f"src/screens/{pid}/{key}.tsx"] = str(code)
        target = auth_file(page) or route_file(str(page.get("route") or "/"), tab=pid in tabs)
        if target:
            files[target] = f'export {{ default }} from "@/screens/{pid}";\n'
        for rel, text in files.items():
            expected.add(rel)
            if _write(root / rel, text if text.endswith("\n") else text + "\n"):
                written.append(rel)
    # A PAGE WITH NO PHONE SCREEN STILL HAS A ROUTE. The tab, the menu entry or the link leads somewhere that says what
    # happened and where the page is, instead of "This screen does not exist". When a screen is written for it later
    # the same file is overwritten with the real one.
    for page in screen_gaps(doc):
        pid = str(page.get("id"))
        target = route_file(str(page.get("route") or "/"), tab=pid in tabs)
        if not target:
            continue
        expected.add(target)
        if _write(root / target, MISSING_SCREEN.format(title=json.dumps(str(page.get("name") or page.get("route") or "This page")),
                                                         route=json.dumps(str(page.get("route") or "/")))):
            written.append(target)
    # "/" IS WHERE THE APP OPENS. Most applications declare no page at "/" (the web's root merely forwards
    # to the entry page), and a native app opened there showed "This screen does not exist". Without a
    # page of its own at "/", it forwards to where a signed-in person lands.
    if not ({"app/index.tsx", "app/(tabs)/index.tsx"} & expected):
        expected.add(ROOT_REDIRECT)
        if _write(root / ROOT_REDIRECT, ROOT_REDIRECT_SOURCE):
            written.append(ROOT_REDIRECT)
    # A page that is gone takes its screen and its route with it.
    manifest = root / MANIFEST
    try:
        before = set(json.loads(manifest.read_text("utf-8")))
    except (OSError, ValueError):
        before = set()
    for rel in sorted(before - expected):
        stale = root / rel
        if rel in AUTH_FILES.values():
            # A drawn sign-in that goes gives the FALLBACK back, never an app with no way in.
            if _write(stale, (TEMPLATE_DIR / rel).read_text(encoding="utf-8")):
                written.append(rel)
        elif stale.is_file():
            stale.unlink()
            written.append(f"-{rel}")
            # a route group or folder left empty (`app/(tabs)` once the app goes to a drawer) goes with its files
            for parent in stale.parents:
                if parent == root or parent.name in ("app", "src") or any(parent.iterdir()):
                    break
                parent.rmdir()
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
