"""Guarantee the light-theme `:root` in a generated app's globals.css defines the
full standard token set.

The design agent often emits a COMPLETE `.dark` block but an INCOMPLETE light
`:root` — missing `--foreground`, `--border`, `--input`, `--muted-foreground`,
and the `*-foreground` pairs. In the default (light) theme those vars are then
undefined, so `border: 1px solid hsl(var(--border))` resolves to an invalid color
and the browser falls back to `currentColor` (the dark text) — producing harsh
near-black borders on every card/table/panel.

This fills any missing standard token in `:root` with a light-appropriate default
(deriving `--ring` from `--primary`), so surfaces render with subtle light borders.
Idempotent; only adds tokens that are absent.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Light-theme defaults (HSL channel triplets, matching the `H S% L%` var format).
_LIGHT_DEFAULTS = {
    "--foreground": "215 25% 17%",
    "--card-foreground": "215 25% 17%",
    "--popover": "0 0% 100%",
    "--popover-foreground": "215 25% 17%",
    "--primary-foreground": "0 0% 100%",
    "--secondary-foreground": "0 0% 100%",
    "--accent-foreground": "0 0% 100%",
    "--destructive-foreground": "0 0% 100%",
    "--muted-foreground": "215 16% 47%",
    "--border": "214 18% 89%",
    "--input": "214 18% 89%",
    "--ring": "215 20% 65%",
    "--surface-hover": "180 9% 95%",
}


def complete_light_theme(output_dir: str | Path) -> dict:
    base = Path(output_dir)
    css_path = base / "src" / "app" / "globals.css"
    if not css_path.exists():
        return {"completed": False, "reason": "no globals.css"}

    css = css_path.read_text(encoding="utf-8")
    m = re.search(r":root\s*\{([^}]*)\}", css)
    if not m:
        return {"completed": False, "reason": "no :root block"}

    body = m.group(1)
    present = set(re.findall(r"(--[\w-]+)\s*:", body))
    if "--foreground" in present and "--border" in present:
        return {"completed": False, "reason": "already complete"}

    # Derive --ring from --primary when available (focus ring should echo brand).
    primary = re.search(r"--primary\s*:\s*([^;]+);", body)
    defaults = dict(_LIGHT_DEFAULTS)
    if primary and "--ring" not in present:
        defaults["--ring"] = primary.group(1).strip()

    additions = [f"  {k}: {v};" for k, v in defaults.items() if k not in present]
    if not additions:
        return {"completed": False, "reason": "nothing missing"}

    new_body = body.rstrip() + "\n  /* light-theme floor (auto-completed) */\n" + "\n".join(additions) + "\n"
    new_css = css[:m.start(1)] + new_body + css[m.end(1):]
    css_path.write_text(new_css, encoding="utf-8")
    logger.info("[theme-tokens] completed light :root with %d missing token(s)", len(additions))
    return {"completed": True, "added": len(additions), "tokens": [a.strip() for a in additions]}


# The three Tailwind directives that make the utility layer exist. Hand-written
# pages (login/signup) are pure Tailwind; without these, every utility class
# produces no CSS and the page renders unstyled ("distorted").
_TAILWIND_DIRECTIVES = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"


def ensure_tailwind_directives(output_dir: str | Path) -> dict:
    """Guarantee globals.css carries the `@tailwind base/components/utilities`
    directives. The design LLM is told to write them but sometimes omits them
    (variance), which silently disables Tailwind for the whole app — so all
    hand-written Tailwind pages (login, signup) render unstyled.

    Inserts them AFTER any leading `@import` lines (CSS requires @import first)
    and before the rest of the file. Idempotent; a no-op when already present.
    """
    css_path = Path(output_dir) / "src" / "app" / "globals.css"
    if not css_path.exists():
        return {"inserted": False, "reason": "no globals.css"}
    css = css_path.read_text(encoding="utf-8")
    if "@tailwind" in css:
        return {"inserted": False, "reason": "already present"}

    lines = css.splitlines(keepends=True)
    # Find the insertion point: after the contiguous leading run of @import /
    # blank / comment lines (so the directives sit right after the font @import).
    idx = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("@import") or s == "" or s.startswith("/*") or s.startswith("*"):
            idx = i + 1
        else:
            break
    block = _TAILWIND_DIRECTIVES + ("\n" if idx < len(lines) and lines[idx].strip() else "")
    new_css = "".join(lines[:idx]) + block + "".join(lines[idx:])
    css_path.write_text(new_css, encoding="utf-8")
    logger.info("[theme-tokens] inserted missing @tailwind directives into globals.css")
    return {"inserted": True}
