"""Deterministic app-shell builder (SP4).

The LLM shell agent reliably produced ONE structure — a left sidebar — and hardcoded
generic `bg-slate-900` classes, ignoring the generated design tokens. That made every
app read as the same admin template. This module replaces that guesswork with a small
catalog of genuinely-distinct shell FRAMES (sidebar / top-bar / icon-rail), selected
deterministically by the app's information architecture, and styled from the real
design-spec color tokens.

Output is a `shell.json` dict in the renderer's v2 component-tree schema — the same
format the LLM agent produced — so it drops into the existing pipeline and passes the
shell_guardrail (exactly one PageOutlet, registered node types, >=1 nav Button).

TODO(spec-d-w6): Wave 6 of the domain-intelligence cleanup retires this
795-LOC three-shape catalog and bridges shell rendering into Wave 1's
design-agent numeric+string emission (which is meant to produce varied
shell shapes on its own). Retirement prerequisites:

  1. Wave 1 must complete full caller migration first. Only 2/13
     design-authorship callers migrated in commit c46f4e78; the shell
     bridge here is the 3rd caller and must not land until the design
     agent is the authority for shell shape/tokens.
  2. Build a bridge helper (~150 LOC) that reads brief/design-spec
     numeric+string fields (nav width, sidebar depth, header height,
     brand-tile shape, active-nav stripe style, ...) and materializes
     the same shell.json shape this module emits — so the single
     production caller below drops in cleanly.
  3. Migrate the sole non-test caller:
     - backend/agents/shell_layout_agent.py::generate_shell_to_file
       (imports build_shell_deterministic on line 721 as the primary
       shell path; the LLM fallback below it stays).
  4. Only then delete this module. Note: 4 test files
     (test_shell_templates, test_shell_sidenav_width,
     test_structural_identity, test_figma_end_to_end_byte_exact) will
     need equivalent coverage against the new bridge — do NOT drop the
     invariants (exactly-one PageOutlet, registered node types,
     >=1 nav Button, token cleaning, nav-icon selection) in transit.

Do NOT delete this file until Wave 1 completes and steps 1-3 land.
See docs/superpowers/specs/2026-08-07-domain-intelligence-cleanup.md
lines 299-320 for the full Wave 6 plan.
"""
from __future__ import annotations

import re
from typing import Any

# ── tokens ────────────────────────────────────────────────────────────────────

_TOKEN_FALLBACK = {
    "primary": "#2E4A6E",
    "onPrimary": "#FFFFFF",
    "accent": "#C47D0E",
    "sidebarBg": "#1A2940",
    "sidebarText": "#C7D2DE",
    "sidebarMuted": "#7C8BA0",
    # Spec A Slice 4 — active-nav stripe + brand-tile chrome derived
    # from brief.palette accent + brand. Downstream frame builders use
    # these instead of a hardcoded green square / muted stripe.
    "sidebarActive": "#C47D0E",   # defaults to accent
    "brandTile": "#2E4A6E",       # defaults to primary
    "background": "#F1F0ED",
    "surface": "#FFFFFF",
    "border": "#DCDAD5",
    "text": "#1C2536",
    "textMuted": "#546474",
}


# Shared outer gutter. Must match the renderer's PageOutlet `comfortable` padding
# (packages/renderer/src/nodes/shell/PageOutlet.tsx) so the top header/toolbar and
# the page content below it share one consistent left edge at every breakpoint —
# otherwise the header sits at 16px while content indents to 32px on desktop and
# the column looks misaligned against the frame.
_GUTTER_X = "px-4 sm:px-6 lg:px-8"

_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_FUNC_RE = re.compile(r"(?:rgb|hsl)a?\([^)]*\)", re.IGNORECASE)


def _clean_color(v: Any) -> Any:
    """Extract just the CSS color from an LLM-authored palette value.

    The design agent frequently annotates colors, e.g.
    ``"#2E5FA3 — slate-blue for institutional trust"``. Passed straight to CSS
    that whole string is an invalid color, so the component silently falls back
    to its default (a generic blue). Keep only the leading hex / rgb() / hsl() /
    named token and drop the prose."""
    if not isinstance(v, str):
        return v
    s = v.strip()
    m = _HEX_RE.search(s) or _FUNC_RE.search(s)
    if m:
        return m.group(0)
    # Named color (e.g. "teal") or an already-clean value — take the first token,
    # dropping any trailing description separated by whitespace or an em/en-dash.
    return re.split(r"[\s—–]", s, 1)[0] if s else s


def extract_tokens(design_spec: dict | None, brand: dict | None = None) -> dict:
    """Pull the concrete colors the frames paint with, from the design-spec palette
    (falling back to sensible neutrals). Brand colors override when present."""
    cp = ((design_spec or {}).get("colorPalette")
          or (design_spec or {}).get("colors") or {})
    t = dict(_TOKEN_FALLBACK)
    mapping = {
        "primary": ("primary",),
        "accent": ("accent",),
        "sidebarBg": ("sidebarBg",),
        "sidebarText": ("sidebarText",),
        # Spec A Slice 4 — sidebarActive derives from the accent (brief
        # said "active nav uses accent"); brandTile derives from the
        # primary (the sidebar top-left tile IS the brand).
        "sidebarActive": ("sidebarActive", "accent"),
        "brandTile": ("brandTile", "primary"),
        "background": ("background",),
        "surface": ("surface",),
        "border": ("border",),
        "text": ("textPrimary", "text"),
        "textMuted": ("textSecondary", "muted"),
    }
    for key, sources in mapping.items():
        for s in sources:
            v = cp.get(s)
            if isinstance(v, str) and v.strip():
                t[key] = _clean_color(v)
                break
    b = brand or {}
    if isinstance(b.get("primaryColor"), str):
        t["primary"] = _clean_color(b["primaryColor"])
    t["appName"] = (b.get("appName") or b.get("name")
                    or (design_spec or {}).get("appName") or "App")
    # Whether the design spec actually painted the sidebar (vs. the neutral fallback) —
    # lets SideNav fall back to its own mode palette instead of a stale default navy.
    t["sidebarFromSpec"] = bool(cp.get("sidebarBg") or cp.get("sidebarText"))
    return t


# ── nav derivation ──────────────────────────────────────────────────────────

def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _humanize(title: str | None, route: str = "") -> str:
    raw = title or ""
    raw = re.sub(r"(List|Detail|Create|Edit|Index)?Page$", "", raw)
    if not raw:
        seg = [s for s in (route or "").split("/") if s]
        raw = seg[0] if seg else "Home"
    raw = re.sub(r"[-_]", " ", raw)
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw)
    label = raw.strip().title() or "Home"
    # "Matters List" / "Contracts List" read as generator output, not product
    # nav. The list page IS the entity's page — drop the suffix.
    return re.sub(r"\s+List$", "", label) or "Home"


def _is_detail_page(raw_title: str | None, route: str = "") -> bool:
    """Detail pages are reached through their list's rows — they are not nav
    destinations. A rail full of 'Contract Detail' / 'User Detail' entries was
    one of the loudest same-generator signals in the audit. Checked on the RAW
    title (before _humanize strips the DetailPage suffix) plus the route."""
    t = (raw_title or "").strip()
    if re.search(r"Detail(Page)?$", t) or re.search(r"\bDetail\b\s*$", t):
        return True
    return bool(re.search(r"(^|[-/])detail(s)?($|[-/])", (route or "").lower()))


_ICONS = [
    # Abstract IA group labels (build_nav_groups emits these as section headers).
    ("overview", "layout-dashboard"), ("portfolio", "building"), ("people", "users"),
    ("financ", "dollar-sign"), ("operation", "settings-2"), ("catalog", "box"),
    ("sales", "trending-up"), ("marketing", "megaphone"), ("logistics", "truck"),
    # Dashboard / home / boards.
    ("dashboard", "home"), ("home", "home"), ("dispatch", "layout-dashboard"),
    ("board", "layout-kanban"), ("work order", "clipboard-list"), ("task", "inbox"),
    ("timeline", "calendar-clock"), ("scheduler", "calendar-clock"),
    # People-ish.
    ("customer", "users"), ("client", "users"), ("user", "user"), ("team", "users"),
    ("tenant", "users"), ("guest", "users"), ("staff", "users"), ("employee", "users"),
    ("member", "users"), ("owner", "user-check"), ("landlord", "user-check"),
    ("technician", "user-cog"), ("patient", "heart-pulse"), ("student", "graduation-cap"),
    ("doctor", "stethoscope"), ("physician", "stethoscope"), ("provider", "stethoscope"),
    ("nurse", "heart-pulse"), ("profile", "user"), ("account", "user"),
    ("search", "search"), ("directory", "search"), ("browse", "search"),
    # Places / assets.
    ("property", "building"), ("propert", "building"), ("building", "building"),
    ("unit", "door-open"), ("room", "door-open"), ("apartment", "building"),
    ("vehicle", "car"), ("equipment", "wrench"), ("asset", "package"),
    ("part", "package"), ("inventory", "package"), ("product", "box"),
    # Ops / maintenance.
    ("maintenance", "wrench"), ("repair", "wrench"), ("vendor", "truck"),
    ("supplier", "truck"), ("shipment", "truck"),
    # Money / docs.
    ("lease", "file-text"), ("contract", "file-text"), ("document", "file-text"),
    ("invoice", "receipt"), ("payment", "credit-card"), ("rent", "credit-card"),
    ("expense", "receipt"), ("budget", "pie-chart"), ("account", "wallet"),
    ("transaction", "arrow-left-right"), ("warrant", "shield"),
    # Time / comms / misc.
    ("reservation", "calendar-check"), ("booking", "calendar-check"),
    ("appointment", "calendar-check"), ("event", "calendar"),
    ("schedule", "calendar-check"), ("calendar", "calendar"),
    ("report", "bar-chart-2"), ("analytic", "bar-chart-2"), ("insight", "bar-chart-2"),
    ("workflow", "git-branch"), ("message", "mail"), ("inbox", "inbox"),
    ("notification", "bell"), ("ticket", "ticket"), ("project", "folder"),
    ("order", "shopping-cart"), ("course", "book-open"),
    ("setting", "settings"), ("config", "settings"), ("admin", "shield"),
]

# When no keyword matches, vary the icon by label so nav items don't all collapse
# to the same generic circle — deterministic (hash of the label), not random.
_FALLBACK_ICONS = [
    "circle", "square", "layers", "bookmark", "tag", "flag", "box", "folder",
]


# Generic "surface" words that describe the PAGE TYPE, not its subject.
# "Patient Dashboard" / "Doctor Dashboard" / "Staff Dashboard" all matched
# `dashboard -> home` and rendered four identical glyphs — fatal in an
# icon-only rail. These lose to any subject keyword in the same label.
_GENERIC_ICON_KEYWORDS = {"dashboard", "home", "overview", "portal", "page",
                          "console", "workspace", "hub", "center", "centre"}


def _icon_for(label: str) -> str:
    low = (label or "").lower()
    generic: str | None = None
    for kw, icon in _ICONS:
        # Word-START anchored: bare substring matching fired "board" inside
        # "dashboard" and "part" inside "department". Anchoring to a word
        # boundary while allowing the word to continue keeps the intended
        # stem matches ("propert" -> properties, "financ" -> financial).
        if not re.search(rf"\b{re.escape(kw)}", low):
            continue
        if kw in _GENERIC_ICON_KEYWORDS:
            # Remember it, but keep looking for a subject keyword first.
            generic = generic or icon
            continue
        return icon
    if generic:
        return generic
    if not low:
        return "circle"
    return _FALLBACK_ICONS[sum(ord(c) for c in low) % len(_FALLBACK_ICONS)]


def _is_top_level(page: dict) -> bool:
    if not page.get("shell"):
        return False
    if page.get("params"):
        return False
    route = page.get("route", "") or ""
    if route.endswith("/new"):
        return False
    segs = [s for s in route.split("/") if s]
    return len(segs) <= 1  # "/" or "/foo", not "/foo/bar"


def build_nav_items(nav_flow: dict) -> list[dict]:
    """Top-level destinations from nav-flow (index/dashboard pages, no detail/create)."""
    items: list[dict] = []
    seen: set[str] = set()
    demoted: list[dict] = []
    for p in (nav_flow or {}).get("pages", []) or []:
        if not _is_top_level(p):
            continue
        route = p.get("route", "/") or "/"
        if route in seen:
            continue
        seen.add(route)
        label = "Dashboard" if route == "/" else _humanize(p.get("title"), route)
        entry = {"label": label, "route": route, "icon": _icon_for(label)}
        # Demote param-less detail pages from the rail (still routable via
        # their list's rows) — unless that would gut the menu entirely.
        (demoted if _is_detail_page(p.get("title"), route) else items).append(entry)
    return items if len(items) >= 2 else items + demoted


# Deterministic IA families for ungrouped menus. Domain-neutral labels; a
# family only materialises when >=2 items land in it, so small apps stay flat.
_NAV_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    ("People", ("user", "client", "member", "team", "employee", "staff",
                "patient", "student", "customer", "contact", "guest",
                "attorney", "paralegal", "tenant", "vendor", "candidate")),
    ("Billing", ("invoice", "billing", "payment", "expense", "budget", "trust",
                 "price", "quote", "revenue", "payout", "tax", "payroll")),
    ("Documents", ("document", "template", "contract", "file", "agreement",
                   "note", "attachment", "policy", "form")),
    ("Insights", ("report", "analytic", "progress", "metric", "insight",
                  "stat", "trend", "summary", "overview")),
    ("System", ("setting", "profile", "notification", "integration", "privacy",
                "subscription", "onboarding", "sync", "admin", "preference",
                "account", "security", "calculator")),
]


def _auto_groups(items: list[dict]) -> list[dict]:
    """Cluster a long flat menu into labeled sections — deterministically.

    The LLM-authored navigation.groups is preferred when it exists; this is
    the fallback IA so an app NEVER ships an 18-item wall of flat links.
    Dashboard-ish items stay first and flat; matched families become
    sections; everything unmatched stays flat between them.
    """
    if len(items) <= 7:
        return list(items)
    lead: list[dict] = []
    rest: list[dict] = []
    for it in items:
        low = it["label"].lower()
        if it.get("route") == "/" or "dashboard" in low or low == "home":
            lead.append(it)
        else:
            rest.append(it)

    family_of: dict[int, str] = {}
    for idx, it in enumerate(rest):
        low = it["label"].lower()
        for fam, kws in _NAV_FAMILIES:
            if any(kw in low for kw in kws):
                family_of[idx] = fam
                break

    counts: dict[str, int] = {}
    for fam in family_of.values():
        counts[fam] = counts.get(fam, 0) + 1

    out: list[dict] = list(lead)
    flat_run = [it for idx, it in enumerate(rest)
                if counts.get(family_of.get(idx, ""), 0) < 2]
    out.extend(flat_run)
    for fam, _ in _NAV_FAMILIES:
        if counts.get(fam, 0) < 2:
            continue
        members = [it for idx, it in enumerate(rest) if family_of.get(idx) == fam]
        out.append({"label": fam, "icon": _icon_for(fam),
                    "items": [{"label": m["label"], "route": m["route"],
                               "icon": m["icon"]} for m in members]})
    return out


def build_nav_groups(nav_flow: dict, design_spec: dict | None = None) -> list[dict]:
    """Group nav items using the design-spec's IA groups when available (preferring
    the spec's clean labels), else a single group. Always routes from nav-flow."""
    items = build_nav_items(nav_flow)
    by_route_norm = {_norm(i["route"]): i for i in items}
    by_label_norm = {_norm(i["label"]): i for i in items}
    used: set[str] = set()
    groups: list[dict] = []

    ds_groups = ((design_spec or {}).get("navigation") or {}).get("groups") or []
    for g in ds_groups:
        gi: list[dict] = []
        for name in g.get("items", []) or []:
            n = _norm(name)
            match = by_label_norm.get(n) or by_route_norm.get(n)
            if not match and n:
                match = next((it for k, it in by_label_norm.items()
                              if k and (n in k or k in n)), None)
            if match and match["route"] not in used:
                used.add(match["route"])
                gi.append({"label": str(name).strip(), "route": match["route"],
                           "icon": match["icon"]})
        if gi:
            groups.append({"label": g.get("label", ""), "items": gi})

    leftovers = [i for i in items if i["route"] not in used]
    if leftovers:
        groups.append({"label": "More" if groups else "Menu", "items": leftovers})
    if not groups:
        groups = [{"label": "Menu", "items": items}]
    return groups


# ── node helpers ────────────────────────────────────────────────────────────

def _text(content: str, cls: str = "") -> dict:
    p: dict = {"content": content}
    if cls:
        p["className"] = cls
    return {"type": "Text", "props": p}


def _nav_btn(item: dict, cls: str, with_label: bool = True) -> dict:
    # `navigate` keeps standalone/full-reload behaviour + satisfies the shell
    # guardrail; the `onClick` nav descriptor is what the Engine's delegated
    # [data-nav-trigger] handler needs to swap the PageOutlet WITHOUT reloading
    # the shell — required for the menu to work in the editor preview.
    p: dict = {"icon": item["icon"], "variant": "ghost",
               "navigate": item["route"],
               "onClick": {"action": "navigate", "to": item["route"]},
               "className": cls}
    if with_label:
        p["label"] = item["label"]
    else:
        p["aria-label"] = item["label"]
    return {"type": "Button", "props": p}


def _icon_btn(icon: str, cls: str = "", aria: str = "",
              navigate: str = "") -> dict:
    p: dict = {"icon": icon, "variant": "ghost"}
    if cls:
        p["className"] = cls
    if aria:
        p["aria-label"] = aria
    if navigate:
        p["navigate"] = navigate
    # A hamburger IS the sidebar toggle — say so, or it renders as a button
    # that does nothing and mobile users can never open the nav. The runtime
    # is already there: `togglesSidebar` makes Button emit
    # `data-sidebar-toggle`, which the renderer's ShellStateProvider picks up
    # via its delegated click handler. Only the flag was missing, and only on
    # this deterministic path — the Figma importer sets it via its own
    # toggle heuristic (figma_to_schema), which is why this went unnoticed.
    if icon == "menu":
        p["togglesSidebar"] = True
    return {"type": "Button", "props": p}


_NOTIF_WORDS = ("notification", "notifications", "alert", "alerts", "inbox")


def _routes_of(groups: list[dict]) -> list[tuple[str, str]]:
    """Flatten grouped nav into (label, route) pairs."""
    out: list[tuple[str, str]] = []
    for g in groups or []:
        for it in (g.get("items") or []):
            if isinstance(it, dict):
                out.append((str(it.get("label") or ""), str(it.get("route") or "")))
    return out


def _notif_slot(pairs: list[tuple[str, str]]) -> list[dict]:
    """The notifications bell — but ONLY when the app actually has somewhere
    for it to go.

    A bell with no destination is a control that does nothing, which is worse
    than no bell: it advertises a capability the app does not have. So the
    chrome slot is conditional on a real notifications/alerts/inbox route, and
    when one exists the bell navigates there instead of sitting inert.
    """
    for label, route in pairs:
        hay = f"{label} {route}".lower()
        if any(w in hay for w in _NOTIF_WORDS) and route:
            return [_icon_btn("bell", "", "Notifications", navigate=route)]
    return []


def _avatar(cls: str = "") -> dict:
    return {"type": "Avatar", "props": {"name": "User", "size": "sm"}}


def _page_outlet() -> dict:
    return {"type": "PageOutlet", "id": "page-outlet"}


def _brand_mark(tokens: dict, on_dark: bool) -> dict:
    letter = (tokens.get("appName") or "A").strip()[:1].upper()
    txt = "#FFFFFF" if on_dark else tokens["onPrimary"]
    return {
        "type": "Container",
        "props": {"className": f"h-8 w-8 rounded-md bg-[{tokens['accent']}] "
                               f"flex items-center justify-center font-semibold text-sm text-[{txt}]"},
        "children": [_text(letter)],
    }


# ── frames ────────────────────────────────────────────────────────────────────

def _frame_sidebar(groups: list[dict], tokens: dict) -> dict:
    sb, sbt, sbm = tokens["sidebarBg"], tokens["sidebarText"], tokens["sidebarMuted"]
    nav_children: list[dict] = []
    for g in groups:
        kids = [_text(g["label"].upper(),
                      f"text-[{sbm}] text-xs uppercase tracking-wide px-3 py-1.5 font-medium")] if g["label"] else []
        kids += [_nav_btn(i, f"justify-start w-full text-[{sbt}]") for i in g["items"]]
        nav_children.append({"type": "Stack", "props": {"className": "gap-0.5 px-2"}, "children": kids})

    sidebar = {
        "type": "Container",
        "props": {"data-shell-region": "sidebar", "shellRole": "sidebar",
                  "className": f"hidden md:flex w-60 bg-[{sb}] text-[{sbt}] flex-col h-screen overflow-y-auto shrink-0 sidebar-scroll"},
        "children": [
            {"type": "Row", "props": {"className": "items-center gap-2 px-4 py-4"},
             "children": [_brand_mark(tokens, True),
                          {"type": "Heading", "props": {"content": tokens["appName"], "level": 4,
                                                        "className": f"text-[{sbt}] text-base"}}]},
            {"type": "Stack", "props": {"className": "flex-1 overflow-y-auto py-3 gap-4 text-sm"},
             "children": nav_children},
            {"type": "Container", "props": {"className": "p-3 mt-auto"},
             "children": [{"type": "Row", "props": {"className": "items-center gap-2 px-2 py-2"},
                           "children": [_avatar(), _text("User", f"text-sm text-[{sbt}]"),
                                        _icon_btn("log-out", "h-8 w-8 ml-auto", "Logout")]}]},
        ],
    }
    main = {
        "type": "Stack",
        "props": {"className": "flex-1 flex-col overflow-hidden h-screen overflow-y-auto main-scroll min-w-0"},
        "children": [
            {"type": "Container", "props": {"data-shell-region": "header",
                                            "className": f"flex items-center gap-3 {_GUTTER_X} py-3 border-b bg-[{tokens['surface']}]"},
             "children": [_icon_btn("menu", "md:hidden", "Open menu"),
                          {"type": "Container", "props": {"className": "flex-1"}},
                          {"type": "Input", "props": {"name": "search", "type": "text",
                                                      "placeholder": "Search...", "className": "max-w-md", "aria-label": "Search"}},
                          *_notif_slot(_routes_of(groups)), _avatar()]},
            _page_outlet(),
        ],
    }
    return {"type": "Row", "props": {"className": "w-full h-screen overflow-hidden items-stretch"},
            "children": [sidebar, main]}


def _frame_topbar(groups: list[dict], tokens: dict) -> dict:
    items = [i for g in groups for i in g["items"]]
    nav = [_nav_btn(i, f"text-[{tokens['text']}]") for i in items[:8]]
    topbar = {
        "type": "Container",
        "props": {"data-shell-region": "header",
                  "className": f"flex items-center gap-2 {_GUTTER_X} py-3 border-b bg-[{tokens['surface']}] shrink-0"},
        "children": [
            {"type": "Row", "props": {"className": "items-center gap-2 mr-4"},
             "children": [_brand_mark(tokens, False),
                          {"type": "Heading", "props": {"content": tokens["appName"], "level": 4,
                                                        "className": f"text-[{tokens['text']}] text-base"}}]},
            {"type": "Row", "props": {"className": "items-center gap-1 flex-wrap"}, "children": nav},
            {"type": "Container", "props": {"className": "flex-1"}},
            {"type": "Input", "props": {"name": "search", "type": "text", "placeholder": "Search...",
                                        "className": "max-w-xs", "aria-label": "Search"}},
            *_notif_slot(_routes_of(groups)), _avatar(),
        ],
    }
    body = {"type": "Stack",
            "props": {"className": f"flex-1 overflow-y-auto main-scroll bg-[{tokens['background']}]"},
            "children": [_page_outlet()]}
    return {"type": "Stack", "props": {"className": "w-full h-screen overflow-hidden flex-col"},
            "children": [topbar, body]}


def _frame_rail(groups: list[dict], tokens: dict) -> dict:
    sb, sbt = tokens["sidebarBg"], tokens["sidebarText"]
    items = [i for g in groups for i in g["items"]]
    rail_btns = [_nav_btn(i, f"w-10 h-10 justify-center text-[{sbt}]", with_label=False) for i in items[:12]]
    rail = {
        "type": "Container",
        "props": {"data-shell-region": "sidebar", "shellRole": "rail",
                  "className": f"hidden md:flex w-16 bg-[{sb}] flex-col items-center h-screen shrink-0 py-3 gap-1"},
        "children": [
            _brand_mark(tokens, True),
            {"type": "Stack", "props": {"className": "flex-1 items-center gap-1 mt-3 overflow-y-auto"},
             "children": rail_btns},
            _avatar("mt-auto"),
        ],
    }
    main = {
        "type": "Stack",
        "props": {"className": "flex-1 flex-col overflow-hidden h-screen overflow-y-auto main-scroll min-w-0"},
        "children": [
            {"type": "Container", "props": {"data-shell-region": "header",
                                            "className": f"flex items-center gap-3 {_GUTTER_X} py-3 border-b bg-[{tokens['surface']}]"},
             "children": [{"type": "Heading", "props": {"content": tokens["appName"], "level": 4,
                                                        "className": f"text-[{tokens['text']}] text-base"}},
                          {"type": "Container", "props": {"className": "flex-1"}},
                          {"type": "Input", "props": {"name": "search", "type": "text", "placeholder": "Search...",
                                                      "className": "max-w-md", "aria-label": "Search"}},
                          *_notif_slot(_routes_of(groups)), _avatar()]},
            _page_outlet(),
        ],
    }
    return {"type": "Row", "props": {"className": "w-full h-screen overflow-hidden items-stretch"},
            "children": [rail, main]}


def _frame_split(groups: list[dict], tokens: dict) -> dict:
    """Three-zone workspace: a slim icon rail (one icon per nav group) + a labeled
    list pane (the destinations) + the main content. The Slack / Linear / email shape,
    for inbox/messaging-centric apps that read list -> detail."""
    sb, sbt = tokens["sidebarBg"], tokens["sidebarMuted"]
    surf, txt, brd, muted = tokens["surface"], tokens["text"], tokens["border"], tokens["textMuted"]

    rail_icons = []
    for g in groups:
        if g["items"]:
            first = g["items"][0]
            rail_icons.append(_nav_btn(
                {"label": g["label"] or first["label"], "route": first["route"], "icon": _icon_for(g["label"]) if g["label"] else first["icon"]},
                f"w-10 h-10 justify-center text-[{tokens['sidebarText']}]", with_label=False))
    rail = {
        "type": "Container",
        "props": {"data-shell-region": "rail",
                  "className": f"hidden md:flex w-14 bg-[{sb}] flex-col items-center h-screen shrink-0 py-3 gap-1"},
        "children": [_brand_mark(tokens, True),
                     {"type": "Stack", "props": {"className": "flex-1 items-center gap-1 mt-3 overflow-y-auto"},
                      "children": rail_icons},
                     _icon_btn("settings", f"w-10 h-10 justify-center text-[{tokens['sidebarText']}] mt-auto", "Settings")],
    }

    list_children: list[dict] = []
    for g in groups:
        kids = [_text(g["label"], f"text-[{muted}] text-xs uppercase tracking-wide px-2 py-1 font-medium")] if g["label"] else []
        kids += [_nav_btn(i, f"justify-start w-full text-[{txt}]") for i in g["items"]]
        list_children.append({"type": "Stack", "props": {"className": "gap-0.5"}, "children": kids})
    list_pane = {
        "type": "Container",
        "props": {"data-shell-region": "sidebar",
                  "className": f"hidden md:flex w-52 bg-[{surf}] border-r border-[{brd}] flex-col h-screen overflow-y-auto shrink-0 sidebar-scroll"},
        "children": [
            {"type": "Container", "props": {"className": f"px-3 py-3 border-b border-[{brd}]"},
             "children": [{"type": "Heading", "props": {"content": tokens["appName"], "level": 5,
                                                        "className": f"text-[{txt}] text-sm"}}]},
            {"type": "Stack", "props": {"className": "flex-1 overflow-y-auto py-3 px-2 gap-4 text-sm"},
             "children": list_children},
        ],
    }
    main = {
        "type": "Stack",
        "props": {"className": "flex-1 flex-col overflow-hidden h-screen overflow-y-auto main-scroll min-w-0"},
        "children": [
            {"type": "Container", "props": {"data-shell-region": "header",
                                            "className": f"flex items-center gap-3 {_GUTTER_X} py-3 border-b bg-[{surf}]"},
             "children": [{"type": "Container", "props": {"className": "flex-1"}},
                          {"type": "Input", "props": {"name": "search", "type": "text", "placeholder": "Search...",
                                                      "className": "max-w-md", "aria-label": "Search"}},
                          *_notif_slot(_routes_of(groups)), _avatar()]},
            _page_outlet(),
        ],
    }
    return {"type": "Row", "props": {"className": "w-full h-screen overflow-hidden items-stretch"},
            "children": [rail, list_pane, main]}


def _is_dark(hexc: str | None) -> bool:
    """Relative-luminance test so we can pick a dark vs light rail from any bg color."""
    try:
        h = (hexc or "").lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) < 140
    except Exception:
        return True


def _nav_pref(design_spec: dict | None) -> str:
    """The design agent's chosen navigation style (string or dict), normalised."""
    nav = (design_spec or {}).get("navigation")
    if isinstance(nav, str):
        return nav.strip().lower()
    if isinstance(nav, dict):
        s = nav.get("style") or nav.get("type")
        if s:
            return str(s).strip().lower()
    lay = (design_spec or {}).get("layout")
    if isinstance(lay, dict) and lay.get("navigation"):
        return str(lay["navigation"]).strip().lower()
    return ""


def _sidebar_mode(tokens: dict, design_spec: dict | None) -> str:
    """Dark or light rail — from the design agent's nav style, else bg luminance."""
    pref = _nav_pref(design_spec)
    if "dark" in pref:
        return "dark"
    if pref in ("sidebar", "sidebar-light", "light"):
        return "light"
    return "dark" if (tokens.get("sidebarFromSpec") and _is_dark(tokens.get("sidebarBg"))) else (
        "dark" if not tokens.get("sidebarFromSpec") else "light")


def build_sidenav_groups(nav_flow: dict, design_spec: dict | None = None) -> list[dict]:
    """Main menu items (icon + label) with optional sub-items (icon + label), from the
    design-spec IA groups + nav-flow. Grouped items become a section (main + subs);
    ungrouped top-level pages become flat main items."""
    items = build_nav_items(nav_flow)
    by_route = {_norm(i["route"]): i for i in items}
    by_label = {_norm(i["label"]): i for i in items}
    used: set[str] = set()
    out: list[dict] = []

    nav = (design_spec or {}).get("navigation")
    ds_groups = (nav.get("groups") if isinstance(nav, dict) else None) or []
    for g in ds_groups:
        subs: list[dict] = []
        for name in g.get("items", []) or []:
            n = _norm(name)
            m = by_label.get(n) or by_route.get(n)
            if not m and n:
                m = next((it for k, it in by_label.items() if k and (n in k or k in n)), None)
            if m and m["route"] not in used:
                used.add(m["route"])
                subs.append({"label": m["label"], "route": m["route"], "icon": m["icon"]})
        if subs:
            out.append({"label": g.get("label", ""), "icon": _icon_for(g.get("label", "")), "items": subs})

    leftovers = [{"label": it["label"], "route": it["route"], "icon": it["icon"]}
                 for it in items if it["route"] not in used]
    if out:
        # LLM-curated groups exist — append whatever they missed, flat.
        out.extend(leftovers)
        return out
    # No curated IA at all (the DNA/industry-fallback paths): cluster the flat
    # wall deterministically instead of shipping 18 ungrouped links.
    return _auto_groups(leftovers) or leftovers


def _widest_label(groups: list[dict]) -> str:
    """The longest visible label anywhere in the SideNav tree — brand,
    group headers, group items, sub-items. Drives the content-fit
    expanded-width calc so labels like 'Front-Desk Staff Availability'
    don't render as 'Front-Desk Staff Avai…'."""
    widest = ""
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        for key in ("label", "title", "name"):
            v = g.get(key)
            if isinstance(v, str) and len(v) > len(widest):
                widest = v
        for item in (g.get("items") or []) if isinstance(g.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            for key in ("label", "title", "name"):
                v = item.get(key)
                if isinstance(v, str) and len(v) > len(widest):
                    widest = v
            for sub in (item.get("items") or []) if isinstance(item.get("items"), list) else []:
                if isinstance(sub, dict):
                    for key in ("label", "title", "name"):
                        v = sub.get(key)
                        if isinstance(v, str) and len(v) > len(widest):
                            widest = v
    return widest


def _expanded_width_for(groups: list[dict], app_name: str) -> int:
    """Content-fit width for the SideNav's expanded rail.

    Sizing model (derived from the library's tf-row CSS at
    packages/library/src/components/SideNav/SideNav.tsx:61):
      icon-cell (14+20=34px) + gap (14) + label + right-padding (20) +
      breathing (12) = base ~80px of chrome.
    Rough per-character width at the 14px SideNav font: 8.4px average.
    Clamp to [236, 320]px — 236 is the library default (matches short-
    label apps); 320 is the empirical UX ceiling before the rail eats
    too much page. Anything longer TRUNCATES with ellipsis (correct —
    a monster 50-char label shouldn't take 500px of chrome)."""
    widest = max(_widest_label(groups), app_name or "", key=len)
    n = len(widest)
    # Empirical: 14px sans-serif ~8.4px/char with occasional wide chars.
    est = int(round(80 + n * 8.4))
    return max(236, min(est, 320))


def _sidenav(groups: list[dict], tokens: dict, mode: str) -> dict:
    """The SideNav library node — collapsible hover-expand rail, token-painted.
    Colors are passed only when the design spec actually provided sidebar tokens;
    otherwise SideNav falls back to its own (mode-derived) palette.

    ``expandedWidth`` is computed deterministically from the widest label
    so multi-word menu items ('Front-Desk Staff Availability') don't
    truncate at the library's 236px default. Clamped to [236, 320]."""
    props: dict = {
        "groups": groups,
        "appName": tokens.get("appName", "App"),
        "mode": mode,
        "accent": tokens.get("accent") or tokens.get("primary"),
        "expandedWidth": _expanded_width_for(groups, tokens.get("appName", "App")),
    }
    if tokens.get("sidebarFromSpec"):
        props["bg"] = tokens.get("sidebarBg")
        props["text"] = tokens.get("sidebarText")
        props["muted"] = tokens.get("sidebarMuted")
    return {"type": "SideNav", "props": props}


def _frame_sidenav(nav_flow: dict, tokens: dict, design_spec: dict | None, mode: str) -> dict:
    """Sidebar/rail frame built around the collapsible SideNav component."""
    groups = build_sidenav_groups(nav_flow, design_spec)
    nav = _sidenav(groups, tokens, mode)
    main = {
        "type": "Stack",
        "props": {"className": "flex-1 flex-col overflow-hidden h-screen overflow-y-auto main-scroll min-w-0"},
        "children": [
            {"type": "Container",
             "props": {"data-shell-region": "header",
                       "className": f"flex items-center gap-3 {_GUTTER_X} py-3 border-b bg-[{tokens['surface']}]"},
             "children": [{"type": "Container", "props": {"className": "flex-1"}},
                          {"type": "Input", "props": {"name": "search", "type": "text", "placeholder": "Search...",
                                                      "className": "max-w-md", "aria-label": "Search"}},
                          *_notif_slot(_routes_of(groups)), _avatar()]},
            _page_outlet(),
        ],
    }
    return {"type": "Row", "props": {"className": "w-full h-screen overflow-hidden items-stretch"},
            "children": [nav, main]}


# ── PB-3: persona-pills frame (Claude-yoga-demo style) ──────────────────────
#
# Consumer-product apps with a small set of personas (Member / Instructor /
# Studio Admin, or Buyer / Seller / Support, …) read as ADMIN PANELS when
# they get a sidebar. The persona-pills frame is a top-strip that:
#
#   [brand mark  wordmark]                 [ pill · pill · pill ]  [avatar]
#
# with each pill being a persona (icon + name) that navigates to that
# persona's first job route. No sidebar, no left rail — the whole screen
# becomes CONTENT with a small always-visible identity + role-switcher up
# top. This is what the Claude-Artifact yoga demo used and what makes an
# app stop looking like an admin panel.
#
# Selection: :func:`select_frame` prefers this frame when nav_flow.personas
# is present (attached by PB-4 when a product brief was synthesised) AND
# persona count is 2-4. Single-persona apps stay on topbar (no switcher
# needed); 5+ persona apps fall back to sidebar (pills overflow).
#
# The frame draws EVERY persona's landing route as a pill link. Sub-tab
# rendering (Member's [Schedule | My Bookings | Membership | My Reviews])
# is per-page work — the shell only paints the identity + persona strip.


def _persona_pill(persona: dict, tokens: dict, is_first: bool) -> dict:
    """One persona pill. Links to the persona's first job route.

    ``is_first`` gets a subtly-different visual state so the user has a
    hint about which persona they're currently in (best-effort — real
    active-state is a runtime concern the pages resolve).
    """
    jobs = persona.get("jobs") or []
    first_job = jobs[0] if jobs else None
    route = first_job.get("route") if isinstance(first_job, dict) else "/"
    label = persona.get("name") or "Persona"
    # Active pill: filled surface + full text (raised look).
    # Inactive: transparent with slightly dimmed text.
    # Neutral tints via Tailwind opacity utilities so we don't depend on
    # optional token keys (e.g. tokens['muted'] isn't guaranteed present).
    active_cls = (f"px-4 py-1.5 rounded-full bg-[{tokens['surface']}] "
                  f"text-[{tokens['text']}] text-sm font-medium shadow-sm")
    inactive_cls = (f"px-4 py-1.5 rounded-full bg-transparent "
                    f"text-[{tokens['text']}]/70 text-sm font-medium "
                    f"hover:bg-[{tokens['surface']}]/60")
    return {
        "type": "Button",
        "props": {
            "label": label,
            "variant": "ghost",
            "navigate": route,
            "onClick": {"action": "navigate", "to": route},
            "className": active_cls if is_first else inactive_cls,
        },
    }


def _frame_persona_pills(personas: list[dict], tokens: dict) -> dict:
    """Top-strip shell with a persona pill-switcher and a page outlet body.

    ``personas`` is the ``nav_flow.personas`` array (PB-4). Each entry is
    ``{id, name, role, jobs: [{id, label, route, pageId}]}``.
    """
    # A subtle tinted container that HOLDS the persona pills — matches the
    # Claude yoga demo's segmented-control look. Uses the border token
    # (always present) tinted with Tailwind opacity so it works on any
    # palette without depending on optional token keys.
    pills_container = {
        "type": "Row",
        "props": {"className": f"items-center gap-1 rounded-full bg-[{tokens['border']}]/40 p-1"},
        "children": [
            _persona_pill(p, tokens, is_first=(i == 0))
            for i, p in enumerate(personas)
        ],
    }
    topbar = {
        "type": "Container",
        "props": {"data-shell-region": "header",
                  "className": f"flex items-center justify-between {_GUTTER_X} py-5 "
                               f"bg-[{tokens['background']}]"},
        "children": [
            # Brand mark + wordmark, left
            {"type": "Row", "props": {"className": "items-center gap-3"},
             "children": [_brand_mark(tokens, False),
                          {"type": "Stack", "props": {"className": "gap-0"},
                           "children": [
                               {"type": "Heading",
                                "props": {"content": tokens["appName"], "level": 3,
                                          "className": f"text-[{tokens['text']}] text-lg font-semibold leading-tight"}},
                           ]}]},
            # Persona pill container, right
            pills_container,
        ],
    }
    body = {
        "type": "Stack",
        "props": {"className": f"flex-1 overflow-y-auto main-scroll bg-[{tokens['background']}]"},
        "children": [_page_outlet()],
    }
    return {
        "type": "Stack",
        "props": {"className": "w-full h-screen overflow-hidden flex-col"},
        "children": [topbar, body],
    }


FRAMES = {"sidebar": _frame_sidebar, "topbar": _frame_topbar,
          "rail": _frame_rail, "split": _frame_split,
          "persona-pills": _frame_persona_pills}


# ── selection + entry ─────────────────────────────────────────────────────────

_CANVAS_ARCHETYPES = {"kanban", "board", "calendar", "timeline", "map"}
_SPLIT_ARCHETYPES = {"inbox", "split", "messages", "mail"}


# IRF-M3-T2: map from the shape-primitive vocabulary
# (backend/shapes/vocabulary.json → layout.shell) to the FRAMES table above.
# The two vocabularies differ historically — shell_templates predates the
# four-axis substrate. This table is the ONE place they're reconciled.
#
# - "none" maps to the sentinel string "none" — build_shell_deterministic
#   returns an empty-frame shell that the pipeline can treat as "skip
#   shell". Consumer utilities (Snap2App-style) declare shell=none.
# - "bottom-tabs" (mobile-native) has no direct web-shell equivalent; we
#   render as topbar with tab-style styling and rely on the mobile
#   scaffolding (M3-T9) to render true bottom tabs on Expo.
# - "map-canvas" apps (Uber-style) use the map as the shell itself; the
#   nearest web-shell approximation is topbar-over-map, which lets the
#   page schema fill the rest with a MapCanvas component.
_APP_SHAPE_TO_FRAME = {
    "none":          "none",
    "sidebar":       "sidebar",
    "header":        "topbar",
    "three-pane":    "split",
    "bottom-tabs":   "topbar",   # closest web-shell approx; mobile uses real tabs
    "map-canvas":    "topbar",   # topbar over MapCanvas
}


def _frame_from_app_shape(plan: dict | None) -> str | None:
    """Read ``plan.app_shape.layout.shell`` and translate to a FRAMES
    key. Returns None when the shape wasn't declared — caller falls
    through to design_spec / IA heuristic."""
    if not isinstance(plan, dict):
        return None
    shape = plan.get("app_shape")
    if not isinstance(shape, dict):
        return None
    layout = shape.get("layout")
    if not isinstance(layout, dict):
        return None
    shell = layout.get("shell")
    if not isinstance(shell, str):
        return None
    return _APP_SHAPE_TO_FRAME.get(shell)


def select_frame(plan: dict | None, nav_flow: dict, design_spec: dict | None = None) -> str:
    """Deterministically pick a shell frame from the app's information architecture,
    so different domains get structurally different shells (not always a sidebar).

    PB-3: HIGHEST priority (above every other consideration) is the
    persona-pills frame when the app has a small persona set. The
    product brief (PB-2) attached ``nav_flow.personas`` in PB-4 iff
    the app has 2-4 personas with at least one resolvable job each.
    When present, we serve the persona-pills top-strip frame — the
    Claude-yoga-demo layout that makes the shell stop looking like an
    admin panel. Single-persona apps skip this (a switcher for one
    role is dead chrome); 5+ persona apps fall through to sidebar
    (pills overflow the top strip).
    """
    personas = (nav_flow or {}).get("personas") if isinstance(nav_flow, dict) else None
    if isinstance(personas, list) and 2 <= len(personas) <= 4:
        return "persona-pills"
    shape_frame = _frame_from_app_shape(plan)
    # A planner-authored app_shape wins UNLESS role-multiplicity contradicts it.
    # A "header" shape choice becomes user-hostile the moment ≥2 actors need
    # different menu subsets — the persistent sidebar is what makes the
    # per-role split legible. Let the IA heuristic override in that case.
    _actors_for_override = (plan or {}).get("actors")
    _actor_count_early = (
        sum(1 for a in _actors_for_override if isinstance(a, dict))
        if isinstance(_actors_for_override, list)
        else (len(_actors_for_override) if isinstance(_actors_for_override, dict) else 0)
    )
    if shape_frame is not None and not (shape_frame == "topbar" and _actor_count_early >= 2):
        return shape_frame

    items = build_nav_items(nav_flow)
    n = len(items)

    # Honor the design agent's chosen navigation style first (per-domain, dynamic);
    # fall back to the IA heuristic only when it didn't specify one.
    pref = _nav_pref(design_spec)
    explicit = {
        "sidebar": "sidebar", "sidebar-dark": "sidebar", "sidebar-light": "sidebar",
        "rail": "rail", "icon-rail": "rail",
        "topbar": "topbar", "top-bar": "topbar", "command-bar": "topbar", "bottom-tabs": "topbar",
        "split": "split", "split-workspace": "split", "list-detail": "split",
    }
    if pref in explicit:
        return explicit[pref]

    archetypes = set()
    for p in (plan or {}).get("pages", []) or []:
        a = (p.get("archetype") or "").strip().lower()
        if a:
            archetypes.add(a)
    routes_blob = " ".join(i["route"] for i in items)
    split_heavy = bool(archetypes & _SPLIT_ARCHETYPES) or any(
        k in routes_blob for k in ("inbox", "message", "conversation", "ticket", "mail"))
    # "board" as a bare substring matches "dashboard" — word-boundary the check.
    import re as _re
    canvas_heavy = bool(archetypes & _CANVAS_ARCHETYPES) or "dispatch" in routes_blob or bool(_re.search(r"\bboard\b", routes_blob))

    # Role multiplicity — apps with multiple actors (admin + member + instructor,
    # tenant + landlord, etc.) benefit from a sidebar because each role's menu
    # subset stays persistently visible. Single-actor apps can stay in topbar
    # even at moderate item counts.
    actors = (plan or {}).get("actors")
    if isinstance(actors, list):
        actor_count = sum(1 for a in actors if isinstance(a, dict))
    elif isinstance(actors, dict):
        actor_count = len(actors)
    else:
        actor_count = 0
    multi_actor = actor_count >= 2

    if split_heavy:
        return "split"
    if canvas_heavy:
        return "rail"
    # Multi-actor + non-trivial IA → sidebar even at moderate counts. The old
    # `n <= 5 → topbar` rule mis-fired on the Yoga Studio Booking case
    # (admin + member roles, 5 unique tops) — a topbar can't express the
    # per-role menu split.
    if multi_actor and n >= 4:
        return "sidebar"
    if n <= 5:
        return "topbar"
    if n >= 10:
        return "sidebar"
    return "topbar"


def build_shell_deterministic(plan: dict | None, nav_flow: dict,
                              brand: dict | None = None,
                              design_spec: dict | None = None) -> dict:
    """Build a complete, renderable shell.json deterministically: select a frame by IA,
    derive grouped nav from nav-flow, paint with the real design tokens."""
    # Fix 4 branding lock — when the plan carries an explicit appName (set by
    # the entrypoint from project.name for Figma imports, or by the planner
    # for other flows), that name is authoritative for the shell brand. It
    # would otherwise be lost: `extract_tokens` only reads `brand.appName`
    # and `design_spec.appName`, neither of which knows about the plan.
    _plan_name = (plan or {}).get("appName") or (plan or {}).get("name")
    if _plan_name and str(_plan_name).strip():
        brand = dict(brand or {})
        brand.setdefault("appName", str(_plan_name).strip())
    tokens = extract_tokens(design_spec, brand)
    frame = select_frame(plan, nav_flow, design_spec)
    # IRF-M3-T2: shape.layout.shell="none" → emit a passthrough shell that
    # renders its children with zero chrome. Consumer utilities (Snap2App)
    # need this — their hero pages are the whole UI; wrapping them in a
    # sidebar or topbar shows dead chrome above the hero. The frame marker
    # stays on the shell so downstream consumers (menu sync, root-layout
    # Toaster guard) can honor the "no shell" intent without touching this
    # module.
    if frame == "none":
        return {"schemaVersion": "2.0", "title": "App Shell", "id": "shell",
                "frame": "none",
                "appName": tokens.get("appName", "App"),
                "children": [{"type": "Slot", "props": {}}]}
    # Sidebar / rail frames use the collapsible, token-painted SideNav component;
    # topbar / split keep the deterministic button frames.
    if frame in ("sidebar", "rail"):
        mode = _sidebar_mode(tokens, design_spec)
        root = _frame_sidenav(nav_flow, tokens, design_spec, mode)
    elif frame == "persona-pills":
        # PB-3: persona-pill frame reads personas straight from nav_flow
        # (attached by PB-4) rather than the entity-grouped nav-items
        # the other frames consume. When the personas array is somehow
        # missing (defensive), fall back to topbar so we still emit a
        # renderable shell.
        personas = (nav_flow or {}).get("personas") or []
        if not personas:
            groups = build_nav_groups(nav_flow, design_spec)
            root = _frame_topbar(groups, tokens)
            frame = "topbar"
        else:
            root = _frame_persona_pills(personas, tokens)
    else:
        groups = build_nav_groups(nav_flow, design_spec)
        root = FRAMES.get(frame, _frame_topbar)(groups, tokens)
    return {"schemaVersion": "2.0", "title": "App Shell", "id": "shell",
            "frame": frame,
            # 2026-08-13 — top-level appName so layout.tsx doesn't have to
            # dig for it inside a SideNav prop bag (the persona-pills frame
            # doesn't emit a SideNav, so appName used to fall through to the
            # literal "__APP_NAME__" template placeholder on wellness apps).
            "appName": tokens.get("appName", "App"),
            "children": [root]}
