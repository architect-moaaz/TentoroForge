"""The platform's features, per organisation: what each one is, whether it
is on, and the door that refuses it when it is not.

Everything is on unless it takes an app's source code out of the platform.
The super admin changes a feature for one organisation, or its default for
every organisation that has no setting of its own, from the cockpit; each
change carries a reason and lands in the audit trail. A feature that is
off is still shown to the organisation — locked, with a note saying who
can open it — and the API refuses it with 403.

Resolution, most specific first: the organisation's own setting, then the
platform's default setting, then the catalogue.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.features import FeatureSetting
from models.project import Project

PLATFORM = "platform"
ORG = "org"


@dataclass(frozen=True)
class Feature:
    key: str
    name: str
    description: str
    group: str
    default_on: bool
    #: True when the feature takes an app's source code out of the platform.
    source_out: bool = False
    #: Where it is enforced: "api" when its routes refuse, "ui" when only the
    #: screens lock (the feature has no route of its own to refuse).
    enforced: str = "api"


CATALOGUE: tuple[Feature, ...] = (
    # Build
    Feature("drafts_room", "Drafts Room", "Study references and compose drafts before a build.", "build", True),
    Feature("discover", "Discover", "Guided discovery conversations that write a brief.", "build", True),
    Feature("templates", "Templates", "Start an app from a template or a suggested app.", "build", True),
    Feature("portal", "Portal", "The organisation's portal of apps, tasks and activity.", "build", True),
    Feature("brand", "Brand", "The company's brand profile, discovered from its logo or site.", "build", True),
    # Workspace
    Feature("code_view", "Code tab", "Read the app's source files inside Forge.", "workspace", False, source_out=True),
    Feature("legacy_editors", "Legacy editors", "The schema, AHTML and IR editors.", "workspace", True, enforced="ui"),
    Feature("agents", "Agents and AI", "An app's agent definitions and AI features.", "workspace", True),
    Feature("office", "Virtual office", "Watch the agents at work on an app.", "workspace", True, enforced="ui"),
    Feature("monitoring", "Monitoring", "An app's incidents and runtime exceptions.", "workspace", True, enforced="ui"),
    # Ship
    Feature("publish", "Publish to the web", "Deploy the built app on the platform's hosting.", "ship", False, source_out=True),
    Feature("mobile_builds", "Mobile builds", "iOS and Android binaries through Expo's build service.", "ship", False, source_out=True),
    Feature("code_export", "Code export", "Download the source, generate Dockerfile, compose, README and env files, push to git.", "ship", False, source_out=True),
    # Integrations
    Feature("integrations", "Integrations", "Keys and services the organisation connects to its apps.", "integrations", True),
    Feature("mcp_servers", "MCP servers", "Tool servers Smith may call while building.", "integrations", True),
)
BY_KEY: dict[str, Feature] = {f.key: f for f in CATALOGUE}
GROUPS = ("build", "workspace", "ship", "integrations")


def feature_or_404(key: str) -> Feature:
    f = BY_KEY.get(key)
    if f is None:
        raise HTTPException(status_code=404, detail=f"No feature named {key!r}")
    return f


def disabled_message(key: str) -> str:
    return f"{BY_KEY[key].name} is not enabled for your organisation. Ask the platform administrator."


async def settings_for(db: AsyncSession, org_id: uuid.UUID | str | None) -> dict[str, dict[str, FeatureSetting]]:
    """{"platform": {key: row}, "org": {key: row}} — the rows that apply."""
    where = FeatureSetting.scope_kind == PLATFORM
    if org_id is not None:
        where = or_(where, (FeatureSetting.scope_kind == ORG) & (FeatureSetting.scope_id == str(org_id)))
    rows = (await db.execute(select(FeatureSetting).where(where))).scalars().all()
    out: dict[str, dict[str, FeatureSetting]] = {PLATFORM: {}, ORG: {}}
    for row in rows:
        out[row.scope_kind][row.feature_key] = row
    return out


def resolve(feature: Feature, platform: FeatureSetting | None, org: FeatureSetting | None) -> dict[str, Any]:
    """What applies to one organisation for one feature, and where it came from."""
    if org is not None:
        return {"enabled": bool(org.enabled), "source": ORG, "reason": org.reason}
    if platform is not None:
        return {"enabled": bool(platform.enabled), "source": PLATFORM, "reason": platform.reason}
    return {"enabled": feature.default_on, "source": "default", "reason": ""}


async def effective(db: AsyncSession, org_id: uuid.UUID | str | None) -> dict[str, dict[str, Any]]:
    """Every feature as it stands for `org_id` (the platform's defaults when None)."""
    rows = await settings_for(db, org_id)
    return {f.key: resolve(f, rows[PLATFORM].get(f.key), rows[ORG].get(f.key)) for f in CATALOGUE}


async def is_enabled(db: AsyncSession, org_id: uuid.UUID | str, key: str) -> bool:
    return (await effective(db, org_id))[key]["enabled"]


async def require_enabled(db: AsyncSession, org_id: uuid.UUID | str, key: str) -> None:
    if not await is_enabled(db, org_id, key):
        raise HTTPException(status_code=403, detail=disabled_message(key), headers={"X-Forge-Feature": key})


async def set_feature(db: AsyncSession, *, scope_kind: str, scope_id: str, key: str, enabled: bool | None,
                      reason: str, by: PlatformUser) -> FeatureSetting | None:
    """Write (or, with `enabled=None`, clear) one setting. Returns the row kept."""
    feature_or_404(key)
    row = (await db.execute(select(FeatureSetting).where(
        FeatureSetting.scope_kind == scope_kind, FeatureSetting.scope_id == scope_id,
        FeatureSetting.feature_key == key))).scalar_one_or_none()
    if enabled is None:
        if row is not None:
            await db.delete(row)
        await db.flush()
        return None
    if row is None:
        row = FeatureSetting(scope_kind=scope_kind, scope_id=scope_id, feature_key=key, enabled=enabled,
                             reason=reason, set_by=by.id)
        db.add(row)
    else:
        row.enabled, row.reason, row.set_by = enabled, reason, by.id
    await db.flush()
    return row


async def org_of_request(request: Request, db: AsyncSession) -> uuid.UUID | None:
    """The organisation a route is about: its `org_id`, or the organisation
    of the project its `project_id` / `short_id` names. None when the route
    names neither (a catalogue, a listing of templates)."""
    params = request.path_params or {}
    raw = params.get("org_id")
    if raw:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            return None
    ref = params.get("project_id") or params.get("short_id")
    if not ref and params.get("deployment_id"):
        from models.deployment import Deployment
        try:
            dep = await db.get(Deployment, uuid.UUID(str(params["deployment_id"])))
        except ValueError:
            dep = None
        ref = str(dep.project_id) if dep is not None else None
    if not ref:
        return None
    ref = str(ref)
    project = None
    try:
        project = await db.get(Project, uuid.UUID(ref))
    except ValueError:
        project = (await db.execute(select(Project).where(Project.short_id == ref))).scalar_one_or_none()
    return project.org_id if project is not None else None


def feature_gate(key: str):
    """A dependency that refuses the route when `key` is off for the
    organisation the route is about. Sign-in is required first, so an
    outsider learns nothing about an organisation's features."""
    feature_or_404(key)

    async def gate(request: Request, user: PlatformUser = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)) -> None:
        org_id = await org_of_request(request, db)
        if org_id is None:
            return
        await require_enabled(db, org_id, key)

    gate.__name__ = f"feature_gate_{key}"
    return gate


def catalogue_rows() -> list[dict[str, Any]]:
    return [{"key": f.key, "name": f.name, "description": f.description, "group": f.group,
             "default_on": f.default_on, "source_out": f.source_out, "enforced": f.enforced} for f in CATALOGUE]
