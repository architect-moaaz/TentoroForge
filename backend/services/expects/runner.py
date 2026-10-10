"""One runner for every application: each statement tried as its people.

For each statement (`Expectation`), on a copy of the application's database
with its dev server running (`page_review.RunningApp`):

  1. the given records are made through the application's own data API, as
     the person who owns them, so the application stamps whose they are;
  2. each step is done in a browser as its person — signing in through the
     application's own sign-in form, opening screens, and doing what the step
     says on the controls a person would use (`resolve`);
  3. each check is judged by code from what the browser and the database
     report: the screen they are on, the text it shows, what the application
     answered their last action, what opening a screen gives them, what is
     stored. No model judges whether the application was right.

A statement passes when every check holds, fails when one does not — with
what was seen instead — and is "not tried" when the runner could not set it
up (a record it could not make, a person it could not sign in). Crashes and
server errors seen on the way are kept beside the verdict (`also`).

Nothing here knows what any application is for.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from services.expects import resolve
from services.expects.browser import Browser, BrowserGone
from services.expects.statements import GUEST, _entities, _live, expectations

logger = logging.getLogger(__name__)

#: What an application's answer to a write means when it is not a success.
REFUSED = {400, 401, 403, 404, 409, 422}
_NOT_FOUND = re.compile(r"\b404\b|\bpage not found\b|\bnot found\b|could not be found|does not exist|"
                        r"doesn'?t exist|no longer available", re.I)
_NOT_ALLOWED = re.compile(r"\b403\b|\bforbidden\b|not allowed|not available to your role|access denied|"
                          r"(?:do not|don'?t) have access|not authori[sz]ed|unauthori[sz]ed", re.I)
_VALIDATION = re.compile(r"required|invalid|must be|please (?:enter|fill|choose|select)|cannot be|can't be|"
                         r"at least|at most|not enough|exceeds?|only \d+", re.I)
_ADDRESS_REF = re.compile(r"((?:^|[/=?&]))@([A-Za-z][\w\-]*)")


class _Missing(Exception):
    """A check names a field its record type does not keep."""


class NotTried(Exception):
    """The statement could not be set up; nothing was learned about the app."""


class StepFailed(Exception):
    """A step could not be done the way a person would do it — itself a finding."""


@dataclass
class Person:
    key: str
    role: str                 # a role id, or GUEST
    name: str                 # the role's name, or "guest"
    email: str = ""
    password: str = ""
    signed_in: bool = False
    url: str = ""
    nav: dict | None = None   # what the last screen opened gave
    last: dict | None = None  # what the application answered their last `do`


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split()).lower()


def _route_re(route: str) -> re.Pattern:
    from services.blueprint.app_check import _route_re as rr
    return rr(route)


#: Fields the application fills itself, never by whoever makes a record.
_SELF_FILLED = {"id", "createdAt", "updatedAt", "deletedAt", "created_at", "updated_at"}


def complete(entity: dict, values: dict, stamp: str) -> dict:
    """A record a statement gives, with each required field it left out
    filled in: what the field's own examples or allowed values say first, a
    plain value of its type otherwise — made unique to the statement, so it
    never meets a row the copy already has. A statement names what matters
    to it; a slug or an order number it did not mention does not."""
    out = dict(values)
    label = next((v for v in values.values() if isinstance(v, str) and v.strip() and not v.startswith("@")), "")
    for f in entity.get("fields") or []:
        name = str(f.get("name") or "") if isinstance(f, dict) else ""
        if not name or name in out or name in _SELF_FILLED or not f.get("required"):
            continue
        kind = str(f.get("type") or "string").lower()
        if kind in ("uuid", "reference", "relation", "file", "image", "location", "json"):
            continue                      # a record it points at is the statement's to give
        allowed = f.get("values") or f.get("enumValues") or f.get("options")
        examples = [x for x in f.get("examples") or [] if x not in (None, "")]
        if kind in ("boolean", "bool"):
            out[name] = examples[0] if examples and isinstance(examples[0], bool) else True
        elif allowed:
            out[name] = allowed[0] if not isinstance(allowed[0], dict) else allowed[0].get("value")
        elif kind in ("number", "decimal", "integer", "int", "float", "money", "currency"):
            out[name] = examples[0] if examples and isinstance(examples[0], (int, float)) else 1
        elif kind in ("date", "datetime", "timestamp", "time"):
            out[name] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        elif "email" in name.lower():
            out[name] = f"{stamp}.{name.lower()}@example.com"
        else:
            base = re.sub(r"[^a-z0-9]+", "-", (label or name).lower()).strip("-") or name.lower()
            out[name] = f"{base}-{stamp}" if f.get("unique") or "slug" in name.lower() or "number" in name.lower() \
                or "code" in name.lower() else (label or f"{name} {stamp}")
    return out


class Logins:
    """Who signs in as each role on the copy: the seeded administrator, and
    for every other role a login of that role whose password on the COPY is
    set to the administrator's, so the sign-in form can be used as them. A
    second person of a role (`who`) is a copy of the first login."""

    def __init__(self, app: Any, doc: dict):
        self.app, self.doc = app, doc
        self.cache: dict[tuple[str, str], tuple[str, str]] = {}

    def _q(self, sql: str) -> list[list[str]]:
        from services.blueprint.page_review import _query
        return _query(self.app, sql)

    def of(self, role_name: str, who: str = "") -> tuple[str, str]:
        from services.blueprint.account_model import admin_role, account_entity
        from services.blueprint.page_review import ADMIN_EMAIL, ADMIN_PASSWORD, login_of_role
        from services.seed_backstop import _ADMIN_BCRYPT

        key = (role_name, who)
        if key in self.cache:
            return self.cache[key]
        admin = admin_role(self.doc) or "Admin"
        if role_name == admin and not who:
            self.cache[key] = (ADMIN_EMAIL, ADMIN_PASSWORD)
            return self.cache[key]
        if role_name == admin:
            found = (self._q("select id::text from users where email = '%s'" % ADMIN_EMAIL.replace("'", "''")) or [[None]])[0][0]
        else:
            got = login_of_role(self.app, self.doc, role_name)
            found = got[0] if got else None
        if not found:
            raise NotTried(f"the copy has no login of the role {role_name} to sign in as")
        if who:
            found = self._clone(found, who, account_entity(self.doc))
        email = (self._q(f"select email from users where id::text = '{found}'") or [[""]])[0][0]
        if not email:
            raise NotTried(f"the {role_name} login on the copy has no email to sign in with")
        self._q(f"update users set password = '{_ADMIN_BCRYPT}' where id::text = '{found}' returning id")
        self.cache[key] = (email, ADMIN_PASSWORD)
        return self.cache[key]

    def _clone(self, src: str, who: str, account: dict | None) -> str:
        """A second login of the same role: the first one's rows copied under
        a new id and email — its login row, and its account row when the
        account is a record of its own."""
        import uuid as _uuid
        from services.blueprint.projection import to_snake
        new = str(_uuid.uuid4())
        tag = re.sub(r"[^a-z0-9]+", "-", who.lower()).strip("-") or "other"
        for table in ["users"] + ([str(account.get("table") or to_snake(str(account.get("name"))))]
                                  if account else []):
            if not table.replace("_", "").isalnum():
                continue
            cols = [r[0] for r in self._q("select column_name from information_schema.columns "
                                          f"where table_schema = 'public' and table_name = '{table}'")]
            if not cols or "id" not in cols:
                continue
            picks = []
            for c in cols:
                if c == "id":
                    picks.append(f"'{new}'::uuid")
                elif c == "email":
                    picks.append(f"'{tag}.' || {c}")
                else:
                    picks.append(f'"{c}"')
            self._q(f'insert into "{table}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
                    f'select {", ".join(picks)} from "{table}" where id::text = \'{src}\' returning id')
        return new


class Trial:
    """One statement, tried: its people, its records, its steps, its checks."""

    def __init__(self, app: Any, doc: dict, browser: Browser, recipes: resolve.Recipes, logins: Logins,
                 sessions: dict | None = None):
        from services.blueprint.account_model import admin_role
        self.app, self.doc, self.b, self.recipes, self.logins = app, doc, browser, recipes, logins
        #: Signed-in sessions kept across statements, by role and person: the
        #: copy is reset in place, so a session outlives it.
        self.sessions = sessions if sessions is not None else {}
        self.roles = {str(r.get("id")): str(r.get("name") or r.get("id")) for r in _live(doc.get("roles"))}
        admin = admin_role(doc) or "Admin"
        self.admin_id = next((k for k, v in self.roles.items() if v == admin), "")
        self.pages = {str(p.get("id")): p for p in _live(doc.get("pages")) if p.get("route")}
        self.ents = _entities(doc)
        self.people: dict[str, Person] = {}
        self.given: dict[str, dict] = {}
        self.log: list[str] = []
        self.also: list[str] = []
        self.signs_in: set[str] = set()
        self.started = ""
        self.stamp = ""
        #: What the people's actions sent, and the screen of the last one:
        #: the evidence of whose part a failure is (`expects.build.owner_of`).
        self.sent: list[dict] = []
        self.where = ""
        self.unstarted: list[str] = []

    # ── people ─────────────────────────────────────────────────────────────

    def _key(self, role: Any, who: Any) -> str:
        return f"{role or self.admin_id}:{who or ''}"

    def person(self, role: Any, who: Any = None) -> Person:
        role = str(role or self.admin_id)
        key = self._key(role, who)
        if key in self.people:
            return self.people[key]
        if role != GUEST and role not in self.roles:
            raise NotTried(f"{role} is not one of the application's roles")
        p = Person(key=key, role=role, name=GUEST if role == GUEST else self.roles[role])
        self.people[key] = p
        if role == GUEST or key in self.signs_in:
            # A guest, or a person whose statement signs them in: signed out.
            self.b.call("person", key=key, base=self.app.base)
            if role != GUEST:
                p.email, p.password = self.logins.of(p.name, str(who or ""))
            return p
        self._signed_in(p, key, str(who or ""))
        return p

    def _signed_in(self, p: Person, key: str, who: str, *, form_only: bool = True) -> None:
        """`p` signed in: with the session kept from an earlier statement when
        it still holds, else through the sign-in form, keeping that session."""
        # Who they are, before anything else: records they own are stamped
        # with their login's id, read by their email.
        p.email, p.password = self.logins.of(p.name, who)
        kept = self.sessions.get((p.role, who))
        if kept:
            self.b.call("person", key=key, base=self.app.base, state=kept)
            session = self.b.call("api", key=key, method="GET", path="/api/auth/session")
            if '"user"' in str(session.get("body") or ""):
                p.signed_in = True
                return
            self.b.call("close", key=key)
        self.b.call("person", key=key, base=self.app.base)
        p.email, p.password = self.logins.of(p.name, who)
        if not self._sign_in(p, self._sign_in_route()):
            if form_only:
                raise NotTried(f"could not sign in as {p.name} through the sign-in form (landed on {p.url})")
            got = self.b.call("apisignin", key=key, email=p.email, password=p.password)
            if not got.get("signedIn"):
                raise NotTried(f"could not sign in as {p.name} to make the starting records")
            self.log.append(f"{p.name} signed in through the sign-in endpoint to make the starting records")
            p.signed_in = True
        state = self.b.call("state", key=key).get("state")
        if state:
            self.sessions[(p.role, who)] = state

    def maker(self, role: Any, who: Any = None) -> Person:
        """Who makes a given record: the same login as the statement's person,
        signed in in a browser of its own — the statement's person may start
        signed out to sign in later. A guest's records are made in the guest's
        own browser, which is what makes them that guest's."""
        role = str(role or self.admin_id)
        if role == GUEST:
            return self.person(role, who)
        key = "maker:" + self._key(role, who)
        if key in self.people:
            return self.people[key]
        if role not in self.roles:
            raise NotTried(f"{role} is not one of the application's roles")
        p = Person(key=key, role=role, name=self.roles[role])
        self.people[key] = p
        self._signed_in(p, key, str(who or ""), form_only=False)
        return p

    def _sign_in_route(self) -> str:
        from services.expects.statements import _sign_in_route
        return _sign_in_route(self.doc)

    def _auth_routes(self) -> set[str]:
        return {str(p.get("route")) for p in self.pages.values() if str(p.get("pattern") or "") == "auth"} \
            | {self._sign_in_route()}

    def _sign_in(self, p: Person, route: str) -> bool:
        # Once more when the first try gave no session: a dev server
        # recompiling a page that was just rewritten drops the first one.
        return self._sign_in_once(p, route) or self._sign_in_once(p, route)

    def _sign_in_once(self, p: Person, route: str) -> bool:
        got = self.b.call("signin", key=p.key, url=self.app.base + route, email=p.email, password=p.password)
        if not got.get("ok"):
            self.log.append(f"{p.name} could not use the sign-in form at {route}: {got.get('error')}")
            return False
        p.url = str(got.get("url") or "")
        p.nav = {"status": 200, "url": p.url, "text": ""}
        session = self.b.call("api", key=p.key, method="GET", path="/api/auth/session")
        p.signed_in = '"user"' in str(session.get("body") or "")
        self.log.append(f"{p.name} signed in through the form at {route} and landed on {self.path(p.url)}"
                        + ("" if p.signed_in else " — but no session came of it"))
        return p.signed_in

    def _on_sign_in(self, p: Person) -> bool:
        here = self.path(p.url).split("?", 1)[0]
        return bool(p.url) and any(_route_re(r).match(here) for r in self._auth_routes())

    def path(self, url: str) -> str:
        url = str(url or "")
        if url.startswith(self.app.base):
            url = url[len(self.app.base):]
        return url.split("#", 1)[0] or "/"

    # ── records ────────────────────────────────────────────────────────────

    def _table(self, eid: str) -> str:
        from services.blueprint.projection import to_snake
        ent = self.ents.get(eid) or {}
        return str(ent.get("table") or to_snake(str(ent.get("name") or "")))

    def _value(self, v: Any) -> Any:
        if isinstance(v, str) and v.strip().startswith("@") and v.strip()[1:] in self.given:
            ref = v.strip()[1:]
            if ref not in self.given:
                raise NotTried(f"@{ref} is used before it is made")
            return self.given[ref]["id"]
        return v

    def make_given(self, g: dict) -> None:
        ref, eid = str(g.get("ref")), str(g.get("entity"))
        ent = self.ents.get(eid)
        if ent is None:
            raise NotTried(f"the given {ref} is of a record type the application does not have")
        if g.get("self"):
            return self._make_self(g, ent)
        owner = self.maker(g.get("as"), g.get("who"))
        values = {k: self._value(v) for k, v in (g.get("values") or {}).items()}
        values = complete(ent, values, self.stamp)
        table = self._table(eid)
        values = self._distinct_name(ent, table, values, ref)
        got = self.b.call("api", key=owner.key, method="POST", path=f"/api/data/{table}", body=values)
        status = int(got.get("status") or 0)
        if not got.get("ok") or status >= 300:
            refused = (f"the {owner.name} could not make a {ent.get('name')} through the application: "
                       f"HTTP {status} {str(got.get('body') or got.get('error') or '')[:300]}")
            # A starting record is where a statement starts, not what it
            # tries: refused through the application, it is put on the copy
            # directly — whose it is filled in the way the application would
            # (`stamp_columns`) — and the refusal kept beside the verdict.
            self.also.append(refused)
            row = self._insert(table, {**values, **self._whose(ent, owner)})
            if row is None:
                raise NotTried(f"the given {ref}: {refused}; and it could not be put on the copy directly"
                               + (f" ({self.last_insert_error})" if getattr(self, "last_insert_error", "") else ""))
        else:
            try:
                row = json.loads(got.get("body") or "{}")
            except ValueError:
                raise NotTried(f"the given {ref}: the application answered with a page, not a record "
                               f"(HTTP {status}) — {owner.name} was not let in to make it") from None
        if isinstance(row, dict) and isinstance(row.get("data"), dict):
            row = row["data"]
        rid = str((row or {}).get("id") or "") if isinstance(row, dict) else ""
        if not rid:
            raise NotTried(f"the given {ref} ({ent.get('name')}) was made but the answer carried no id")
        self.given[ref] = {"id": rid, "entity": eid, "values": values, "row": row if isinstance(row, dict) else {},
                           "table": table}
        self.log.append(f"made {ent.get('name')} {ref} ({rid}) as {owner.name}")

    def _distinct_name(self, ent: dict, table: str, values: dict, ref: str) -> dict:
        """A record looked for by its name is found by its name ALONE: when the
        copy already has a row of that name, this one's is made its own. The
        deactivated "Classic Crew Tee" a statement made was judged still on
        sale because the copy's own "Classic Crew Tee" was (torob1,
        2026-10-09)."""
        from services.blueprint.page_review import _query
        from services.blueprint.projection import to_snake
        field = next((f for f in (ent.get("labelField"), "name", "title", "label")
                      if f and isinstance(values.get(f), str) and values[f].strip()), None)
        if not field:
            return values
        name = values[field].replace("'", "''")
        clash = _query(self.app, f'select 1 from "{table}" where "{to_snake(field)}"::text = \'{name}\' limit 1')
        if clash and clash[0]:
            values = {**values, field: f"{values[field]} {self.stamp.upper()}"}
            # AND EVERY FIELD THAT MUST BE UNIQUE WITH IT. 'Electronics EXP008'
            # kept the slug 'electronics', the app answered 409, and the
            # statement failed as the app's (ecom v2, forge-v3, 2026-10-10).
            told = [field]
            for f in ent.get("fields") or []:
                n = str(f.get("name") or "")
                if not n or n == field or not isinstance(values.get(n), str) or not values[n].strip():
                    continue
                if f.get("unique") or "slug" in n.lower() or "number" in n.lower() or "code" in n.lower():
                    values[n] = f"{values[n]}-{self.stamp.lower()}"
                    told.append(n)
            self.log.append(f"the copy already had a {ent.get('name')} named {name!r}; {ref} is "
                            f"{values[field]!r} so it can be told apart"
                            + (f" (and its {', '.join(told[1:])} with it)" if len(told) > 1 else ""))
        return values

    def _make_self(self, g: dict, ent: dict) -> None:
        """The person's own account record set to what the statement says —
        on the copy, by the login's id (a login IS its account row)."""
        from services.blueprint.page_review import _query
        from services.blueprint.projection import to_snake
        ref = str(g.get("ref"))
        role = str(g.get("as") or "")
        if role not in self.roles:
            raise NotTried(f"the given {ref} is someone's own account and names no role")
        email, _pw = self.logins.of(self.roles[role], str(g.get("who") or ""))
        rows = _query(self.app, "select id::text from users where email = '%s'" % email.replace("'", "''"))
        if not rows or not rows[0]:
            raise NotTried(f"the {self.roles[role]} login has no account to set")
        rid = rows[0][0]
        table = self._table(str(ent.get("id")))
        sets = []
        for k, v in (g.get("values") or {}).items():
            v = self._value(v)
            col = to_snake(str(k))
            lit = ("null" if v is None else ("true" if v is True else "false") if isinstance(v, bool)
                   else str(v) if isinstance(v, (int, float)) else "'" + str(v).replace("'", "''") + "'")
            sets.append(f'"{col}" = {lit}')
        if sets:
            done = _query(self.app, f'update "{table}" set {", ".join(sets)} where id::text = \'{rid}\' returning id')
            if not done:
                raise NotTried(f"the {self.roles[role]}'s own {ent.get('name')} could not be set: "
                               + (self._sql_error(f'update "{table}" set {", ".join(sets)} where id::text = \'{rid}\'')
                                  or "no account row"))
        self.given[ref] = {"id": rid, "entity": str(ent.get("id")), "values": dict(g.get("values") or {}),
                           "row": {}, "table": table}
        self.log.append(f"set the {self.roles[role]}'s own {ent.get('name')} ({rid}): "
                        + ", ".join(f"{k}={v!r}" for k, v in (g.get("values") or {}).items()))

    def _whose(self, ent: dict, owner: Person) -> dict:
        """The columns that say whose a record is, as the application would
        fill them for `owner`: their login's id, or a guest's token."""
        from services.blueprint.page_review import _query
        from services.expects.statements import stamp_columns
        user_cols, guest_cols = stamp_columns(self.doc, ent)
        if owner.role == GUEST:
            if not guest_cols:
                return {}
            jar = self.b.call("cookies", key=owner.key).get("cookies") or []
            token = next((c.get("value") for c in jar if c.get("name") == "forge-guest"), "")
            if not token:
                raise NotTried(f"the guest has no token of their own to own a {ent.get('name')} by")
            return {c: token for c in guest_cols}
        if owner.role == self.admin_id or not user_cols:
            return {}
        rows = _query(self.app, "select id::text from users where email = '%s'" % owner.email.replace("'", "''"))
        return {c: rows[0][0] for c in user_cols} if rows and rows[0] else {}

    def _insert(self, table: str, values: dict) -> dict | None:
        """A row put on the copy directly, its fields by their column names."""
        from services.blueprint.page_review import _query
        from services.blueprint.projection import to_snake
        info = {r[0]: r for r in _query(self.app, (
            "select column_name, is_nullable, coalesce(column_default, ''), data_type, udt_name "
            f"from information_schema.columns where table_schema = 'public' and table_name = '{table}'")) if r}
        cols = set(info)
        # WHAT THE TABLE INSISTS ON. A column the database requires and nothing
        # fills — no default, not given, not in the definition's required list
        # (an order's `placed_at`, a cart's `status`) — gets a plain value of
        # its type, so the insert is refused only for what the statement said.
        given = {to_snake(str(k)) for k in values}
        filled: dict[str, str] = {}
        for col, (_n, nullable, default, kind, udt) in info.items():
            if nullable != "NO" or default or col in given or col == "id":
                continue
            kind = (kind or "").lower()
            if "timestamp" in kind or kind == "date":
                filled[col] = "now()"
            elif kind in ("integer", "bigint", "smallint", "numeric", "real", "double precision"):
                filled[col] = "0"
            elif kind == "boolean":
                filled[col] = "false"
            elif kind == "user-defined":
                filled[col] = f"(enum_range(null::\"{udt}\"))[1]"
            elif kind in ("json", "jsonb"):
                filled[col] = "'{}'"
            elif kind in ("text", "character varying", "character"):
                filled[col] = f"'{col}-{self.stamp or 'x'}'"
        names, vals = [], []
        for col, sql_value in filled.items():
            names.append(f'"{col}"')
            vals.append(sql_value)
        for k, v in values.items():
            col = to_snake(str(k))
            if col not in cols:
                continue
            names.append(f'"{col}"')
            if v is None:
                vals.append("null")
            elif isinstance(v, bool):
                vals.append("true" if v else "false")
            elif isinstance(v, (int, float)):
                vals.append(str(v))
            elif isinstance(v, (dict, list)):
                vals.append("'" + json.dumps(v).replace("'", "''") + "'")
            else:
                vals.append("'" + str(v).replace("'", "''") + "'")
        rows = _query(self.app, f'with i as (insert into "{table}" ({", ".join(names)}) values ({", ".join(vals)}) '
                                f'returning *) select row_to_json(i)::text from i')
        if not rows or not rows[0]:
            self.last_insert_error = self._sql_error(
                f'insert into "{table}" ({", ".join(names)}) values ({", ".join(vals)})')
            # A RECORD THAT IS ALREADY THERE IS GIVEN. A unique name the copy's
            # own rows already hold ("Shirts") is the record the statement
            # starts from; it was refused as a duplicate, not missing.
            unique = [r[0] for r in _query(self.app, (
                "select k.column_name from information_schema.table_constraints c join "
                "information_schema.key_column_usage k on k.constraint_name = c.constraint_name "
                f"where c.table_name = '{table}' and c.constraint_type = 'UNIQUE'")) if r]
            for k, v in values.items():
                col = to_snake(str(k))
                if col in unique and isinstance(v, str):
                    rows = _query(self.app, f'select row_to_json(t)::text from "{table}" t '
                                            f"where \"{col}\"::text = '{v.replace(chr(39), chr(39) * 2)}' limit 1")
                    if rows and rows[0]:
                        break
        try:
            return json.loads(rows[0][0]) if rows and rows[0] else None
        except ValueError:
            return None

    def _sql_error(self, sql: str) -> str:
        """Why a statement the copy refused was refused — run inside a
        transaction that is rolled back, so nothing it did is kept."""
        import subprocess
        container, copy, _url = self.app.clone or ("", "", "")
        try:
            if container:
                done = subprocess.run(["docker", "exec", container, "psql", "-U", "postgres", "-d", copy, "-v",
                                       "ON_ERROR_STOP=1", "-c", f"begin; {sql}; rollback;"],
                                      capture_output=True, text=True, timeout=60)
                return (done.stderr or "").strip().splitlines()[0][:300] if done.returncode else ""
            from services import app_databases
            con = app_databases._connect(copy)
            try:
                con.autocommit = False
                with con.cursor() as cur:
                    cur.execute(sql)
                con.rollback()
            finally:
                con.close()
        except Exception as exc:  # noqa: BLE001 — the reason, as the database gave it
            return str(exc).splitlines()[0][:300]
        return ""

    def label(self, ref: str) -> str:
        g = self.given.get(ref.lstrip("@")) or {}
        ent = self.ents.get(str(g.get("entity"))) or {}
        values = {**(g.get("row") or {}), **(g.get("values") or {})}
        for f in (ent.get("labelField"), "name", "title", "label"):
            if f and isinstance(values.get(f), str) and values[f].strip():
                return values[f]
        ids = {str(x.get("id")) for x in self.given.values()}
        own = next((v for v in (g.get("values") or {}).values()
                    if isinstance(v, str) and v.strip() and not v.startswith("@") and v not in ids
                    and not re.fullmatch(r"[0-9a-f-]{36}", v.strip())), "")
        if own:
            return own
        # A record with no name of its own is shown by the one it points at:
        # a cart line by its product's name — the nearest name or title along
        # what it points at, before any other value.
        return self._name_along(g) or ""

    def _name_along(self, g: dict) -> str:
        seen: set[int] = {id(g)}
        frontier = [g]
        fallback = ""
        while frontier:
            nxt = []
            for cur in frontier:
                for v in (cur.get("values") or {}).values():
                    pointed = next((x for x in self.given.values() if id(x) not in seen and x.get("id") == v), None)
                    if pointed is None:
                        continue
                    seen.add(id(pointed))
                    vals = {**(pointed.get("row") or {}), **(pointed.get("values") or {})}
                    for f in ("name", "title", "fullName", "label"):
                        if isinstance(vals.get(f), str) and vals[f].strip():
                            return vals[f]
                    fallback = fallback or next((x for x in (pointed.get("values") or {}).values()
                                                 if isinstance(x, str) and x.strip() and not x.startswith("@")), "")
                    nxt.append(pointed)
            frontier = nxt
        return fallback

    # ── addresses ──────────────────────────────────────────────────────────

    def address(self, page: Any = None, record: Any = None, address: Any = None) -> str:
        if address:
            def sub(m: re.Match) -> str:
                ref = m.group(2)
                if ref not in self.given:
                    raise NotTried(f"the address names @{ref}, which was not made")
                return m.group(1) + self.given[ref]["id"]
            return _ADDRESS_REF.sub(sub, str(address))
        pg = self.pages.get(str(page or ""))
        if pg is None:
            raise NotTried(f"the screen {page} is not one the application has")
        route = str(pg["route"])
        rec = self.given.get(str(record or "").lstrip("@")) if record else None
        if "[" not in route:
            # A RECORD OPENED IN A PANEL OF THE SCREEN: `/browse?product=<id>`.
            # The record was dropped and the bare list judged in its place
            # (ToroCommerce's product detail, torob1, 2026-10-09).
            if rec is not None:
                panel = next((sec for sec in pg.get("sections") or [] if isinstance(sec, dict)
                              and sec.get("placement") == "panel" and sec.get("param")
                              and str(sec.get("entity") or "") == str(rec.get("entity"))), None)
                if panel is not None:
                    return f"{route}?{panel['param']}={rec['id']}"
            return route
        values: dict = {}
        rid = ""
        if rec is not None:
            values, rid = {**(rec.get("row") or {}), **(rec.get("values") or {})}, rec["id"]
        else:
            row = self._any_row(pg)
            if row is None:
                raise NotTried(f"{route} opens one record and there is none to open")
            values, rid = row, str(row.get("id"))

        def fill(m: re.Match) -> str:
            name = m.group(1).lstrip(".")
            if name == "id" or name.endswith("Id") or name.endswith("_id"):
                return rid
            v = values.get(name)
            return str(v) if v not in (None, "") else rid
        return re.sub(r"\[([^\]]+)\]", fill, route)

    def _any_row(self, page: dict) -> dict | None:
        from services.blueprint.page_review import _query
        eid = str((page.get("data") or {}).get("primaryEntity") or "")
        if eid not in self.ents:
            return None
        table = self._table(eid)
        rows = _query(self.app, f'select row_to_json(t)::text from "{table}" t limit 1')
        try:
            row = json.loads(rows[0][0]) if rows and rows[0] else None
        except ValueError:
            return None
        if isinstance(row, dict):
            row.update({re.sub(r"_([a-z])", lambda m: m.group(1).upper(), k): v for k, v in list(row.items())})
        return row

    # ── steps ──────────────────────────────────────────────────────────────

    def goto(self, p: Person, where: str) -> dict:
        nav = self.b.call("goto", key=p.key, url=self.app.base + where)
        if not nav.get("ok") and re.search(r"Timeout|ERR_ABORTED", str(nav.get("error"))):
            # A dev server compiling, or a client redirect cutting the load
            # short: once more before it counts.
            nav = self.b.call("goto", key=p.key, url=self.app.base + where)
        if not nav.get("ok"):
            raise StepFailed(f"{where} could not be opened as {p.name}: {nav.get('error')}")
        p.nav, p.url = nav, str(nav.get("url") or "")
        for e in nav.get("errors") or []:
            self.also.append(f"opening {where} as {p.name}: {e}")
        if int(nav.get("status") or 0) >= 500:
            self.also.append(f"{where} answered HTTP {nav.get('status')} as {p.name}")
        # WHAT NO SCREEN MAY SHOW, on every screen a statement opens: a crash
        # page, "undefined", a raw record id, a label read as a 2001 date —
        # the checks the separate page check made, kept beside the verdict.
        try:
            from services.blueprint.app_check import screen_findings
            for f in screen_findings(str(nav.get("text") or ""), self.doc):
                self.also.append(f"{self.path(p.url)} as {p.name}: {f}")
        except Exception:  # noqa: BLE001 — a check that cannot read the screen says nothing
            pass
        return nav

    def step(self, st: dict, i: int, s: dict) -> None:
        p = self.person(s.get("as"), s.get("who"))
        act = str(s.get("act"))
        if act == "open":
            where = self.address(s.get("page"), s.get("record"), s.get("address"))
            nav = self.goto(p, where)
            self.log.append(f"{p.name} opened {where} → {self.path(nav.get('url'))} (HTTP {nav.get('status')})")
        elif act == "do":
            self.do(p, st, i, str(s.get("what") or ""))
            wf = str(s.get("workflow") or "")
            if wf and not any(f"/api/workflows/{wf}/" in str(c.get("path")) for c in (p.last or {}).get("calls") or []):
                # The step says which process it starts: a screen that did
                # not start it is said, whatever the checks after it find.
                name = next((str(w.get("name")) for w in self.doc.get("workflows") or []
                             if isinstance(w, dict) and str(w.get("id")) == wf), wf)
                self.unstarted.append(f"doing \"{s.get('what')}\" on {self.path(p.url)} did not start {name} ({wf})")
        elif act == "sign_in":
            route = self._sign_in_route()
            if s.get("page") and str(self.pages.get(str(s["page"]), {}).get("pattern") or "") != "auth":
                # From another screen: open it as they would.
                self.goto(p, self.address(s.get("page"), s.get("record")))
            if self._on_sign_in(p):
                # Turned away to the sign-in page: this one, with the address it carries back.
                route = self.path(p.url)
            elif s.get("page") and str(self.pages.get(str(s["page"]), {}).get("pattern") or "") != "auth":
                # Still on the screen: follow its sign-in link, as a person would.
                self.do(p, st, i, "go to sign in")
                route = self.path(p.url) if self._on_sign_in(p) else route
            if not self._sign_in(p, route):
                raise StepFailed(f"{p.name} could not sign in through the form at {route}; "
                                 f"landed on {self.path(p.url)}")
        elif act == "sign_out":
            self.b.call("close", key=p.key)
            self.b.call("person", key=p.key, base=self.app.base)
            p.signed_in, p.url, p.nav, p.last = False, "", None, None
            self.log.append(f"{p.name} signed out")
        elif act == "reload":
            got = self.b.call("reload", key=p.key)
            p.url = str(got.get("url") or p.url)
        elif act == "come_back":
            self.goto(p, "/")
            self.log.append(f"{p.name} came back later")
        elif act == "wait":
            time.sleep(3)
        else:
            raise NotTried(f"step {i} is {act!r}, which the runner does not know")

    def page_at(self, url: str) -> str:
        """The screen an address is, by route."""
        here = self.path(url).split("?", 1)[0]
        best = ""
        for pid, pg in self.pages.items():
            if _route_re(str(pg.get("route"))).match(here) and (not best or "[" not in str(pg.get("route"))):
                best = pid
        return best

    def do(self, p: Person, st: dict, i: int, what: str) -> None:
        says = str(st.get("says") or "")
        if not p.url or p.url.startswith("about:"):
            # Someone who acts before opening anything starts where anyone
            # arriving does: the application's front page.
            self.goto(p, "/")
        self.where = self.page_at(p.url) or self.where
        key = resolve.Recipes.key(str(st.get("id") or says[:40]), i, what)
        recipe = self.recipes.get(key)
        if recipe:
            got = self._replay(p, recipe)
            unsent = got is not None and got.get("invalid") and not any(
                c.get("method") != "GET" for c in got.get("calls") or [])
            if got is not None and not unsent:
                p.last = got
                self._said(p, what, got)
                return
            self.recipes.drop(key)
        done_words: list[str] = []
        kept: list[dict] = []
        merged: dict = {"calls": [], "messages": [], "invalid": [], "errors": [], "dialogs": []}
        for _round in range(resolve.ROUNDS):
            look = self.b.call("look", key=p.key)
            if not look.get("ok"):
                raise StepFailed(f"the screen could not be read: {look.get('error')}")
            by_idx = {int(c["idx"]): c for c in look.get("controls") or []}
            about = [f"{(self.ents.get(str(g.get('entity'))) or {}).get('name') or 'record'} \"{self.label(ref)}\""
                     for ref, g in self.given.items() if self.label(ref)]
            ans = resolve.ask_model(what, says, look, done_words, about=about[:8])
            acts = [a for a in ans.get("actions") or [] if isinstance(a, dict) and a.get("idx") in by_idx]
            if not acts:
                if done_words:
                    break
                why = str(ans.get("cannot") or "no control on it does that")
                raise StepFailed(f"on {self.path(look.get('url'))}, {p.name} could not {what}: {why}")
            got = self._act_looking(p, acts, by_idx)
            self._merge(merged, got)
            blocked = False
            for a in got.get("done") or []:
                c = by_idx.get(int(a.get("idx", -1)), {})
                if not a.get("ok"):
                    # NOT YET, NOT NEVER: a size that opens once a colour is
                    # chosen is pressed after it, as a person would.
                    if "not enabled" in str(a.get("error")) and _round < resolve.ROUNDS - 1:
                        done_words.append(f"{c.get('name') or c.get('field')!r} could not be pressed yet — it is "
                                          "not enabled; choose what it waits for first")
                        merged.setdefault("held_back", []).append(str(c.get("name") or c.get("field") or "a control"))
                        blocked = True
                        break
                    raise StepFailed(f"{p.name} tried to {a.get('do')} {c.get('name') or c.get('field') or 'a control'} "
                                     f"to {what}, and it failed: {a.get('error')}")
                kept.append({"desc": resolve.describe(c), "do": a.get("do"), "value": a.get("value")})
                done_words.append(f"{a.get('do')} {c.get('name') or c.get('field')!r}"
                                  + (f" = {a.get('value')!r}" if a.get("value") not in (None, "") else ""))
            if blocked:
                continue
            if len(got.get("done") or []) < len(acts) and _round < resolve.ROUNDS - 1:
                # The screen changed under the plan: ask again from what it shows.
                continue
            sent = [c for c in got.get("calls") or [] if c.get("method") != "GET"]
            if got.get("invalid") and not sent and _round < resolve.ROUNDS - 1:
                # The form would not send: a person fills in what it asks for.
                done_words.append("the screen would not send and asks for: " + "; ".join(got["invalid"]))
                continue
            if ans.get("done", True):
                break
        p.last, p.url = merged, str(merged.get("url") or p.url)
        self.recipes.put(key, kept)
        self._said(p, what, merged)

    def _act_looking(self, p: Person, acts: list[dict], by_idx: dict[int, dict]) -> dict:
        """The planned actions one at a time, looking again after each: a
        click that opens a dialog or a page leaves the rest of the plan
        pointing at what is now covered or gone. A planned control still on
        the screen (by its description) is used; one that is not ends the
        plan here, and the next round asks again from what the screen shows."""
        merged: dict = {"calls": [], "messages": [], "invalid": [], "errors": [], "dialogs": [], "done": []}
        controls = by_idx
        for n, a in enumerate(acts):
            idx = int(a["idx"])
            if n:
                look = self.b.call("look", key=p.key)
                fresh = {int(c["idx"]): c for c in look.get("controls") or []}
                found = resolve.find(resolve.describe(by_idx.get(idx, {})), list(fresh.values()))
                if found is None:
                    break
                controls, idx = fresh, found
            got = self.b.call("act", key=p.key, actions=[{"idx": idx, "do": a.get("do", "click"), "value": a.get("value")}])
            for d in got.get("done") or []:
                d["idx"] = int(a["idx"])          # reported against the plan's own numbering
            self._merge(merged, got)
            merged["done"] = merged["done"] + list(got.get("done") or [])
            merged["url"] = got.get("url") or merged.get("url")
            if not all(d.get("ok") for d in got.get("done") or []):
                break
        return merged

    def _replay(self, p: Person, recipe: list[dict]) -> dict | None:
        merged: dict = {"calls": [], "messages": [], "invalid": [], "errors": [], "dialogs": []}
        for r in recipe:
            look = self.b.call("look", key=p.key)
            idx = resolve.find(r.get("desc") or {}, look.get("controls") or [])
            if idx is None:
                return None
            got = self.b.call("act", key=p.key, actions=[{"idx": idx, "do": r.get("do"), "value": r.get("value")}])
            self._merge(merged, got)
            if not all(a.get("ok") for a in got.get("done") or []):
                return None
        p.url = str(merged.get("url") or p.url)
        return merged

    @staticmethod
    def _merge(into: dict, got: dict) -> None:
        for k in ("calls", "errors", "dialogs", "held_back"):
            into[k] = (into.get(k) or []) + list(got.get(k) or [])
        for k in ("messages", "invalid", "url"):
            if got.get(k):
                into[k] = got[k]

    def _said(self, p: Person, what: str, got: dict) -> None:
        writes = [c for c in got.get("calls") or [] if c.get("method") != "GET"]
        self.sent += [{"method": c.get("method"), "path": c.get("path"), "status": c.get("status"),
                       "request": str(c.get("sent") or "")[:400], "body": str(c.get("body") or "")[:300]}
                      for c in writes]
        self.log.append(f"{p.name} did: {what} → " + (", ".join(
            f"{c['method']} {c['path']} {c['status']}" + (f" sending {str(c.get('sent'))[:240]}" if c.get("sent") else "")
            for c in writes) or "no request")
                        + (f"; the screen said: {' | '.join(got.get('messages') or [])[:200]}"
                           if got.get("messages") else ""))
        for e in got.get("errors") or []:
            self.also.append(f"while {p.name} did '{what}': {e}")
        for c in got.get("calls") or []:
            if int(c.get("status") or 0) >= 500:
                self.also.append(f"{c.get('method')} {c.get('path')} answered {c.get('status')}: {str(c.get('body'))[:200]}")

    # ── checks ─────────────────────────────────────────────────────────────

    def told(self, got: dict | None) -> tuple[str, str]:
        """What the application answered: success, refusal, error or nothing."""
        if got is None:
            return "nothing", "they had done nothing for the application to answer"
        writes = [c for c in got.get("calls") or [] if c.get("method") != "GET"]
        said = " | ".join(got.get("messages") or [])
        bodies = "; ".join(f"{c['method']} {c['path']} {c['status']} {str(c.get('body'))[:160]}" for c in writes)
        if any(int(c.get("status") or 0) >= 500 for c in writes):
            return "error", bodies
        if any(int(c.get("status") or 0) in REFUSED or '"refused":true' in str(c.get("body") or "").replace(" ", "")
               for c in writes):
            return "refusal", bodies + (f"; the screen said: {said}" if said else "")
        if writes:
            return "success", bodies + (f"; the screen said: {said}" if said else "")
        if got.get("held_back") and not writes:
            # THE SCREEN WOULD NOT LET THEM: a control held disabled (more than
            # the stock, a closed slot) is a refusal made before anything is sent.
            return "refusal", "the screen would not let them: " + ", ".join(sorted(set(got["held_back"]))) + \
                " stayed disabled" + (f"; the screen said: {said}" if said else "")
        if got.get("invalid") or (said and _VALIDATION.search(said)):
            return "refusal", "the screen refused before sending: " + "; ".join(got.get("invalid") or []) + (
                f" {said}" if said else "")
        return "nothing", ("nothing was sent" + (f"; the screen said: {said}" if said else ""))

    def check(self, c: dict, last: Person) -> str | None:
        """None when it holds; what was seen instead when it does not."""
        p = self.person(c.get("as"), c.get("who")) if c.get("as") else last
        kind = str(c.get("check"))
        if kind == "on":
            route = str((self.pages.get(str(c.get("page"))) or {}).get("route") or "")
            here = self.path(p.url).split("?", 1)[0]
            return None if route and _route_re(route).match(here) else f"{p.name} is on {here}, not {route}"
        if kind in ("sees", "not_sees"):
            if c.get("page"):
                self.goto(p, self.address(c.get("page"), c.get("record")))
            text = (p.nav or {}).get("text") or ""
            if not text:
                look = self.b.call("look", key=p.key)
                text = look.get("text") or ""
            want = self.label(str(c["record"])) if c.get("record") else str(c.get("text") or "")
            if not want:
                raise NotTried(f"the check looks for {c.get('record')}, which has nothing to be found by")
            found = _norm(want) in _norm(text)
            if kind == "sees" and not found:
                return f"{p.name} does not see {want!r} on {self.path(p.url)}"
            if kind == "not_sees" and found:
                return f"{p.name} sees {want!r} on {self.path(p.url)}"
            return None
        if kind == "told":
            got, why = self.told(p.last)
            want = str(c.get("told"))
            return None if got == want else f"{p.name} was told {got}, not {want}: {why}"
        if kind == "gets":
            where = self.address(c.get("page"), c.get("record"), c.get("address"))
            nav = self.goto(p, where)
            got = self._gets(nav, where, c)
            want = str(c.get("gets"))
            return None if got == want else (f"opening {where} as {p.name} gave {got} "
                                             f"(landed on {self.path(nav.get('url'))}, HTTP {nav.get('status')}), not {want}")
        if kind in ("stored", "not_stored"):
            return self._stored(c, kind)
        if kind == "sent":
            raise NotTried("what the application sends cannot be seen by the runner yet")
        raise NotTried(f"the check {kind!r} is not one the runner knows")

    def _gets(self, nav: dict, where: str, c: dict) -> str:
        landed = self.path(nav.get("url")).split("?", 1)[0]
        status = int(nav.get("status") or 0)
        head = str(nav.get("text") or "")[:1500]
        if any(_route_re(r).match(landed) for r in self._auth_routes()):
            return "sign_in_asked"
        if status == 404 or _NOT_FOUND.search(head):
            return "not_found"
        if status in (401, 403) or _NOT_ALLOWED.search(head):
            return "not_allowed"
        target = str((self.pages.get(str(c.get("page"))) or {}).get("route") or "") if c.get("page") else ""
        meant = where.split("?", 1)[0]
        if (target and _route_re(target).match(landed)) or landed == meant:
            return "shown"
        return f"sent to {landed}"

    def _matching(self, c: dict) -> tuple[str, list[str], str]:
        """`(table, where, what)` — the rows a stored/not_stored check counts."""
        from services.blueprint.page_review import _query
        from services.blueprint.projection import to_snake
        rec = self.given.get(str(c.get("record") or "").lstrip("@")) if c.get("record") else None
        eid = str(c.get("entity") or (rec or {}).get("entity") or "")
        if eid not in self.ents:
            raise NotTried("the check names no record type to look in")
        table = self._table(eid)
        cols = {r[0] for r in _query(self.app, "select column_name from information_schema.columns "
                                               f"where table_schema = 'public' and table_name = '{table}'") if r}
        if not cols:
            raise NotTried(f"the table {table} could not be read")
        where: list[str] = []
        for f, v in (c.get("values") or {}).items():
            col = to_snake(str(f))
            if col not in cols:
                raise _Missing(f"{self.ents[eid].get('name')} keeps no {f}")
            v = self._value(v)
            if v is None:
                where.append(f'"{col}" is null')
            elif isinstance(v, bool):
                where.append(f'"{col}" = {"true" if v else "false"}')
            elif isinstance(v, (int, float)):
                where.append(f'"{col}"::numeric = {v}')
            else:
                where.append(f"\"{col}\"::text = '{str(v).replace(chr(39), chr(39) * 2)}'")
        if rec is not None:
            where.append(f"id::text = '{rec['id']}'")
        what = f"{self.ents[eid].get('name')} with " + (", ".join(f"{k}={v!r}" for k, v in (c.get("values") or {}).items())
                                                         or "anything")
        return table, where, what

    def _count(self, table: str, where: list[str]) -> int:
        from services.blueprint.page_review import _query
        rows = _query(self.app, f'select count(*) from "{table}"' + (" where " + " and ".join(where) if where else ""))
        if not rows or not rows[0]:
            raise NotTried(f"{table} could not be read")
        return int(rows[0][0] or 0)

    def take_baseline(self, checks: list[dict]) -> None:
        """How many rows already match each stored/not_stored check before
        anyone does anything — what the steps did is the difference. A time
        stamp could not say it: an updated customer keeps the `created_at` it
        had, and a table with no stamp at all matched the copy's own rows."""
        self.baseline = {}
        for c in checks:
            if str(c.get("check")) in ("stored", "not_stored") and not c.get("record"):
                try:
                    table, where, _what = self._matching(c)
                    self.baseline[id(c)] = self._count(table, where)
                except (NotTried, _Missing):
                    continue

    def _stored(self, c: dict, kind: str) -> str | None:
        try:
            table, where, what = self._matching(c)
        except _Missing as exc:
            return str(exc)
        n = self._count(table, where)
        if c.get("record"):
            # One given record: whether it holds those values now.
            if kind == "stored" and n == 0:
                return f"the given {c['record']} is not a {what}"
            if kind == "not_stored" and n > 0:
                return f"the given {c['record']} is a {what}"
            return None
        before = getattr(self, "baseline", {}).get(id(c))
        if before is None:
            if kind == "stored" and n == 0:
                return f"no {what} is stored"
            if kind == "not_stored" and n > 0:
                return f"{n} {what} {'is' if n == 1 else 'are'} stored"
            return None
        if kind == "stored" and n <= before:
            return f"no {what} is stored by what they did ({n} before and after)"
        if kind == "not_stored" and n > before:
            return f"{n - before} {what} {'was' if n - before == 1 else 'were'} stored by what they did"
        return None

    # ── the statement ──────────────────────────────────────────────────────

    def run(self, st: dict) -> dict:
        from services.blueprint.page_review import _query
        t0 = time.monotonic()
        self.signs_in = {self._key(s.get("as"), s.get("who")) for s in st.get("steps") or []
                         if s.get("act") == "sign_in"}
        now = _query(self.app, "select localtimestamp::text")
        self.started = now[0][0] if now and now[0] else ""
        self.stamp = re.sub(r"[^a-z0-9]", "", str(st.get("id") or "").lower()) or "x"
        out: dict = {"id": st.get("id"), "says": st.get("says"), "kind": st.get("kind")}
        failures: list[str] = []
        untried: list[str] = []
        try:
            from services.expects.statements import given_order
            for g in given_order(st.get("given") or []) or (st.get("given") or []):
                self.make_given(g)
            self.take_baseline(st.get("then") or [])
            last: Person | None = None
            for i, s in enumerate(st.get("steps") or [], 1):
                self.step(st, i, s)
                last = self.person(s.get("as"), s.get("who"))
            for c in st.get("then") or []:
                try:
                    miss = self.check(c, last or self.person(None))
                except NotTried as exc:
                    untried.append(f"{c.get('check')}: {exc}")
                    continue
                if miss:
                    failures.append(miss)
            failures += self.unstarted
            verdict = "failed" if failures else ("not_tried" if untried and len(untried) == len(st.get("then") or [])
                                                 else "passed")
        except StepFailed as exc:
            failures.append(str(exc))
            verdict = "failed"
        except NotTried as exc:
            untried.append(str(exc))
            verdict = "not_tried"
        except BrowserGone:
            raise
        except Exception as exc:  # noqa: BLE001 — one statement never ends the run
            logger.exception("[expects] %s", st.get("id"))
            untried.append(f"the runner failed: {type(exc).__name__}: {exc}")
            verdict = "not_tried"
        finally:
            for key in list(self.people):
                try:
                    self.b.call("close", key=key, timeout=30)
                except Exception:  # noqa: BLE001
                    pass
        out.update(verdict=verdict, failures=failures, untried=untried, also=list(dict.fromkeys(self.also))[:12],
                   log=self.log[:40], seconds=round(time.monotonic() - t0, 1),
                   sent=self.sent[:20], where=self.where)
        return out


class Fresh:
    """Every statement starts from the same database: the copy the app runs
    on is kept as a template once (`<copy>_start`), and dropped and made again
    from it before each statement. Statements share no rows — a record one
    statement makes cannot be in the way of the next, and none of them can
    pass on what an earlier one left behind."""

    def __init__(self, app: Any):
        self.app = app
        container, copy, _ = app.clone
        self.container, self.copy, self.start = container, copy, f"{copy}_start"
        self._sql(f'DROP DATABASE IF EXISTS "{self.start}"')
        self._make(self.start, self.copy)

    def _sql(self, sql: str, db: str = "postgres") -> None:
        import subprocess
        if self.container:
            done = subprocess.run(["docker", "exec", self.container, "psql", "-U", "postgres", "-d", db,
                                   "-v", "ON_ERROR_STOP=1", "-c", sql], capture_output=True, text=True, timeout=180)
            if done.returncode != 0:
                raise NotTried(f"the database copy could not be reset: {done.stderr.strip()[-300:]}")
            return
        from services import app_databases
        con = app_databases._connect()
        try:
            with con.cursor() as cur:
                cur.execute(sql)
        finally:
            con.close()

    def _make(self, name: str, template: str) -> None:
        for attempt in (1, 2, 3):
            self._sql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                      f"WHERE datname = '{template}' AND pid <> pg_backend_pid()")
            try:
                self._sql(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
                return
            except NotTried:
                if attempt == 3:
                    raise
                time.sleep(1)

    def reset(self) -> None:
        """The copy's rows put back as they were, in place. Dropping the copy
        and making it again cut the server's connections, and the next sign-in
        or save after it failed on a dead connection (57P01), so a statement
        was judged on the reset rather than on the application."""
        import subprocess
        tables = self._tables()
        if not tables:
            raise NotTried("the database copy has no tables to reset")
        listed = ", ".join(f'public."{t}"' for t in tables)
        if self.container:
            script = (f"psql -U postgres -d {self.copy} -v ON_ERROR_STOP=1 -q -c 'TRUNCATE {listed} RESTART IDENTITY CASCADE' "
                      f"&& pg_dump -U postgres --data-only --disable-triggers --schema=public {self.start} "
                      f"| psql -U postgres -q -v ON_ERROR_STOP=1 -d {self.copy} > /dev/null")
            done = subprocess.run(["docker", "exec", self.container, "sh", "-c", script],
                                  capture_output=True, text=True, timeout=300)
            if done.returncode != 0:
                raise NotTried(f"the database copy could not be reset: {done.stderr.strip()[-300:]}")
            return
        import io
        from services import app_databases
        src, dst = app_databases._connect(self.start), app_databases._connect(self.copy)
        try:
            with src.cursor() as a, dst.cursor() as b:
                b.execute("SET session_replication_role = replica")
                b.execute(f"TRUNCATE {listed} RESTART IDENTITY CASCADE")
                for t in tables:
                    buf = io.StringIO()
                    a.copy_expert(f'COPY public."{t}" TO STDOUT', buf)
                    buf.seek(0)
                    b.copy_expert(f'COPY public."{t}" FROM STDIN', buf)
                b.execute("SET session_replication_role = origin")
        finally:
            src.close()
            dst.close()

    def _tables(self) -> list[str]:
        from services.blueprint.page_review import _query
        return [r[0] for r in _query(self.app, "select tablename from pg_tables where schemaname = 'public' "
                                               "order by 1") if r and r[0]]

    def close(self) -> None:
        try:
            self._sql(f'DROP DATABASE IF EXISTS "{self.start}" WITH (FORCE)')
        except Exception:  # noqa: BLE001 — a leftover template is not a failed run
            logger.warning("[expects] could not drop %s", self.start)


def warm(app: Any, doc: dict) -> None:
    """Every screen asked for once, signed in as the administrator, before
    anyone uses it: a dev server compiles a page on its first visit, and a
    screen asked for signed out is turned away before it is compiled. A
    person who waited half a minute for that would be judged on the wait."""
    import http.cookiejar
    import urllib.parse
    import urllib.request
    from services.blueprint.page_review import ADMIN_EMAIL, ADMIN_PASSWORD
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        csrf = json.loads(opener.open(app.base + "/api/auth/csrf", timeout=60).read() or b"{}").get("csrfToken", "")
        form = urllib.parse.urlencode({"csrfToken": csrf, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
                                       "json": "true"}).encode()
        opener.open(app.base + "/api/auth/callback/credentials", data=form, timeout=60).read(100)
    except Exception:  # noqa: BLE001 — signed out still compiles the public screens
        logger.info("[expects] warming signed out")
    for p in _live(doc.get("pages")):
        route = re.sub(r"\[[^\]]+\]", "x", str(p.get("route") or ""))
        if not route:
            continue
        try:
            opener.open(app.base + route, timeout=180).read(200)
        except Exception:  # noqa: BLE001 — a redirect or a 404 has compiled it all the same
            pass


def _office(project_dir: Path) -> Callable[..., None]:
    """What this project's office is shown, or nothing when none is bound."""
    try:
        from services.office_bridge import office_for
        from services.office_events import trial_event
        emit = office_for(project_dir)
    except Exception:  # noqa: BLE001
        return lambda *a: None
    if emit is None:
        return lambda *a: None

    def show(kind: str, *args: str) -> None:
        try:
            if kind == "trial":
                emit(trial_event(*args))
        except Exception:  # noqa: BLE001 — a picture never breaks a trial
            pass
    return show


def run(app: Any, doc: dict, project_dir: Path, *, only: list[str] | None = None,
        emit: Callable[[dict], None] | None = None, restore: bool = False) -> dict:
    """Every statement (or `only` those ids) tried on the running copy. With
    `restore`, the copy is put back as it was afterwards — a turn's trials
    share it. The results file keeps each statement's latest result: a run of
    some statements updates those and keeps the rest."""
    rows = [st for st in expectations(doc) if not only or str(st.get("id")) in only]
    # The template first: making it disconnects the server once, and the
    # warm-up's requests are what find and replace those connections.
    fresh = Fresh(app)
    warm(app, doc)
    recipes = resolve.Recipes(project_dir / ".forge" / "expects" / "recipes.json")
    results: list[dict] = []
    # THE WORKBENCH ON SCREEN: each statement as it is tried, as the person
    # it is about, and what it found (`office_events.trial_event`).
    show = _office(project_dir)
    try:
        sessions: dict = {}
        with Browser(project_dir / ".forge" / "expects" / "browser") as b:
            for n, st in enumerate(rows):
                if n:
                    fresh.reset()
                who = next((str(s.get("as") or "") for s in st.get("steps") or [] if isinstance(s, dict)
                            and s.get("as")), "")
                show("trial", str(st.get("id") or ""), str(st.get("says") or ""), "trying", who)
                res = Trial(app, doc, b, recipes, Logins(app, doc), sessions).run(st)
                results.append(res)
                show("trial", str(res.get("id") or st.get("id") or ""), str(st.get("says") or ""),
                     str(res.get("verdict") or "not_tried"), who)
                if emit:
                    emit(res)
        if restore and rows:
            fresh.reset()
    finally:
        fresh.close()
    summary = {k: sum(1 for r in results if r["verdict"] == k) for k in ("passed", "failed", "not_tried")}
    report = {"summary": summary, "results": results, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    path = project_dir / ".forge" / "expects" / "results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    kept: dict[str, dict] = {}
    if only:
        try:
            kept = {str(r.get("id")): r for r in json.loads(path.read_text()).get("results") or []}
        except (OSError, ValueError):
            kept = {}
    kept.update({str(r["id"]): r for r in results})
    live = {str(st.get("id")) for st in expectations(doc)}
    path.write_text(json.dumps({**report, "results": [r for k, r in kept.items() if k in live]},
                               indent=1, default=str))
    return report


def main(argv: list[str]) -> int:
    """`python -m services.expects.runner <project dir> [EXP-001 …]`"""
    from services.blueprint.page_review import RunningApp
    from services.blueprint.service import BlueprintService
    project = Path(argv[0]).resolve()
    doc = BlueprintService.load(output_dir=str(project)).doc
    from services.blueprint.assembly import VERIFY_DIST_DIR
    with RunningApp(project / "app", log=project / ".forge" / "expects" / "server.log",
                    mode="production", dist_dir=VERIFY_DIST_DIR) as app:
        def show(r: dict) -> None:
            print(f"{r['id']} {r['verdict'].upper():10} {r['seconds']:>5}s  {r['says']}", flush=True)
            for f in r["failures"] + r["untried"]:
                print(f"      - {f}", flush=True)
        report = run(app, doc, project, only=argv[1:] or None, emit=show)
    print(json.dumps(report["summary"]))
    return 0


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    raise SystemExit(main(sys.argv[1:]))
