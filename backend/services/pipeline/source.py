"""PlanSource — declares how a generation was initiated + carries
source-specific inputs.

The pipeline used to have two entry-point functions (`_run_relay_pipeline`
for text prompts, `_run_figma_relay_pipeline` for Figma imports) that
duplicated ~3900 lines between them. Phase 1 of the cleanup collapses
those into a single `run_pipeline` that branches per-phase on this class.

Design principles:

- **Immutable.** A generation's source is fixed at kickoff. Downstream
  phases must not mutate it.
- **Two shapes only.** ``text`` and ``figma`` cover every current
  entry-point caller. If a third source ever appears (Notion import,
  screenshot upload), add it here rather than sprouting a third pipeline.
- **Figma fields present iff kind == "figma".** The factory constructors
  enforce this; direct construction is discouraged (use `text()` /
  `figma()`).
- **Never carries LLM prompts / user credentials / anything secret.**
  Downstream phases should read those from env / project settings, not
  from the source. `figma_token` is the one exception — it's needed by
  the Figma REST client mid-pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


PlanSourceKind = Literal["text", "figma"]


@dataclass(frozen=True)
class PlanSource:
    """Where the plan came from + how to author it.

    Prefer the factory methods :meth:`text` and :meth:`figma` over the
    raw constructor — they enforce the "figma fields present iff
    kind == 'figma'" invariant.
    """

    kind: PlanSourceKind

    # Figma-only inputs. Must be None when kind == "text".
    figma_url: Optional[str] = None
    figma_token: Optional[str] = None
    # `figma_context` is the pre-fetched Figma REST payload the design
    # agent uses to extract palette / typography. Populated by the
    # entry-point handler before kicking off the pipeline.
    figma_context: Optional[dict] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.kind == "text":
            if any((self.figma_url, self.figma_token, self.figma_context)):
                raise ValueError(
                    "PlanSource(kind='text') must not carry figma_* fields"
                )
        elif self.kind == "figma":
            if not self.figma_url:
                raise ValueError(
                    "PlanSource(kind='figma') requires figma_url"
                )
            # figma_token + figma_context may legitimately be None early
            # in the request (e.g. public Figma files, no pre-fetch yet)
            # so we don't require them here — downstream phases guard.
        else:  # pragma: no cover — Literal narrows this out at type-check
            raise ValueError(f"unknown PlanSource kind: {self.kind!r}")

    @property
    def is_figma(self) -> bool:
        return self.kind == "figma"

    @property
    def is_text(self) -> bool:
        return self.kind == "text"

    # ---- factory constructors -------------------------------------------------

    @staticmethod
    def text() -> "PlanSource":
        """Text-prompt-driven generation. No Figma inputs."""
        return PlanSource(kind="text")

    @staticmethod
    def figma(
        *,
        url: str,
        token: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> "PlanSource":
        """Figma-driven generation. `url` is the only required Figma
        input at construction; token + context can be attached later
        via :meth:`with_context` if the entry-point handler fetches them
        after kickoff.
        """
        return PlanSource(
            kind="figma",
            figma_url=url,
            figma_token=token,
            figma_context=context,
        )

    def with_context(self, context: dict) -> "PlanSource":
        """Return a copy carrying the fetched figma_context. Immutable —
        never mutates ``self``. No-op when called on a text source
        (returns ``self`` unchanged, since text sources ignore context)."""
        if self.is_text:
            return self
        return PlanSource(
            kind="figma",
            figma_url=self.figma_url,
            figma_token=self.figma_token,
            figma_context=context,
        )
