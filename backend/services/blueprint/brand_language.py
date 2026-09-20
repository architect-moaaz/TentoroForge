"""The company's design language, beside the application it is building.

The profile lives in the platform's database, on the organisation. The
Blueprint substrate is constructible from an `output_dir` and nothing else —
no database, no network — and that property is what lets a Blueprint load from
a fixture, an export or a test. So the language is COPIED in at the start of a
run, exactly as `services.blueprint.references` copies designated uploads and
`documents` copies supplied specifications, and everything downstream reads it
off disk.

Three files, because three different things read them:

    .forge/brand/design.md      the prose the agents are shown
    .forge/brand/design.json    the tokens the projection merges
    brand/<digest>.<ext>        the mark, where `brand_logo` already keeps one

WHY THE DOCUMENT AND THE TOKENS ARE BOTH HERE. The tokens are applied by code
— `brand_design_system` merges them over `designSystem`, deterministically,
because a hex is a fact and a model asked to honour one can only restate it.
The document is for the decisions no token can carry: the vocabulary this
company uses for its own things, how its writing sounds, what it says it does.
Those reach the agents that can act on them as an addendum, the same seam a
supplied specification arrives through.

RE-ADOPTED ON EVERY RUN, AND CLEARED FIRST. A company that redesigns runs
discovery again, and the next build must not merge yesterday's palette over
today's. Clearing also does the other half: an application whose owner
switches from `company` to `custom` has the language taken back off, so the
choice is reversible rather than a thing that happened once.

NOTHING HERE DECIDES WHETHER TO USE IT. `application.designLanguage` is that
decision and the user makes it (`services.smith.design_language`). This module
is the transport.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BRAND_DIR = Path(".forge") / "brand"
DOCUMENT = "design.md"
TOKENS = "design.json"

#: What each node is being shown the company's language FOR.
#:
#: The same table shape as `references.READ_FOR`, and for the same reason: a
#: document is not self-explanatory and it is not equally relevant to
#: everyone. The design agent must be told the palette is not a suggestion;
#: the product agent must be told the opposite about the business summary —
#: that it describes the COMPANY and not the application being built, which is
#: the mistake that turns "we make surgical instruments" into a requirement.
#:
#: A node absent from this table is not shown the document. Prose costs tokens
#: on every call, and a node that cannot act on what it says is paying to
#: ignore it.
READ_FOR: dict[str, str] = {
    "requirements": (
        "Read it for the business and its vocabulary — what this company "
        "does, who it serves, what it calls its own things. It is context "
        "for understanding the request, NOT a source of requirements: "
        "nothing in it is something the application must do. A requirement "
        "comes from what the user asked for."
    ),
    "application_model": (
        "Read it for the domain and the language. The company's own words "
        "for its own things are the words this application should use — a "
        "term from here outranks a synonym you would have chosen. The voice "
        "described here is the voice of the application's copy. What the "
        "company does is not what this application does; take vocabulary and "
        "tone from it, not scope."
    ),
    "design_system": (
        "This is the design language, and it is the answer rather than "
        "evidence towards one. Where it states a colour role, a typeface, a "
        "corner radius or a density, use that value — it was read off this "
        "company's own site and the user chose to build in it. You still own "
        "everything it does not state: accessibility rules, responsive "
        "rules, interaction conventions, and any role it leaves open. Say in "
        "`visualPersonality` that the palette is the company's."
    ),
}

SEES_BRAND: frozenset[str] = frozenset(READ_FOR)


def directory(output_dir: str | Path) -> Path:
    return Path(output_dir) / BRAND_DIR


def available(output_dir: str | Path) -> bool:
    """Whether a company design language has been adopted into this build."""
    return (directory(output_dir) / DOCUMENT).is_file()


def document(output_dir: str | Path) -> str:
    """The adopted design.md, or ""."""
    path = directory(output_dir) / DOCUMENT
    try:
        return path.read_text("utf-8") if path.is_file() else ""
    except OSError:
        return ""


def tokens(output_dir: str | Path) -> dict[str, Any]:
    """The adopted `designSystem` overlay, or {}.

    Returns {} rather than raising on a malformed file: a design language that
    cannot be read is a build that proceeds without one, not a failed
    generation. The projection node logs it.
    """
    path = directory(output_dir) / TOKENS
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("[brand] %s is not readable JSON; ignoring", path)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def clear(output_dir: str | Path) -> None:
    """Take any adopted language back off. Safe when there is none."""
    shutil.rmtree(directory(output_dir), ignore_errors=True)


def adopt(output_dir: str | Path, *, design_md: str, design: dict,
          company_name: str = "", logo_bytes: bytes | None = None,
          logo_name: str = "", logo_media: str = "") -> dict[str, Any]:
    """Copy one organisation's language in. Returns what was adopted.

    The logo is re-stored rather than referenced: `designSystem.logo.file` is
    a path relative to THIS application's output directory, and a path into
    the platform's brand store is an application that cannot be exported,
    rebuilt on another machine, or shipped (§83).
    """
    clear(output_dir)
    root = directory(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    overlay = {k: v for k, v in (design or {}).items() if k != "logo"}
    # Underscored, and stripped before the merge. The company's NAME is not a
    # design token and must never reach `designSystem` as one — it is carried
    # here only so the projection can say whose language it just applied,
    # without that node needing a database it deliberately cannot reach.
    if company_name:
        overlay["_companyName"] = company_name

    if logo_bytes:
        from services import brand_logo

        try:
            stored = brand_logo.store(output_dir, logo_name or "logo",
                                      logo_media, logo_bytes)
            alt = str(((design or {}).get("logo") or {}).get("alt") or "")
            if alt:
                stored["alt"] = alt
            overlay["logo"] = stored
        except Exception as exc:  # noqa: BLE001 — a mark is not the language
            logger.warning("[brand] logo not adopted: %s", exc)

    (root / DOCUMENT).write_text(design_md or "", "utf-8")
    (root / TOKENS).write_text(
        json.dumps(overlay, indent=2, sort_keys=True) + "\n", "utf-8")
    logger.info("[brand] adopted into %s: %d token groups, %d chars of design.md",
                output_dir, len(overlay), len(design_md or ""))
    return overlay


def chosen(doc: dict | None) -> bool:
    """Whether this application is being built in the company's language.

    The one place that question is answered, so a caller cannot get it subtly
    wrong: absent means unasked, and unasked means no — an application must
    never inherit a company's palette because nobody got round to offering
    the choice.
    """
    return str(((doc or {}).get("application") or {})
               .get("designLanguage") or "") == "company"


def addendum(output_dir: str | Path, node: str, doc: dict | None = None) -> str:
    """The block appended to `node`'s prompt, or "".

    Empty three ways, all of them silent: the node cannot act on it, nothing
    was adopted, or the owner chose a design of this application's own. The
    call site therefore needs no condition, which is what keeps this from
    being a flag some node forgets to check.

    `doc` is required in practice — omitting it reads as "not chosen", which
    is the safe direction: a build that forgets to pass the document produces
    an application that ignores the company language, not one that adopts it
    against the owner's answer.
    """
    instruction = READ_FOR.get(node)
    if not instruction or not chosen(doc):
        return ""
    text = document(output_dir)
    if not text.strip():
        return ""
    return (
        "\n\nTHE COMPANY'S DESIGN LANGUAGE — the organisation this "
        "application is being built for has one on record, and the user chose "
        "to build this application in it. " + instruction +
        "\n\n--- design.md ---\n" + text.strip() + "\n--- end design.md ---\n"
    )
