"""Derive the account-type choices a generated app's signup page offers.

Some Blueprints model more than one kind of *self-service* account — a
marketplace where a crew member and a vessel owner register through the same
door and land in different workspaces. The auth scaffold is a single
name/email/password form, so that choice never reached the running app even
when the Blueprint spelled it out (page purpose, a designed two-card signup
layout, acceptance tests). This reads the choice the Blueprint already authored
and returns the options the signup form should present, each mapped to the enum
value the app stores on the account.

Semantic, not lexical. The friendly label the Blueprint shows ("Crew Member")
and the enum value it stores ("candidate") are written in different
vocabularies, and only meaning connects them. That mapping is asked of the
model — the way every other cross-vocabulary step in this pipeline is — rather
than guessed from a word list, which is the failure mode this codebase is built
to avoid. The answer is constrained to the account enum's own values, so the
model chooses a mapping and a self-service subset but cannot invent a value the
schema can't store.

Cheap by construction: the model is consulted only when the account entity
carries a multi-value ``accountType`` enum AND the Blueprint authored a signup
page that presents a choice (two or more option cards). A single-account app
trips neither gate and never makes a call. The result is cached per Blueprint
slice so re-assembly of the same app is free, and any failure degrades to "no
selector" rather than breaking assembly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Field names an app uses for the account-type discriminator on its sign-in
#: entity. This is the column that names *what kind* of account it is, not a
#: word list of account kinds — the kinds themselves come from the enum.
_ACCOUNT_TYPE_FIELDS = ("accountType", "account_type", "userType", "user_type")

#: Routes a signup page lives at.
_SIGNUP_ROUTES = ("/signup", "/register", "/sign-up")


def _entities(doc: dict) -> list[dict]:
    data = doc.get("data") or {}
    ents = data.get("entities")
    if isinstance(ents, list):
        return [e for e in ents if isinstance(e, dict)]
    return []


def _account_type_field(doc: dict) -> tuple[dict, dict, list[str]] | None:
    """The sign-in entity's account-type enum field and its values.

    Prefers the entity that reads as the sign-in account when more than one
    carries such a field, but the requirement that decides eligibility is
    structural: an enum discriminator with at least two values.
    """
    def rank(e: dict) -> int:
        name = (e.get("name") or "").lower()
        desc = (e.get("description") or "").lower()
        return (
            ("account" in name)
            + ("user" in name)
            + any(k in desc for k in ("sign-in", "sign in", "log in", "login"))
        )

    for e in sorted(_entities(doc), key=rank, reverse=True):
        for f in e.get("fields") or []:
            if not isinstance(f, dict):
                continue
            if f.get("type") == "enum" and f.get("name") in _ACCOUNT_TYPE_FIELDS:
                values = [str(v) for v in (f.get("enumValues") or []) if str(v).strip()]
                if len(dict.fromkeys(values)) >= 2:
                    return e, f, list(dict.fromkeys(values))
    return None


def _signup_page_id(doc: dict) -> str | None:
    for p in doc.get("pages") or []:
        if not isinstance(p, dict):
            continue
        route = str(p.get("route") or p.get("path") or "")
        name = str(p.get("name") or "")
        if route in _SIGNUP_ROUTES or name.strip().lower() in ("signup", "sign up", "register"):
            return p.get("id") or route
    return None


def _iter_nodes(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _iter_nodes(child)


def _authored_choices(doc: dict, page_id: str | None) -> list[dict[str, str]]:
    """The option cards the layout agent authored on the signup page.

    A choice reads as a titled card that is not the form itself — the
    ``FeatureCard`` the layout uses to say "pick this kind of account". Returns
    ``{"label", "hint"}`` per card, in authored order, deduped by label.
    """
    if not page_id:
        return []
    layout = next(
        (l for l in doc.get("pageLayouts") or [] if isinstance(l, dict) and l.get("page") == page_id),
        None,
    )
    if not layout:
        return []

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for n in _iter_nodes(layout.get("root") or {}):
        if (n.get("type") or n.get("component")) != "FeatureCard":
            continue
        props = n.get("props") or {}
        label = str(props.get("title") or props.get("label") or props.get("content") or "").strip()
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        hint = str(props.get("description") or props.get("subtitle") or props.get("body") or "").strip()
        out.append({"label": label, "hint": hint})
    return out


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "account"


def _cache_path(cache_dir: str | Path | None) -> Path | None:
    if not cache_dir:
        return None
    return Path(cache_dir) / ".forge" / "signup_account_types.json"


def _slice_key(values: list[str], choices: list[dict], purpose: str) -> str:
    payload = json.dumps({"v": values, "c": choices, "p": purpose}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_json_array(text: str) -> list | None:
    """Pull the first JSON array out of a model reply, fenced or bare."""
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    raw = fence.group(1) if fence else None
    if raw is None:
        start = text.find("[")
        end = text.rfind("]")
        raw = text[start : end + 1] if 0 <= start < end else None
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


def _map_choices(values: list[str], choices: list[dict], purpose: str) -> list[dict[str, str]]:
    """Ask the model which enum value each authored choice stores.

    Constrained to ``values``; returns the self-service subset in a stable
    shape. Kept isolated so the one network dependency assembly acquires has a
    single call site and a single failure mode.
    """
    from services.llm_client import complete

    system = (
        "You map a signup page's account-type choices onto an account entity's "
        "accountType enum. You are given the enum values the database stores, "
        "the choice cards the signup page shows a new user, and the page's "
        "purpose. Return ONLY a JSON array, one object per choice a member of "
        "the public can self-register as, in the order shown, each: "
        '{"value": <one of the given enum values, exactly>, '
        '"label": <the choice\'s human label, tidied>, '
        '"description": <one short sentence, or "">}. '
        "Map by meaning, not spelling. Omit any account kind that is not "
        "self-service public signup (staff, platform administrators, "
        "invite-only or admin-provisioned roles). Use each enum value at most "
        "once. If no choice is genuine self-service, return []."
    )
    user = json.dumps(
        {"enumValues": values, "choices": choices, "pagePurpose": purpose[:600]},
        ensure_ascii=False,
    )
    reply = complete(system=system, content=user, max_tokens=700, temperature=0)
    parsed = _extract_json_array(reply)
    if parsed is None:
        raise ValueError("model reply had no JSON array")

    allowed = set(values)
    used: set[str] = set()
    out: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        label = str(item.get("label") or "").strip()
        if value not in allowed or value in used or not label:
            continue
        used.add(value)
        desc = str(item.get("description") or "").strip()
        entry = {"value": value, "label": label}
        if desc:
            entry["description"] = desc
        out.append(entry)
    return out


def derive_signup_account_types(
    doc: dict, *, cache_dir: str | Path | None = None
) -> list[dict[str, str]]:
    """The account-type options the signup form should offer, or ``[]``.

    ``[]`` means "single-account app, leave signup as name/email/password" — the
    scaffold default. A non-empty result is a list of ``{"value", "label",
    "description"?}`` ready to serialise into the signup page and route.
    """
    try:
        field = _account_type_field(doc)
        if not field:
            return []
        _entity, _f, values = field

        page_id = _signup_page_id(doc)
        choices = _authored_choices(doc, page_id)
        if len(choices) < 2:
            # The app models several account types but its signup does not offer
            # a choice — they are provisioned by invite or admin, not by public
            # self-signup. Adding a selector would invent a flow the Blueprint
            # did not author.
            return []

        purpose = ""
        for p in doc.get("pages") or []:
            if isinstance(p, dict) and (p.get("id") == page_id or p.get("route") in _SIGNUP_ROUTES):
                purpose = str(p.get("purpose") or "")
                break

        cache_file = _cache_path(cache_dir)
        key = _slice_key(values, choices, purpose)
        if cache_file and cache_file.is_file():
            try:
                cached = json.loads(cache_file.read_text("utf-8"))
                if cached.get("key") == key and isinstance(cached.get("options"), list):
                    return cached["options"]
            except (json.JSONDecodeError, OSError):
                pass

        options = _map_choices(values, choices, purpose)
        if len(options) < 2:
            return []

        if cache_file:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(
                    json.dumps({"key": key, "options": options}, ensure_ascii=False),
                    "utf-8",
                )
            except OSError:
                pass
        return options
    except Exception:  # noqa: BLE001 — a signup selector must never be able to
        # fail an assembly; the app builds fine without one.
        logger.exception("signup account-type derivation failed; no selector")
        return []
