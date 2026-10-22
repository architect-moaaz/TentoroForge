"""Where a published application runs: its database and its server, as a pair.

The database is a Neon project in an AWS region; the server is Vercel's
functions, in a Vercel region. Each choice pairs a Neon region with the
Vercel region beside it, so a page's queries do not cross an ocean.

The default is what every application had before there was a choice: the
database in AWS us-east-2 (Ohio) and the server wherever Vercel puts it by
default. An organisation picks a default for its applications; an
application may pick its own in the Publish dialog until its database is
made, at its first publish. After that its region is fixed: a Neon project
does not move, and applications are never moved for anyone.

Neon has no Mumbai; Singapore is the nearest for India (Neon's regions, 2026-10).
"""
from __future__ import annotations

from typing import Any

DEFAULT = "default"

#: id → label, Neon region, Vercel region (None: Vercel's own default).
REGIONS: dict[str, dict[str, Any]] = {
    DEFAULT: {"label": "Default — US East (Ohio)", "neon": "aws-us-east-2", "vercel": None},
    "us-east": {"label": "US East (N. Virginia)", "neon": "aws-us-east-1", "vercel": "iad1"},
    "us-west": {"label": "US West (Oregon)", "neon": "aws-us-west-2", "vercel": "pdx1"},
    "eu-frankfurt": {"label": "Europe (Frankfurt)", "neon": "aws-eu-central-1", "vercel": "fra1"},
    "eu-london": {"label": "Europe (London)", "neon": "aws-eu-west-2", "vercel": "lhr1"},
    "ap-singapore": {"label": "Asia Pacific (Singapore) — nearest to India", "neon": "aws-ap-southeast-1",
                     "vercel": "sin1"},
    "ap-sydney": {"label": "Asia Pacific (Sydney)", "neon": "aws-ap-southeast-2", "vercel": "syd1"},
    "sa-sao-paulo": {"label": "South America (São Paulo)", "neon": "aws-sa-east-1", "vercel": "gru1"},
}


def normalise(region: str | None) -> str:
    """A known region id; anything else is refused."""
    rid = str(region or "").strip() or DEFAULT
    if rid not in REGIONS:
        raise ValueError(f"no such region {rid!r} — one of {', '.join(REGIONS)}")
    return rid


def get(region: str | None) -> dict[str, Any]:
    rid = region if region in REGIONS else DEFAULT
    return {"id": rid, **REGIONS[rid]}


def catalogue() -> list[dict[str, Any]]:
    return [{"id": rid, "label": r["label"]} for rid, r in REGIONS.items()]


def org_default(org_settings: dict | None) -> str:
    rid = str((org_settings or {}).get("deploy_region") or "")
    return rid if rid in REGIONS else DEFAULT


def choose(*, locked: bool, app_choice: str | None, org_settings: dict | None) -> str:
    """The region a publish uses. Locked — the application already has its
    database — it is the region it was published in, recorded then, and the
    default for an application published before regions could be chosen."""
    if locked:
        return app_choice if app_choice in REGIONS else DEFAULT
    if app_choice in REGIONS:
        return str(app_choice)
    return org_default(org_settings)


__all__ = ["DEFAULT", "REGIONS", "normalise", "get", "catalogue", "org_default", "choose"]
