"""The DesignSource contract: scope, tokens, markup, assets.

Field names match what the pipeline already reads. ``DesignTokens.as_dict``
is the ``design_tokens`` dict :func:`services.brief_from_figma.brief_from_figma`
takes; :meth:`DesignScope.to_plan` is the plan shape
:func:`services.figma_plan_builder.build_plan_from_figma` returned. Adapters
map into these and nothing downstream learns a provider's vocabulary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Provider = Literal["figma", "uxpilot"]
PROVIDERS: tuple[str, ...] = ("figma", "uxpilot")

#: ``jsx`` — Figma Dev Mode; ``html`` — UX Pilot; ``schema`` — a PageV2 tree
#: the provider already built (Figma's REST node tree mapped deterministically
#: when Dev Mode is not reachable), serialised as JSON.
MarkupKind = Literal["jsx", "html", "schema"]


class DesignSourceError(RuntimeError):
    """The provider could not supply one of the four inputs."""


def route_slug(route: str) -> str:
    """``/`` → ``home``; ``/orders/[id]`` → ``orders-[id]``. Same rule the
    Figma mapper and binding pass use for schema file names."""
    return route.strip("/").replace("/", "-") or "home"


@dataclass(frozen=True)
class DesignPage:
    route: str
    title: str
    #: Figma node id ``"220:144"`` · UX Pilot design id.
    ref: str
    #: The plan's page-type vocabulary (auth/dashboard/list/detail/form/error)
    #: or None when the provider gives no signal.
    kind: str | None = None
    #: UX Pilot page prompt / AI context. Empty for Figma.
    prompt: str = ""
    preview_url: str | None = None


@dataclass(frozen=True)
class DesignScope:
    provider: Provider
    #: Figma file key · UX Pilot page id.
    container: str
    name: str
    pages: tuple[DesignPage, ...]
    #: UX Pilot sitemap / journey diagrams; empty for Figma.
    flows: tuple[dict, ...] = ()
    #: Where the design lives, for the plan's provenance and commit messages.
    ref: str = ""

    def to_plan(self) -> dict[str, Any]:
        """The plan dict the pipeline consumes.

        Keeps the Figma keys (``figma_node_id``, ``figma_file_key``,
        ``_figma_driven``) beside the provider-neutral ones while the
        Figma-only phases still read them.
        """
        pages: list[dict[str, Any]] = []
        for p in self.pages:
            entry: dict[str, Any] = {
                "route": p.route,
                "name": p.title,
                "design_ref": p.ref,
                "type": p.kind,
                "file": f"src/schemas/{route_slug(p.route)}.json",
                "entity": None,
            }
            if p.prompt:
                entry["prompt"] = p.prompt
            if self.provider == "figma":
                entry["figma_node_id"] = p.ref
            pages.append(entry)

        plan: dict[str, Any] = {
            "pages": pages,
            "name": self.name or "Untitled",
            "design": {
                "provider": self.provider,
                "container": self.container,
                "ref": self.ref,
            },
            "_design_driven": True,
        }
        if self.flows:
            plan["design"]["flows"] = [dict(f) for f in self.flows]
        if self.provider == "figma":
            plan["figma_file_key"] = self.container
            plan["figma_url"] = self.ref
            plan["_figma_driven"] = True
        return plan


@dataclass(frozen=True)
class DesignTokens:
    """The raw measured vocabulary of a design. Role assignment (which
    colour is the brand) belongs to the brief aggregator, not here."""

    colors: tuple[str, ...] = ()
    fonts: tuple[str, ...] = ()
    font_sizes: tuple[float, ...] = ()
    border_radii: tuple[float, ...] = ()
    spacings: tuple[float, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.colors or self.fonts or self.font_sizes
                    or self.border_radii or self.spacings)

    def as_dict(self) -> dict[str, list]:
        """The ``design_tokens`` dict ``brief_from_figma`` and the design
        context file take. Sorted and deduplicated so two adapters that saw
        the same design write the same bytes."""
        return {
            "colors": sorted(set(self.colors)),
            "fonts": sorted(set(self.fonts)),
            "font_sizes": sorted(set(self.font_sizes)),
            "border_radii": sorted(set(self.border_radii)),
            "spacings": sorted(set(self.spacings)),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "DesignTokens":
        d = d or {}

        def _nums(key: str) -> tuple[float, ...]:
            return tuple(float(v) for v in (d.get(key) or [])
                         if isinstance(v, (int, float)))

        return cls(
            colors=tuple(str(c) for c in (d.get("colors") or [])),
            fonts=tuple(str(f) for f in (d.get("fonts") or [])),
            font_sizes=_nums("font_sizes"),
            border_radii=_nums("border_radii"),
            spacings=_nums("spacings"),
        )

    def merged(self, other: "DesignTokens") -> "DesignTokens":
        return DesignTokens(
            colors=self.colors + other.colors,
            fonts=self.fonts + other.fonts,
            font_sizes=self.font_sizes + other.font_sizes,
            border_radii=self.border_radii + other.border_radii,
            spacings=self.spacings + other.spacings,
        )


@dataclass(frozen=True)
class DesignMarkup:
    ref: str
    kind: MarkupKind
    source: str
    #: Remote asset URLs referenced by the markup, for the downloader.
    asset_urls: tuple[str, ...] = field(default=())
    #: A rendering of the page, for the schema refiner's eyes. Absent when the
    #: provider has none or the markup is already exact.
    preview_url: str | None = None
    #: Nodes the deterministic mapping could not classify (``schema`` kind).
    incomplete: int = 0


@runtime_checkable
class DesignSource(Protocol):
    """One provider's answers to the four questions the pipeline asks."""

    provider: Provider
    #: Figma file key · UX Pilot page id.
    container: str

    async def scope(self) -> DesignScope: ...

    async def tokens(self) -> DesignTokens: ...

    async def markup(self, ref: str) -> DesignMarkup | None: ...

    async def assets(
        self, urls: list[str], output_dir: str, project_id: str | None = None,
    ) -> dict[str, str]: ...
