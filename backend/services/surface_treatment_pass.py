"""IRF-M6-T4 — deterministic surface treatment pass.

Post-generation, zero-LLM pass that paints the chosen aesthetic
profile's ``surface_treatment`` rules onto the emitted page + shell
schemas + the app's ``globals.css``.

What it does:

1. Pick the aesthetic profile via
   ``services.aesthetic_profile_picker.pick(plan)``.
2. Inject the profile's ``css_variables`` into
   ``src/app/globals.css`` under an ``.aesthetic-<name>`` scope so
   they only apply when the root layout carries that class.
3. Add ``aesthetic-<name>`` to the root layout's ``<body>`` class.
4. Walk every ``src/schemas/*.json`` and layer the profile's
   ``surface_treatment`` hints:
   - ``root`` → the page schema's outermost Stack/Section gets
     ``style.background`` from the profile's root rule.
   - ``card`` → every ``Card`` node gets ``style`` merged from the
     profile's card rule (boxShadow / backdropFilter / borderRadius).
   - ``button.primary`` → every ``Button`` with ``variant=primary``
     gets the profile's button rule (boxShadow / borderRadius).
   - ``heading.h1`` → every ``Heading`` with ``level=1`` gets the
     profile's heading rule (fontFamily / letterSpacing).

Idempotent — the injected marker + node style keys are stable across
runs. Safe to invoke unconditionally from ``post_generate_fixes``.

Flag: ``FORGE_SURFACE_TREATMENT`` (default off). When off, returns
``{"applied": False, "reason": "flag-disabled"}`` and touches nothing.
Lets pipelines wire the pass without visual side-effects until we
flip the flag.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from services.aesthetic_profile_picker import pick_profile

logger = logging.getLogger(__name__)


# ── flag ────────────────────────────────────────────────────────────


def is_enabled() -> bool:
    return os.getenv("FORGE_SURFACE_TREATMENT", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ── globals.css injection ───────────────────────────────────────────


_CSS_MARKER = "/* IRF-M6-T4 aesthetic-scope injected */"


def _render_css_scope(profile_name: str, css_vars: dict[str, str]) -> str:
    lines = [f".aesthetic-{profile_name} {{"]
    for var, val in css_vars.items():
        lines.append(f"  {var}: {val};")
    lines.append("}")
    return "\n".join(lines)


def _inject_globals_css(output_dir: Path, profile: dict) -> bool:
    css_path = output_dir / "src" / "app" / "globals.css"
    if not css_path.is_file():
        return False
    name = profile.get("name") or ""
    vars_map = profile.get("css_variables") or {}
    if not name or not isinstance(vars_map, dict) or not vars_map:
        return False
    text = css_path.read_text(encoding="utf-8")
    scope = _render_css_scope(name, vars_map)
    marker = f"{_CSS_MARKER} name={name}"

    if marker in text:
        return False  # already applied for this profile

    # Strip any prior IRF injection so switching profiles is clean
    text = re.sub(
        rf"\n?{re.escape(_CSS_MARKER)} name=\S+\n\.aesthetic-\S+ \{{[^}}]*\}}\n?",
        "\n",
        text,
    )

    new_text = text.rstrip() + f"\n\n{marker}\n{scope}\n"
    css_path.write_text(new_text, encoding="utf-8")
    return True


# ── layout.tsx: add aesthetic-<name> to <body> class ────────────────


def _add_body_class(output_dir: Path, profile_name: str) -> bool:
    layout_path = output_dir / "src" / "app" / "layout.tsx"
    if not layout_path.is_file():
        return False
    text = layout_path.read_text(encoding="utf-8")
    target = f"aesthetic-{profile_name}"
    if target in text:
        return False

    # Strip any prior aesthetic-* class first (idempotent profile swap)
    text = re.sub(r"\baesthetic-[a-z0-9-]+\b", "", text)

    # Prefer: <body className="...">
    def _augment(match: "re.Match[str]") -> str:
        existing = match.group(1).strip()
        prefix = match.group(0)[: match.start(1) - match.start()]
        suffix = match.group(0)[match.end(1) - match.start():]
        merged = (existing + " " + target).strip()
        merged = re.sub(r"\s+", " ", merged)
        return prefix + merged + suffix

    m = re.search(r'<body\b[^>]*\bclassName=\{?["`]([^"`]*)["`]\}?', text)
    if m:
        new_text = text[: m.start()] + _augment(m) + text[m.end():]
    else:
        # Fallback: inject className on the <body> tag
        new_text = re.sub(
            r'<body\b',
            f'<body className="{target}"',
            text,
            count=1,
        )
        if new_text == text:
            return False
    layout_path.write_text(new_text, encoding="utf-8")
    return True


# ── schema tree walk + surface hints ────────────────────────────────


def _iter_nodes(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)


_PADDING_TOKENS = ("p-", "px-", "py-", "pl-", "pr-", "pt-", "pb-")
_TINT_PADDING_CLASS = "px-6 py-6 md:px-8 md:py-8"


def _ensure_tinted_root_padding(root: dict) -> bool:
    """Add horizontal + vertical padding to a tinted page root Stack when it
    has none. Prevents child Cards from hugging the tinted well's edges.

    Idempotent: skips if the root already declares any ``p-*`` utility, an
    explicit ``padding`` prop, or a ``style.padding`` value.
    """
    props = root.setdefault("props", {})
    existing_class = str(props.get("className") or "")
    if any(tok in existing_class for tok in _PADDING_TOKENS):
        return False
    if props.get("padding") or props.get("p"):
        return False
    style = props.get("style") or {}
    if isinstance(style, dict) and (style.get("padding") or style.get("paddingLeft")
                                     or style.get("paddingRight")):
        return False
    props["className"] = (existing_class + " " + _TINT_PADDING_CLASS).strip()
    return True


def _merge_style(node: dict, style_hint: dict) -> bool:
    if not style_hint:
        return False
    props = node.setdefault("props", {})
    style = props.setdefault("style", {})
    changed = False
    for k, v in style_hint.items():
        if style.get(k) != v:
            style[k] = v
            changed = True
    return changed


def _apply_to_schema(schema: dict, treatment: dict) -> int:
    """Return count of nodes touched."""
    touched = 0
    root_hint = treatment.get("root") or {}
    card_hint = treatment.get("card") or {}
    button_hint = treatment.get("button.primary") or {}
    heading_hint = treatment.get("heading.h1") or {}

    root = schema.get("root")
    if isinstance(root, dict) and root_hint:
        if _merge_style(root, root_hint):
            touched += 1
        # When we paint the root with a tinted background, the tinted well
        # would otherwise hug the outer layout's padding — cards inside touch
        # its left/right edges (screenshots B-XXX). Add horizontal + vertical
        # padding on the root itself so children float inside the tint with
        # breathing room. Only added when the root doesn't already declare
        # padding via className/props (idempotent, respects prior authoring).
        if _ensure_tinted_root_padding(root):
            touched += 1

    for node in _iter_nodes(schema.get("root")):
        if not isinstance(node, dict):
            continue
        t = node.get("type")
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        if t == "Card" and card_hint:
            if _merge_style(node, card_hint):
                touched += 1
        elif t == "Button" and button_hint and props.get("variant") == "primary":
            if _merge_style(node, button_hint):
                touched += 1
        elif t == "Heading" and heading_hint and props.get("level") in (1, "1", "h1"):
            if _merge_style(node, heading_hint):
                touched += 1
    return touched


def _apply_to_all_schemas(output_dir: Path, treatment: dict) -> tuple[int, int]:
    """Returns (files_written, nodes_touched)."""
    sdir = output_dir / "src" / "schemas"
    if not sdir.is_dir():
        return (0, 0)
    files_written = 0
    nodes_touched = 0
    for p in sorted(sdir.glob("**/*.json")):
        if p.name in ("nav-flow.json",):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        touched = _apply_to_schema(data, treatment)
        if touched:
            try:
                p.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                             encoding="utf-8")
                files_written += 1
                nodes_touched += touched
            except Exception:  # noqa: BLE001
                logger.debug("[surface_treatment_pass] write failed %s", p, exc_info=True)
    return (files_written, nodes_touched)


# ── public API ──────────────────────────────────────────────────────


def apply(output_dir: str | Path, plan: dict[str, Any] | None) -> dict[str, Any]:
    """Apply the surface-treatment pass to a generated app.

    Returns a report ``{applied, profile, files, nodes, css_written,
    body_class_added, reason?}``. Never raises.

    Historic behavior is preserved when the flag is off (returns
    ``applied=False`` with reason=flag-disabled).
    """
    if not is_enabled():
        return {"applied": False, "reason": "flag-disabled"}

    root = Path(output_dir) if isinstance(output_dir, str) else output_dir
    if not root.is_dir():
        return {"applied": False, "reason": "output_dir-missing"}

    # Load the design brief (if any) so the picker can veto brutalist
    # skins on calm-tone briefs. Best-effort — a missing brief just
    # means no veto signal.
    brief_for_pick = None
    try:
        from services.design_brief_to_prompt import load_brief_from_disk
        brief_for_pick = load_brief_from_disk(root)
    except Exception:  # noqa: BLE001
        brief_for_pick = None

    profile = pick_profile(plan or {}, brief=brief_for_pick)
    if not profile:
        return {"applied": False, "reason": "no-profile"}
    profile_name = profile.get("name") or "unknown"

    treatment = profile.get("surface_treatment") or {}

    css_written = _inject_globals_css(root, profile)
    body_class_added = _add_body_class(root, profile_name)
    files, nodes = _apply_to_all_schemas(root, treatment)

    return {
        "applied": True,
        "profile": profile_name,
        "files": files,
        "nodes": nodes,
        "css_written": css_written,
        "body_class_added": body_class_added,
    }


__all__ = ["apply", "is_enabled"]
