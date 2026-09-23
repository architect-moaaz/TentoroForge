"""The application's look, as a person edits it: colours by the job they do,
the fonts, how rounded corners are, how dense the screens are.

Reads and writes the Blueprint's ``designSystem`` — the single source every
page's tokens are projected from — through the same seam a restyle uses, so
Smith sees the person's choice as the decision it is, and re-projects
``tokens.css`` so the canvas and the running app follow at once.
"""
from __future__ import annotations

import colorsys
import re
import uuid
from typing import Any

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result
from services.blueprint.projection import _resolve_role, _token_contract, project_design_tokens
from services.react_editor.service import EditorError, Project, load_blueprint

#: The colour roles a person sets, by the job each does. The first name of
#: each is the Blueprint role written; the contract resolves the others.
COLOR_ROLES: list[dict[str, Any]] = [
    {"role": "primary", "group": "Brand", "label": "Main colour", "about": "Buttons, links, the active item"},
    {"role": "accent", "group": "Brand", "label": "Highlight", "about": "The one thing on a screen to notice"},
    {"role": "background", "group": "Surfaces", "label": "Page background", "about": "Behind everything"},
    {"role": "surface", "group": "Surfaces", "label": "Cards and panels", "about": "Boxes that sit on the page"},
    {"role": "surfaceMuted", "group": "Surfaces", "label": "Quiet areas", "about": "Table headers, disabled parts"},
    {"role": "border", "group": "Surfaces", "label": "Lines", "about": "Borders and dividers"},
    {"role": "inverse", "group": "Surfaces", "label": "Dark bars", "about": "A sidebar or footer drawn dark"},
    {"role": "gradientStart", "group": "Brand", "label": "Gradient, from", "about": "The sign-in panel and hero bands start here"},
    {"role": "gradientEnd", "group": "Brand", "label": "Gradient, to", "about": "…and blend to this"},
    {"role": "textPrimary", "group": "Text", "label": "Text", "about": "Most words"},
    {"role": "textSecondary", "group": "Text", "label": "Quieter text", "about": "Hints, captions, labels"},
    {"role": "danger", "group": "Status", "label": "Danger", "about": "Errors, delete"},
    {"role": "success", "group": "Status", "label": "Success", "about": "Done, saved"},
    {"role": "warning", "group": "Status", "label": "Warning", "about": "Needs attention"},
    {"role": "info", "group": "Status", "label": "Information", "about": "Notes, tips"},
]

RADIUS_CHOICES = [("0px", "Sharp"), ("4px", "Slight"), ("8px", "Soft"), ("12px", "Round"), ("16px", "Very round")]
DENSITIES = ("compact", "comfortable", "spacious")
FONT_SUGGESTIONS = ["Inter", "Roboto", "Open Sans", "Lato", "Source Sans 3", "Nunito", "Poppins", "Manrope", "IBM Plex Sans", "Work Sans",
                    "Merriweather", "Playfair Display", "Fraunces", "Lora", "Georgia", "system-ui"]

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_TRIPLET = re.compile(r"^(-?\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%$")


def _hex(value: str | None) -> str | None:
    """A Blueprint colour (hex, or the contract's HSL triplet) as #rrggbb."""
    if not value:
        return None
    v = str(value).strip()
    if _HEX.match(v):
        return v.lower() if len(v) == 7 else "#" + "".join(c * 2 for c in v[1:]).lower()
    m = _TRIPLET.match(v)
    if m:
        h, s, l = float(m.group(1)) % 360 / 360, float(m.group(2)) / 100, float(m.group(3)) / 100
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
    return None


def _luminance(hex6: str) -> float:
    def ch(c: str) -> float:
        x = int(c, 16) / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(hex6[1:3]) + 0.7152 * ch(hex6[3:5]) + 0.0722 * ch(hex6[5:7])


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def _default(role: str) -> str | None:
    """The contract's light default for the token this role feeds."""
    for spec in _token_contract().get("colorTokens") or []:
        if role in (spec.get("role") or []):
            return _hex(spec.get("light"))
    return None


def _roles_for(role: str) -> list[str]:
    for spec in _token_contract().get("colorTokens") or []:
        roles = spec.get("role") or []
        if roles and roles[0] == role:
            return list(roles)
    return [role]


def warnings_for(colors: dict[str, str]) -> list[str]:
    """What would be hard to read, in plain words."""
    out = []
    text = colors.get("textPrimary"); bg = colors.get("background"); surface = colors.get("surface")
    primary = colors.get("primary"); quiet = colors.get("textSecondary")
    if text and bg and contrast(text, bg) < 4.5:
        out.append(f"Text on the page background is hard to read ({contrast(text, bg)}:1 — aim for 4.5 or more).")
    if text and surface and contrast(text, surface) < 4.5:
        out.append(f"Text on cards is hard to read ({contrast(text, surface)}:1 — aim for 4.5 or more).")
    if quiet and bg and contrast(quiet, bg) < 3:
        out.append(f"Quieter text fades into the background ({contrast(quiet, bg)}:1 — aim for 3 or more).")
    if primary and contrast(primary, "#ffffff") < 3 and contrast(primary, "#000000") < 3:
        out.append("The main colour is a mid-tone — neither white nor black text reads well on it.")
    if primary and bg and contrast(primary, bg) < 3:
        out.append(f"The main colour barely stands out from the page background ({contrast(primary, bg)}:1).")
    return out


def get(project: Project) -> dict[str, Any]:
    svc = load_blueprint(project)
    ds = svc.doc.get("designSystem") or {}
    colors = ds.get("colors") or {}
    typography = ds.get("typography") or {}
    radius = ds.get("radius") if isinstance(ds.get("radius"), dict) else {}
    roles = []
    resolved: dict[str, str] = {}
    for spec in COLOR_ROLES:
        raw = _resolve_role(colors, _roles_for(spec["role"]))
        value = _hex(raw) or _default(spec["role"])
        if value:
            resolved[spec["role"]] = value
        roles.append({**spec, "value": value, "set": raw is not None})
    font = next((typography.get(k) for k in ("fontFamilyBase", "fontFamily", "body", "base") if isinstance(typography.get(k), str) and "px" not in typography.get(k)), "")
    heading = next((typography.get(k) for k in ("fontFamilyHeading", "headingFamily", "headings") if isinstance(typography.get(k), str)), "")
    size = next((typography.get(k) for k in ("baseSize", "fontSizeBase") if isinstance(typography.get(k), str)), "")
    return {
        "personality": ds.get("visualPersonality") or "",
        "colors": roles,
        "font": font, "headingFont": heading, "baseSize": size, "fontSuggestions": FONT_SUGGESTIONS,
        "radius": (radius or {}).get("md") or (ds.get("radius") if isinstance(ds.get("radius"), str) else "") or "8px",
        "radiusChoices": [{"value": v, "label": l} for v, l in RADIUS_CHOICES],
        "density": ds.get("informationDensity") or "comfortable",
        "warnings": warnings_for(resolved),
        "hasDesign": bool(colors),
    }


def update(project: Project, patch: dict[str, Any]) -> dict[str, Any]:
    """Apply what the person changed and re-project the app's tokens."""
    svc = load_blueprint(project)
    ds = dict(svc.doc.get("designSystem") or {})
    if not ds.get("colors"):
        raise EditorError(409, "no-design", "This application has no design system yet — the build authors it.")
    colors = dict(ds.get("colors") or {})
    changed: list[str] = []
    for role, value in (patch.get("colors") or {}).items():
        if role not in {r["role"] for r in COLOR_ROLES}:
            raise EditorError(422, "bad-role", f"“{role}” is not a colour this application's look has.")
        hx = _hex(str(value))
        if not hx:
            raise EditorError(422, "bad-colour", f"“{value}” is not a colour — pick one, or type it as #rrggbb.")
        colors[role] = hx
        changed.append(f"{role} → {hx}")
    ds["colors"] = colors
    typography = dict(ds.get("typography") or {})
    if "font" in patch:
        f = str(patch["font"] or "").strip()
        if f:
            typography["fontFamilyBase"] = f
            typography.pop("fontFamily", None)
            changed.append(f"font → {f}")
    if "headingFont" in patch:
        f = str(patch["headingFont"] or "").strip()
        if f:
            typography["fontFamilyHeading"] = f
        else:
            typography.pop("fontFamilyHeading", None)
        changed.append(f"heading font → {f or 'same as text'}")
    if "baseSize" in patch:
        s = str(patch["baseSize"] or "").strip()
        if s and not re.match(r"^\d+(\.\d+)?(px|rem)$", s):
            raise EditorError(422, "bad-size", "The text size is a number of pixels, like 14px.")
        if s:
            typography["baseSize"] = s
        else:
            typography.pop("baseSize", None)
        changed.append(f"text size → {s or 'default'}")
    ds["typography"] = typography
    if "radius" in patch:
        r = str(patch["radius"] or "").strip()
        if not re.match(r"^\d+(\.\d+)?(px|rem)$", r):
            raise EditorError(422, "bad-radius", "Corners are a number of pixels, like 8px.")
        px = float(r[:-2]) if r.endswith("px") else float(r[:-3]) * 16
        radius = dict(ds.get("radius")) if isinstance(ds.get("radius"), dict) else {}
        radius.update({"sm": f"{max(0, round(px / 2))}px", "md": r, "lg": f"{round(px * 1.5)}px"})
        ds["radius"] = radius
        changed.append(f"corners → {r}")
    if "density" in patch:
        d = str(patch["density"] or "")
        if d not in DENSITIES:
            raise EditorError(422, "bad-density", "Density is compact, comfortable or spacious.")
        ds["informationDensity"] = d
        changed.append(f"density → {d}")
    if not changed:
        return get(project)
    label = "Look changed in the editor: " + ", ".join(changed)
    from services.blueprint.orchestrator import DAG
    result = AgentResult(task_id=f"TASK-editor-theme-{uuid.uuid4().hex[:8]}", agent=DAG["design_system"].agent, confidence=1.0,
                         proposals=[ArtifactProposal(section="designSystem", natural_key="designSystem", body=ds)])
    applied = apply_agent_result(svc, result, commit=True, user_request=label)
    if not applied.applied:
        raise EditorError(422, "refused", applied.reason or "That look could not be applied.")
    # The person's choice is the decision on the design system from here on.
    try:
        from services.smith.restyle import record_decision
        record_decision(svc, label)
    except Exception:  # a decision is a courtesy to Smith, not the change itself
        pass
    project_design_tokens(svc.doc, project.app_root)
    return get(project)
