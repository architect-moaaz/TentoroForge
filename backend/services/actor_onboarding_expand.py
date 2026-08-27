"""Derive onboarding pages + workflows from the planner's ``actors`` block.

Slice B established the metadata (who the actors are, how each gets in).
This module makes that metadata *observable in the generated app*: for
every actor whose onboarding is not public self-signup, we ensure the
plan has the concrete UI the inviter needs to bring them in.

Per actor:

  * ``self_signup``   — nothing added here. The signup page already
                        handles it (see :func:`agents.planner._ensure_auth_pages`).
                        We still add an admin **list** page so someone
                        can see who signed up.
  * ``invited_by``    — add:
        - ``/<role-plural>``       (list, visibleTo=[inviter, admin])
        - ``/<role-plural>/new``   (create/invite form, visibleTo=[inviter])
        - workflow ``Invite<ActorName>`` — inserts a User row with the
          right ``role`` and stubs an email step (email transport is
          out-of-scope; the step exists for the workflow editor to fill
          in later).
  * ``platform_org``  — add:
        - ``/<role-plural>``       (list, visibleTo=[admin]) — reads the
          org's mapped users.
        - ``/<role-plural>/link``  (link/import form, visibleTo=[admin])
          — pick from the platform org's user pool and assign the role.
        No public signup, no invite workflow — provisioning is external.

Everything is *idempotent* and *additive*: if the LLM already emitted a
matching page or workflow (by route or by workflow name), we leave it
alone. Missing pieces get filled in. That means legacy plans without an
``actors`` block are a silent no-op — safe to always call.
"""
from __future__ import annotations

import re
from typing import Any

from services.entity_names import derive_names


_KEBAB_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def derive_actor_onboarding(plan: dict) -> dict:
    """Ensure onboarding pages + workflows exist per actor. Mutates ``plan``.

    Returns the same dict for pipeline chaining. Called after
    ``_ensure_actor_user_model`` so ``User.role`` is already populated with
    the right enum values.
    """
    if not isinstance(plan, dict):
        return plan
    actors = plan.get("actors")
    if not isinstance(actors, list) or not actors:
        return plan

    pages = plan.setdefault("pages", [])
    if not isinstance(pages, list):
        pages = []
        plan["pages"] = pages
    workflows = plan.setdefault("workflows", [])
    if not isinstance(workflows, list):
        workflows = []
        plan["workflows"] = workflows

    known_routes = {
        p.get("route") for p in pages
        if isinstance(p, dict) and isinstance(p.get("route"), str)
    }
    known_workflows = {
        (w.get("name") or "").strip() for w in workflows
        if isinstance(w, dict)
    }

    admin_role = _find_admin_role(actors) or "admin"

    for actor in actors:
        if not isinstance(actor, dict):
            continue
        role = str(actor.get("role") or "").strip()
        name = str(actor.get("name") or role or "").strip()
        if not role or not name:
            continue
        ob = actor.get("onboarding") or {}
        source = ob.get("source") if isinstance(ob, dict) else None
        role_plural = _plural_kebab(role)
        list_route = f"/{role_plural}"
        new_route = f"/{role_plural}/new"
        link_route = f"/{role_plural}/link"

        # --- LIST PAGE — always add, so admins/inviters can see who's in. ---
        if list_route not in known_routes:
            visible = _list_visible_to(source, ob, admin_role, role)
            list_page = _build_page(
                route=list_route,
                page_id=f"{role_plural}-list",
                name=f"{_humanize_plural(name)}",
                page_type="list",
                entity="User",
                visible_to=visible,
                description=f"Directory of {_humanize_plural(name).lower()} in the app.",
                filter_by={"role": role},
            )
            pages.append(list_page)
            known_routes.add(list_route)

        # --- BRANCH on onboarding source ---
        if source == "invited_by":
            inviter_name = ob.get("invited_by") if isinstance(ob, dict) else None
            inviter_role = _role_for_actor_name(actors, inviter_name) or admin_role

            # invite form
            if new_route not in known_routes:
                new_page = _build_page(
                    route=new_route,
                    page_id=f"{role_plural}-new",
                    name=f"Invite {name}",
                    page_type="form",
                    entity="User",
                    visible_to=[inviter_role],
                    description=(
                        f"Form for {inviter_name or 'the inviter'} to invite "
                        f"a new {name}. Creates a User row with role='{role}'."
                    ),
                    prefill={"role": role},
                )
                pages.append(new_page)
                known_routes.add(new_route)

            # invite workflow
            wf_name = f"Invite{_pascal(name)}"
            if wf_name not in known_workflows:
                workflows.append(_build_invite_workflow(
                    wf_name=wf_name,
                    actor_name=name,
                    actor_role=role,
                    inviter_role=inviter_role,
                ))
                known_workflows.add(wf_name)

        elif source == "platform_org":
            # Link-from-org page: admin picks from the platform org's user
            # pool and assigns the role. No workflow — provisioning is
            # external to the app.
            if link_route not in known_routes:
                link_page = _build_page(
                    route=link_route,
                    page_id=f"{role_plural}-link",
                    name=f"Link {name} from Organization",
                    page_type="form",
                    entity="User",
                    visible_to=[admin_role],
                    description=(
                        f"Pick a user from the platform organization's user "
                        f"pool and map them to the {name} role."
                    ),
                    prefill={"role": role, "source": "platform_org"},
                )
                pages.append(link_page)
                known_routes.add(link_route)

        elif source == "self_signup":
            # Self-signup describes the PUBLIC path in (the /signup page,
            # added by _ensure_auth_pages). It does NOT preclude internal
            # actors adding this role from inside the app — an admin can
            # always add a walk-in candidate; a recruiter can register a
            # candidate they scouted at a career fair. Add a /new page
            # visible to every internal-facing role so those flows exist.
            if new_route not in known_routes:
                internal_roles = _internal_actor_roles(actors, admin_role)
                new_page = _build_page(
                    route=new_route,
                    page_id=f"{role_plural}-new",
                    name=f"Add {name}",
                    page_type="form",
                    entity="User",
                    visible_to=internal_roles,
                    description=(
                        f"Internal creation form for {name}. Public path "
                        f"is /signup; this page lets admins and other "
                        f"internal roles add a {name} directly (walk-ins, "
                        f"CV imports, admin-initiated registration)."
                    ),
                    prefill={"role": role},
                )
                pages.append(new_page)
                known_routes.add(new_route)

    plan["pages"] = pages
    plan["workflows"] = workflows
    return plan


# --------------------------------------------------------------------------- #
# Internals — page + workflow shape builders
# --------------------------------------------------------------------------- #

def _build_page(
    *,
    route: str,
    page_id: str,
    name: str,
    page_type: str,
    entity: str,
    visible_to: list[str] | None,
    description: str,
    filter_by: dict | None = None,
    prefill: dict | None = None,
) -> dict:
    page: dict = {
        "id": page_id,
        "route": route,
        "name": name,
        "type": page_type,
        "entity": entity,
        "description": description,
        "source": "actor_onboarding",  # provenance marker for debugging
    }
    if visible_to:
        page["visibleTo"] = list(visible_to)
    if filter_by:
        page["filter"] = dict(filter_by)
    if prefill:
        page["prefill"] = dict(prefill)
    return page


def _build_invite_workflow(
    *,
    wf_name: str,
    actor_name: str,
    actor_role: str,
    inviter_role: str,
) -> dict:
    """A minimal invite workflow shaped like every other CRUD workflow the
    planner emits. Two steps: (1) db_insert into users with the actor's
    role pinned, (2) an email step stubbed so the workflow editor can wire
    real transport later. Emitting the stub means the run-time engine sees
    a coherent workflow instead of a 1-step insert with nowhere to go."""
    return {
        "name": wf_name,
        "description": f"Invite a new {actor_name} into the app (assigns role='{actor_role}').",
        "trigger": {
            "kind": "manual",
            "inputs": [
                {"name": "email",   "type": "email",   "required": True},
                {"name": "name",    "type": "varchar", "required": True},
            ],
        },
        "steps": [
            {"id": "create_user", "type": "db_insert",
             "config": {
                 "table": "users",
                 "values": {
                     "email": "{{input.email}}",
                     "name":  "{{input.name}}",
                     "role":  actor_role,
                 },
             },
             "next": "send_invite"},
            {"id": "send_invite", "type": "send_email",
             "config": {
                 "to": "{{input.email}}",
                 "subject": f"You've been invited as a {actor_name}",
                 "body": (
                     f"Hi {{{{input.name}}}}, you've been invited to join as "
                     f"a {actor_name}. Click the link to set your password."
                 ),
                 "note": (
                     "Email transport is a placeholder — wire an SMTP or "
                     "provider credential in the workflow editor before "
                     "production."
                 ),
             },
             "next": "end"},
            {"id": "end", "type": "end"},
        ],
        "roles": {"invoker": inviter_role},
        "source": "actor_onboarding",
    }


# --------------------------------------------------------------------------- #
# Small helpers — actor lookup + naming
# --------------------------------------------------------------------------- #

def _find_admin_role(actors: list) -> str | None:
    """Find the actor whose role name reads as 'admin' — used as the
    default gate for platform_org list pages when no explicit inviter is
    defined."""
    for a in actors:
        if not isinstance(a, dict):
            continue
        role = str(a.get("role") or "").strip().lower()
        if role in ("admin", "administrator", "superadmin", "root", "owner"):
            return a.get("role")
    return None


def _internal_actor_roles(actors: list, admin_role: str) -> list[str]:
    """Roles who can add users through the internal-creation form.

    Rule: admin + any actor who INVITES someone else in the graph. An
    actor is an "inviter" when at least one other actor has
    ``onboarding.invited_by == this.name``. That's a natural authority
    signal: if you can onboard staff (Admin invites Recruiter, Recruiter
    invites Interviewer), you can also add self-signup end users
    (Candidate). Actors who invite no one (Interviewer just conducts
    interviews; Candidate is a self-signup end user) are excluded —
    they shouldn't be able to register other users through the app.

    Admin is always included even if not in the graph (safe default
    for apps that omit an explicit admin actor).
    """
    inviter_names = {
        (a.get("onboarding") or {}).get("invited_by")
        for a in actors
        if isinstance(a, dict) and isinstance(a.get("onboarding"), dict)
    }
    inviter_names.discard(None)
    inviter_names.discard("")

    seen: list[str] = []
    def _add(r: str | None) -> None:
        if r and r not in seen:
            seen.append(r)
    _add(admin_role)
    for a in actors:
        if not isinstance(a, dict):
            continue
        if a.get("name") in inviter_names:
            _add(a.get("role"))
    return seen or [admin_role]


def _role_for_actor_name(actors: list, name: str | None) -> str | None:
    """Resolve an actor NAME (as it appears in ``onboarding.invited_by``)
    back to its role, so the invite page's visibleTo uses roles not
    display names."""
    if not name:
        return None
    for a in actors:
        if not isinstance(a, dict):
            continue
        if a.get("name") == name:
            return a.get("role")
    return None


def _list_visible_to(
    source: str | None, ob: dict, admin_role: str, own_role: str,
) -> list[str] | None:
    """Compute visibleTo for an actor's LIST page. Own-role users always
    see their own directory (self-signup candidates → candidate list);
    admins always see everyone; invited_by inviters see the pool they
    manage."""
    seen: list[str] = []
    def _add(r: str | None) -> None:
        if r and r not in seen:
            seen.append(r)
    _add(admin_role)
    _add(own_role)
    if source == "invited_by" and isinstance(ob, dict):
        inviter_name = ob.get("invited_by")
        if inviter_name:
            _add(inviter_name.lower())
    return seen or None


def _kebab(s: str) -> str:
    s = _KEBAB_SPLIT.sub("-", s)
    s = _NON_ALNUM.sub("-", s).strip("-").lower()
    return s or "actor"


def _plural_kebab(role: str) -> str:
    """Plural kebab route slug for an actor role: ``recruiter`` → ``recruiters``.

    Delegates to :func:`services.entity_names.derive_names` — the single
    naming authority. Linguistic accuracy is not the point; AGREEMENT is.
    These slugs become routes (``/recruiters``, ``/recruiters/new``) that
    other builders link to after deriving the same slug through the
    authority, so a private copy that differs on 4 of every 20 roles
    produces 404ing links.

    ``_kebab`` still runs first so this accepts the free-form role
    strings planners emit, not just PascalCase entity names."""
    return derive_names(_kebab(role)).routeSlug


def _humanize_plural(name: str) -> str:
    """Display label for a plural: ``Recruiter`` → ``Recruiters``."""
    if not name:
        return "Users"
    if name.endswith("s"):
        return name
    if name.endswith("y") and name[-2:-1] not in "aeiou":
        return name[:-1] + "ies"
    if name.endswith(("ch", "sh", "x", "z")):
        return name + "es"
    return name + "s"


def _pascal(name: str) -> str:
    """``Cabin Crew`` → ``CabinCrew``, ``recruiter`` → ``Recruiter``."""
    parts = re.split(r"[\s_-]+", name.strip()) if name else []
    return "".join(p[:1].upper() + p[1:] for p in parts if p) or "Actor"
