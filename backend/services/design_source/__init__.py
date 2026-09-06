"""Design sources — the four things an imported design supplies.

A design import used to mean "Figma": one page per frame, tokens from a
styles tree, JSX per frame from Dev Mode, assets from Figma's CDN. Every
one of those is consumed downstream under provider-neutral names — a plan,
a design brief, PageV2 schemas, cached assets — so the provider is an
adapter behind one contract, not a pipeline of its own.

:class:`DesignSource` is that contract. :mod:`figma` and :mod:`uxpilot` are
the two adapters. Decision 25 (BLUEPRINT.md Appendix C) records why the
Blueprint names a provider rather than Figma.
"""
from services.design_source.base import (  # noqa: F401
    DesignMarkup,
    DesignPage,
    DesignScope,
    DesignSource,
    DesignSourceError,
    DesignTokens,
    Provider,
    PROVIDERS,
)
