"""When may a domain visual-lock preset be applied to a brief?

The preset is a fallback: it gives an LLM-authored brief a coherent,
pre-vetted palette instead of whatever the model reached for. It is not a
correction, and it must never overwrite colours that were MEASURED from a
source the user pointed at — a Figma file or a design-reference screenshot.

The check the seam used before was `visual_lock.is_active()`, which asks
"has a preset already been applied?" — a different question. Extraction
writes `palette`, never `visual_lock`, so every extracted brief answered
"no" and had its measured palette replaced one step later. Nothing warned;
the app simply came out the preset's colour and looked like the reference
had been ignored.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Sources that mean "these values were read off something real".
_MEASURED_SOURCES = {"figma", "screenshot"}


def should_apply_preset(brief) -> bool:
    """True when a domain preset may set this brief's visual lock.

    False when the brief already carries a lock (idempotence — a re-run must
    not swap one preset for another) or carries extracted evidence, which
    outranks any preset.
    """
    if brief is None:
        return False

    try:
        if brief.visual_lock.is_active():
            return False
    except AttributeError:
        pass

    palette = getattr(brief, "palette", None)
    locked = getattr(palette, "locked_fields", None) or set()
    if locked:
        logger.info(
            "[visual-lock] skipping preset — brief locks %d measured palette "
            "field(s)", len(locked))
        return False

    source = getattr(getattr(brief, "identity", None), "source", "authored")
    if source in _MEASURED_SOURCES:
        logger.info("[visual-lock] skipping preset — brief source=%s", source)
        return False

    return True
