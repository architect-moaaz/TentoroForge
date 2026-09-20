"""One discovery: a URL in, a company profile out.

The three readings run in the order they depend on each other and no further:
the site is read once, the design language is counted off that reading with no
model, the identity is summarised from the same reading with one, and the mark
is fetched from the candidates the reading ranked. Then design.md is rendered
from all of it.

NO DATABASE HERE. The router owns the row; this owns the reading. That split
is what lets the whole discovery be exercised against a fixture `Reading` with
no network and no Postgres in the process — and it is the same split
`services.blueprint` keeps for the same reason.

PARTIAL IS THE NORMAL OUTCOME. A site with no readable mark, or no key to
summarise it with, still has a palette; a site behind a bot wall still has a
title. Every part is optional and the profile records which parts landed, so
Settings can show the person exactly what is missing and offer to fill it in
by hand. The only outright failure is a URL that cannot be fetched at all —
`SiteUnreadable`, whose message is written to be shown verbatim.
"""
from __future__ import annotations

import logging
from typing import Any

from services.brand_discovery import design as design_reader
from services.brand_discovery import design_md, identity as identity_reader
from services.brand_discovery import site as site_reader
from services.brand_discovery.site import SiteUnreadable  # noqa: F401 — re-export

logger = logging.getLogger(__name__)


async def discover(url: str, org_id: str) -> dict[str, Any]:
    """Read `url` and return the fields of an `OrgBrandProfile`.

    Raises `SiteUnreadable` when there was nothing to read at all. Everything
    else that goes wrong shows up as an absent part of the returned profile.
    """
    reading = await site_reader.read(url)

    design, evidence = design_reader.design_system_from(reading)
    identity = await identity_reader.read_identity(reading)
    name = identity_reader.company_name(reading, identity)

    logo_path = None
    got = await site_reader.fetch_logo(reading.logo_candidates)
    if got is not None:
        data, media, found_at = got
        try:
            from services.brand_discovery.store import store_logo

            logo = store_logo(org_id, found_at.split("/")[-1] or "logo", media, data)
            logo["alt"] = f"{name} logo" if name else "Company logo"
            design["logo"] = logo
            logo_path = logo["file"]
            evidence["logoFrom"] = found_at
        except Exception as exc:  # noqa: BLE001 — a company with no mark is fine
            logger.warning("[brand] could not store the mark from %s: %s",
                           found_at, exc)
    else:
        evidence["logoFrom"] = ""

    evidence["logoCandidates"] = reading.logo_candidates

    profile: dict[str, Any] = {
        "source_url": reading.url,
        "company_name": name,
        "logo_path": logo_path,
        "identity": identity,
        "design": design,
        "evidence": evidence,
    }
    profile["design_md"] = design_md.render(profile)
    logger.info("[brand] %s: %d colour roles, identity=%s, logo=%s",
                reading.url, len(design.get("colors") or {}),
                "yes" if identity.get("what_you_do") else "no",
                "yes" if logo_path else "no")
    return profile


def regenerate(profile: dict[str, Any]) -> str:
    """The design.md for an edited profile.

    The seam an edit goes through: Settings changes a colour or rewrites what
    the company does, and the document is re-rendered in the same call rather
    than left to be regenerated later by something that might not run. The
    structure and the document are written together or not at all.
    """
    return design_md.render(profile)
