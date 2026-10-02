"""Company discovery — who a company is, and what it looks like.

    site.read          -> Reading         a rendered page, counted
    design.design_system_from -> design    the census as tokens, no model
    identity.read_identity    -> identity  the three answers, one model call
    design_md.render          -> str       design.md, deterministic
    run.discover              -> profile   all four, for one URL
    store.store_logo          -> BrandLogo the mark, kept by the organisation

The profile this produces belongs to the organisation (`models.brand_profile`).
What a *build* does with it is `services.blueprint.brand_language`, and whether
a given application uses it at all is `services.smith.design_language` — asked
once, at the approval gate.
"""
from services.brand_discovery.run import SiteUnreadable, discover, regenerate

__all__ = ["discover", "regenerate", "SiteUnreadable"]
