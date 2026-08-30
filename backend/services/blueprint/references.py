"""What the user showed Smith — §5, §14, §31.

§5 asks for one engine with several ways of expressing intent, and there are
four in practice: a brief, a specification, an existing design, and reference
screenshots. Three of those are prose, and prose already has a route in —
``_with_evidence`` labels supplied documents and appends them to the
description, so the requirements agent reads a 40-page BRD as evidence rather
than as conversation.

The fourth had nowhere to go. :class:`~services.blueprint.executors.AnthropicModel`
has accepted an image since the montage work and nothing in the graph ever
passed one, so an application described by screenshot was, to every agent,
an application described by silence.

Where they live
---------------
Beside the application, under ``.forge/references/`` — not in the platform's
attachment store. The substrate is constructible from an ``output_dir`` and
nothing else, which is what lets a Blueprint be loaded from a fixture, an
export, or a test with no database in the process. A reference is an input to
*this* application in the same way its conversation is, so it belongs in the
same place. Platform callers copy designated attachments in with :func:`adopt`.

What sees them
--------------
:data:`SEES_REFERENCES`. Not every agent: an image costs real tokens on every
call, and a node that cannot act on what it shows is a node paying for a
picture it must ignore. Requirements and the application model can act on one
— a screenshot of the thing being replaced is a statement about scope, entities
and vocabulary, and reading it is the whole point of having been shown it.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Iterable, Sequence

#: Relative to the application's ``output_dir``.
REFERENCE_DIR = Path(".forge") / "references"

#: What Anthropic accepts, mirrored from ``executors.IMAGE_MEDIA_TYPES``.
#: Stated rather than imported: this module is read by callers that have no
#: business importing the model clients, and the set is a fact about the
#: transport rather than about the executor.
SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})

#: What each node is being shown references *for*.
#:
#: An image is not self-explanatory and it is not equally relevant to everyone.
#: The same screenshot is a statement about scope to the requirements agent and
#: a statement about colour to the design agent, and a single instruction
#: covering both ends up telling one of them to ignore the thing it was shown
#: the picture for — the first version told every node "do not transcribe a
#: layout", which is sound advice for requirements and a refusal of the job for
#: `design_system`.
#:
#: An image costs tokens on every call, so a node absent from this table is not
#: shown one: a node that cannot act on what it shows is paying for a picture it
#: must ignore.
READ_FOR: dict[str, str] = {
    "requirements": (
        "Read them for what they say about the problem — what the system does "
        "today, which screens exist, what a user can act on. Each requirement "
        "you take from an image is still one testable statement of something a "
        "user can do. Do not transcribe a layout: what a page looks like is "
        "not decided at this stage and not by you."
    ),
    "application_model": (
        "Read them for the domain — the vocabulary as it appears on screen, "
        "the labels this business actually uses for its own things, who the "
        "screens are addressed to, what the product is evidently for. A word "
        "on a real screen outranks a synonym you would have chosen: the "
        "generated app should speak the language its users already do."
    ),
    "design_system": (
        "Read them for the design language, which is the one thing here you "
        "are meant to take from a picture: the palette and which colour is "
        "doing which job, the type scale and its weights, how much air the "
        "layout leaves, corner radius, how heavy the borders and shadows are. "
        "Name the colours you read as hex in `colors`, and say in "
        "`visualPersonality` that they came from the reference and what you "
        "read them from. Do not reproduce a specific screen — you are "
        "establishing the language every page inherits, not composing one."
    ),
}

#: Derived, so a node cannot be shown a reference without being told what to
#: read it for. A set maintained beside the table is a set that drifts from it.
SEES_REFERENCES: frozenset[str] = frozenset(READ_FOR)


def directory(output_dir: str | Path) -> Path:
    return Path(output_dir) / REFERENCE_DIR


def paths(output_dir: str | Path) -> list[Path]:
    """The application's reference images, in a stable order.

    Sorted by name, because the order reaches a prompt: an unstable order is a
    different prefix on every run, which costs the cache the montage work
    existed to win.
    """
    root = directory(output_dir)
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.iterdir()
         if p.is_file() and p.suffix.lower() in SUFFIXES),
        key=lambda p: p.name,
    )


def adopt(output_dir: str | Path, sources: Iterable[str | Path]) -> list[Path]:
    """Copy images in, and return what the application now holds.

    Copied rather than referenced. The platform's attachment store is not the
    application's, and a Blueprint exported to a tarball with a path into
    somebody's upload directory is an application that cannot be rebuilt
    anywhere else (§83).

    Silently skips what is not an image this transport accepts. A user who
    attached a PDF to a chat has not made a design reference, and failing the
    whole intake over one of them would lose the three that were.
    """
    root = directory(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    for src in sources:
        src = Path(src)
        if src.suffix.lower() not in SUFFIXES or not src.is_file():
            continue
        target = root / src.name
        if target.resolve() != src.resolve():
            shutil.copyfile(src, target)
    return paths(output_dir)


#: Media type -> the suffix to store it under. An attachment store keyed by id
#: holds blobs with no extension, and the transport decides what it will accept
#: from the suffix, so the type has to be turned back into one on the way in.
MEDIA_SUFFIXES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(name: str, media_type: str, fallback: str) -> str:
    """A file name that is a name and not a path.

    The name comes from an upload, so it is user input reaching a filesystem
    path. Reduced to a single component of a known alphabet, and given the
    suffix the media type implies rather than the one the name claims — a
    ``.png`` that is really a PDF must not be handed to the transport as an
    image.
    """
    stem = _SAFE.sub("-", Path(str(name or "")).name).strip("-.") or fallback
    kind = (media_type or "").split(";")[0].strip()
    if kind:
        # A declared type is the authority and it is checked, not consulted.
        # Falling back to the claimed suffix when the type is one we do not
        # accept is how a PDF named `spec.png` reaches the transport as an
        # image — the name is the half of this that a user chose.
        suffix = MEDIA_SUFFIXES.get(kind, "")
        if not suffix:
            return ""
    else:
        # No type to go on — a real file being adopted by path. The suffix is
        # all there is, and it still has to be one we accept.
        suffix = Path(stem).suffix.lower()
        if suffix not in SUFFIXES:
            return ""
    return Path(stem).stem + suffix


def adopt_bytes(
    output_dir: str | Path, name: str, data: bytes, *,
    media_type: str = "", fallback: str = "reference",
) -> Path | None:
    """Take custody of an image that has no file to copy.

    The platform stores attachments as an id-named blob beside a metadata
    sidecar, so there is nothing on disk with a name or a suffix to hand to
    :func:`adopt`. Returns the stored path, or None when the bytes are not an
    image this transport accepts.
    """
    filename = _safe_name(name, media_type, fallback)
    if not filename:
        return None
    root = directory(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / filename
    target.write_bytes(data)
    return target


def clear(output_dir: str | Path) -> None:
    """Undesignate everything — the user withdrew the reference."""
    root = directory(output_dir)
    if root.is_dir():
        shutil.rmtree(root)


#: Appended to the prompt of a node that is being shown references. Says what
#: the images *are*, because an unlabelled image beside a brief is ambiguous in
#: the expensive direction: an agent that reads a screenshot of the system
#: being replaced as a specification of the system being built will faithfully
#: reproduce a layout nobody asked for.
ADDENDUM = """

## What the user showed you

{count} image{plural} {names} {verb} attached to this request by the user, \
before the text above. They are REFERENCE, not specification: the user is \
showing you something to convey what they mean, and what they mean is stated \
in their words. Where the two disagree, the words win.

{read_for}

Anything you take from an image belongs in that artifact's `evidence` as \
`{{"type": "screenshot", "source": "<the file name>"}}`, so a reader can tell \
what the user said from what you read off a picture. An artifact you inferred \
from an image and did not cite is one nobody can check.
"""


def addendum(references: Sequence[Path], node: str = "") -> str:
    """:data:`ADDENDUM` for these references, or "" when there are none.

    Returns "" for a node with no entry in :data:`READ_FOR` even when
    references are passed. Showing a node an image and then having nothing to
    tell it about why is the case this module exists to prevent, and silently
    falling back to generic advice would hide it.
    """
    read_for = READ_FOR.get(node, "")
    if not references or not read_for:
        return ""
    return ADDENDUM.format(
        count=len(references),
        plural="" if len(references) == 1 else "s",
        names="(" + ", ".join(p.name for p in references) + ")",
        verb="was" if len(references) == 1 else "were",
        read_for=read_for,
    )
