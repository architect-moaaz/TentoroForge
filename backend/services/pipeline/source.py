"""PlanSource — declares how a generation was initiated + carries the
source-specific inputs.

The pipeline used to have two entry-point functions (`_run_relay_pipeline`
for text prompts, `_run_figma_relay_pipeline` for Figma imports). Phase 1
of the cleanup collapsed those behind a single `run_pipeline` that
dispatches on this class; the design-source work made the import half
provider-neutral, so a third kind is a new adapter in
:mod:`services.design_source`, not a third pipeline.

Design principles:

- **Immutable.** A generation's source is fixed at kickoff. Downstream
  phases must not mutate it.
- **Three kinds.** ``text`` for prompts, ``figma`` and ``uxpilot`` for
  imported designs. The design kinds share every field; only the adapter
  behind them differs.
- **Design fields present iff the kind is a design.** The factory
  constructors enforce this; direct construction is discouraged.
- **Never carries anything that must not be logged.** ``secret`` (a Figma
  personal token, or an API key resolved from the encrypted MCP-server
  row) is excluded from ``repr`` and must never be persisted; the
  pipeline reads it once to build the adapter. ``credential_id`` is the
  durable reference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


PlanSourceKind = Literal["text", "figma", "uxpilot"]
DESIGN_KINDS: tuple[str, ...] = ("figma", "uxpilot")


@dataclass(frozen=True)
class PlanSource:
    """Where the plan came from + how to author it.

    Prefer the factory methods :meth:`text`, :meth:`figma` and
    :meth:`uxpilot` over the raw constructor — they enforce the
    "design fields present iff the kind is a design" invariant.
    """

    kind: PlanSourceKind

    #: Figma design URL · UX Pilot page id. Required for design kinds.
    design_ref: Optional[str] = None
    #: PlatformMcpServer row id (UX Pilot). The durable credential handle.
    credential_id: Optional[str] = None
    #: Figma personal token · resolved UX Pilot API key. Not persisted, not
    #: shown. Needed mid-pipeline by the provider's client.
    secret: Optional[str] = field(default=None, repr=False)
    #: The persisted design context (tokens) when the entry point already
    #: fetched it. Large; hidden from repr so SSE logs stay readable.
    design_context: Optional[dict] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.kind == "text":
            if any((self.design_ref, self.credential_id, self.secret, self.design_context)):
                raise ValueError(
                    "PlanSource(kind='text') must not carry design fields"
                )
        elif self.kind in DESIGN_KINDS:
            if not self.design_ref:
                raise ValueError(
                    f"PlanSource(kind={self.kind!r}) requires design_ref"
                )
        else:  # pragma: no cover — Literal narrows this out at type-check
            raise ValueError(f"unknown PlanSource kind: {self.kind!r}")

    # ---- predicates -------------------------------------------------------

    @property
    def is_text(self) -> bool:
        return self.kind == "text"

    @property
    def is_design(self) -> bool:
        return self.kind in DESIGN_KINDS

    @property
    def is_figma(self) -> bool:
        return self.kind == "figma"

    @property
    def is_uxpilot(self) -> bool:
        return self.kind == "uxpilot"

    @property
    def provider(self) -> Optional[str]:
        """The design provider, or None for a text source."""
        return self.kind if self.is_design else None

    # ---- Figma-era names ---------------------------------------------------
    # routers.generate still reads these at ~40 sites. They resolve only for
    # a Figma source so a UX Pilot import can never be mistaken for one.

    @property
    def figma_url(self) -> Optional[str]:
        return self.design_ref if self.is_figma else None

    @property
    def figma_token(self) -> Optional[str]:
        return self.secret if self.is_figma else None

    @property
    def figma_context(self) -> Optional[dict]:
        return self.design_context if self.is_figma else None

    # ---- factory constructors -------------------------------------------------

    @staticmethod
    def text() -> "PlanSource":
        """Text-prompt-driven generation. No design inputs."""
        return PlanSource(kind="text")

    @staticmethod
    def figma(
        *,
        url: str,
        token: Optional[str] = None,
        context: Optional[dict] = None,
        credential_id: Optional[str] = None,
    ) -> "PlanSource":
        """Figma-driven generation. `url` is the only required input at
        construction; token + context can be attached later via
        :meth:`with_context` if the entry-point handler fetches them
        after kickoff. `credential_id` names the org's Figma MCP-server
        row the token came from, when it did.
        """
        return PlanSource(
            kind="figma", design_ref=url, secret=token, design_context=context,
            credential_id=credential_id,
        )

    @staticmethod
    def uxpilot(
        *,
        page_id: str,
        credential_id: Optional[str] = None,
        secret: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> "PlanSource":
        """UX Pilot-driven generation. `page_id` names the UX Pilot page;
        `credential_id` is the org's MCP-server row and `secret` the key
        resolved from it for this run."""
        return PlanSource(
            kind="uxpilot", design_ref=page_id, credential_id=credential_id,
            secret=secret, design_context=context,
        )

    def with_context(self, context: dict) -> "PlanSource":
        """Return a copy carrying the fetched design context. Immutable —
        never mutates ``self``. No-op on a text source."""
        if self.is_text:
            return self
        return PlanSource(
            kind=self.kind,
            design_ref=self.design_ref,
            credential_id=self.credential_id,
            secret=self.secret,
            design_context=context,
        )
