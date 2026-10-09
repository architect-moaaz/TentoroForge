"""Smith tries the application, the way a person would (§0, "the whole dev team").

Reads show what the code SAYS. A tester's report is about what the app DOES,
and the two parted on every F&B report Smith got wrong (UAT fxa532bj,
2026-10-01):

* "while adding category it says the category already exists, however it
  does not" — answered "Nothing needed doing" twice, after twelve steps of
  reading. The page and the workflow read correctly; the runtime's lookup
  matched every row when its key was missing. Only running the workflow
  shows that.
* "not able to add food and beverages as admin" — answered "nothing has been
  reported as crashing", because the only window onto behaviour was the
  crash log.
* "once admin logs in, it lands on the unauthenticated dashboard" — `/login`
  was rewritten; where a sign-in lands is decided elsewhere, and opening `/`
  as the admin shows where they land.
* "the admin notifications are not seen" — a "mark as read" workflow was
  added; asking the app for the admin's notifications shows there are none.

So a turn can now TRY: run a workflow as a role, make a request as a role,
open a page as a role. Each runs against a COPY of the app's database on the
app's own dev server (`page_review.RunningApp`, the review's machinery) — the
person's data is never written. One copy serves a whole turn; a change to the
data model starts a fresh one, since the copy was taken before it.

WHAT IS SHOWN. What the app answered, where it ended up, what it wrote — as
rows added and removed per table, fields whose names say they hold secrets
dropped — and what the server printed while it ran. Everything goes through
`secrets_scrub` on the way out, like every read.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from services.smith.secrets_scrub import scrub

logger = logging.getLogger(__name__)

TRIALS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("try_workflow",
     "Run one of the app's processes the way its button would, signed in as "
     "`as` (a role; left out, the administrator; `signed out` for a visitor), "
     "with `input` as the form would send it. Runs on a copy of the data, so "
     "nothing real changes. Shows whether it finished, each step's result or "
     "error, the rows it wrote and what the server printed. Use it when "
     "someone says a button or a save does not work — before deciding what "
     "is wrong, and again after changing it to show it now works.",
     {"workflow": "string", "input": "object", "as": "string"}),
    ("try_request",
     "Ask the running app for something over HTTP, signed in as `as`: "
     "`GET /api/notifications`, `GET /api/data/orders`, a `POST` with `body`. "
     "Shows the status, where it redirected, and the answer. On a copy of "
     "the data.",
     {"method": "string", "path": "string", "body": "object", "as": "string"}),
    ("open_page",
     "Open a screen in a browser signed in as `as` and press its controls. "
     "Shows where it ended up, the text on it, errors in the browser, and "
     "what each button did. A route with `[id]` opens the first record. "
     "`sign_in: true` instead signs in through the sign-in page's own form, "
     "as the administrator, and shows where that lands — the only way to see "
     "where a sign-in takes someone. On a copy of the data.",
     {"route": "string", "as": "string", "sign_in": "boolean"}),
)

TRIALS = TRIALS + (
    ("try_upload",
     "Upload a small picture (`kind`: image) or a small PDF (`kind`: file) as "
     "`as`, the way a form's picker does, then read it back the way a screen "
     "shows it. Where \"I attached an image and it does not show\" starts: "
     "whether the app can keep a file at all. The id it returns is what a "
     "workflow's image or file input takes, for a `try_workflow` after it.",
     {"kind": "string", "as": "string"}),
)

TRIALS = TRIALS + (
    ("try_expectation",
     "Try one of the application's statements of what must happen (`statement`: its `EXP-…` id, "
     "listed under \"What must happen\") the way the build does: its records made, each step done in "
     "a browser as its person, each check judged from what the app showed and stored. Shows whether it "
     "holds and, when it does not, what was seen instead. When a statement covers what someone says "
     "does not work, try it before changing anything; after a change, try it again to show it holds. "
     "On a copy of the data, put back as it was afterwards.",
     {"statement": "string"}),
)

TRIAL_NAMES: frozenset[str] = frozenset(name for name, _d, _a in TRIALS)

#: A 1×1 PNG and a one-page PDF: the smallest files each picker accepts.
_PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                     "1f15c4890000000d49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082")
_PDF = (b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>"
        b"endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 10 10]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")

#: Words that mean nobody is signed in.
SIGNED_OUT = frozenset({"signed out", "signed-out", "anonymous", "visitor", "guest", "public",
                        "nobody", "logged out", "none"})
#: Tables a run writes as bookkeeping, not as the application's records.
BOOKKEEPING = frozenset({"workflow_execution_log", "forge_events", "_forge_seed_meta",
                         "workflow_instances", "forge_schedules"})
#: A table with more rows than this is compared by count alone.
DIFF_ROWS_UP_TO = 2000
#: Rows shown per table and per direction.
ROWS_SHOWN = 6
#: A column whose name says it holds a secret is never shown.
_SECRET_COLUMN = re.compile(r"pass|hash|secret|token|salt|otp|api_?key|private", re.I)
#: Lines of server output worth showing: errors and stack heads.
_SERVER_ERROR = re.compile(r"⨯|error|Error|ERR_|Unhandled|failed|Failed|exception|Exception")
BODY_SHOWN = 3000


class TrialUnavailable(RuntimeError):
    """The app could not be started for a trial. The message is the observation."""


class Bench:
    """One running copy of the application for a turn: started on the first
    trial, stopped when the turn ends (`close`), started again after a change
    to the data model (`reset`)."""

    def __init__(self, output_dir: str, *, factory: Callable[..., Any] | None = None):
        self.output_dir = output_dir
        self._factory = factory
        self._app: Any = None
        self._log_at = 0
        self.log = Path(output_dir) / ".forge" / "trials" / "server.log"
        #: The last `try_workflow`'s tables before and after it ran.
        self.last_written: tuple[dict[str, Any], dict[str, Any]] | None = None
        #: ONE SIGNED-OUT VISITOR FOR THE TURN. A shopper's browser keeps the
        #: `forge-guest` cookie between adding to the bag and opening it; each
        #: trial used to arrive as a stranger, so TCommerce's guest bag read
        #: empty on the bench and Smith blamed a cart page that worked
        #: (2026-10-06). Every signed-out trial carries this token.
        import uuid as _uuid
        self.guest = str(_uuid.uuid4())

    def app(self) -> Any:
        if self._app is None:
            from services.blueprint.page_review import ReviewUnavailable, RunningApp
            factory = self._factory or RunningApp
            self.log.parent.mkdir(parents=True, exist_ok=True)
            self.log.write_bytes(b"")
            self._log_at = 0
            import uuid
            app = factory(Path(self.output_dir) / "app", log=self.log,
                          dist_dir=f".next-trial-{uuid.uuid4().hex[:6]}")
            try:
                self._app = app.__enter__()
            except ReviewUnavailable as exc:
                raise TrialUnavailable(f"The app could not be started to try this: {exc}") from exc
        return self._app

    def server_said(self) -> list[str]:
        """Error lines the server printed since the last call."""
        try:
            data = self.log.read_bytes()
        except OSError:
            return []
        fresh, self._log_at = data[self._log_at:], len(data)
        lines = [l.strip() for l in fresh.decode("utf-8", "replace").splitlines()]
        return [l[:300] for l in lines if l and _SERVER_ERROR.search(l)][:15]

    def reset(self) -> None:
        self.close()

    def close(self) -> None:
        if self._app is not None:
            try:
                self._app.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 — a leftover copy is not a failed turn
                logger.warning("[trials] could not stop the bench", exc_info=True)
            self._app = None

    @property
    def running(self) -> bool:
        return self._app is not None


# ── who is signed in ────────────────────────────────────────────────────────


def _role(doc: dict, ref: str) -> tuple[str, bool]:
    """`(role name, is the administrator's)` for what the call said, or
    `("", False)` for signed out. Left out means the administrator."""
    from services.blueprint.account_model import admin_role
    admin = admin_role(doc) or "Admin"
    want = (ref or "").strip()
    if not want or want.lower() in ("admin", "administrator", admin.lower()):
        return admin, True
    if want.lower() in SIGNED_OUT:
        return "", False
    for r in doc.get("roles") or []:
        if not isinstance(r, dict):
            continue
        if want.lower() in (str(r.get("id") or "").lower(), str(r.get("name") or "").lower()):
            name = str(r.get("name") or r.get("id"))
            return name, name == admin
    known = ", ".join(str(r.get("name")) for r in doc.get("roles") or [] if isinstance(r, dict))
    raise ValueError(f"no role called {want!r}; the app's roles are {known or 'none'}, or `signed out`")


def default_person(doc: dict, *, route: str = "", flow: dict | None = None) -> str:
    """Who a trial is when the call names nobody: the person the screen or the
    process is FOR. It was always the administrator, and an administrator
    cannot change a customer's cart: ToroCommerce's fixed minus button was
    tried as Admin, refused with 422, and reported "still does not work"
    (measured on a copy, 2026-10-07). A screen only some roles may open is
    theirs; a process only some roles may start is theirs; anything else is
    the application's own audience — the role people sign up as — and the
    administrator only when there is none."""
    from services.blueprint.account_model import admin_role, signup_role
    from services.blueprint.projection import launch_roles, restricted_roles

    admin = admin_role(doc) or "Admin"
    audience = signup_role(doc) or admin
    if flow is not None:
        runs = launch_roles(doc).get(str(flow.get("id"))) or []
        named = [r for r in runs if r not in ("*", "@signed-in")]
        if runs and len(named) == len(runs):
            return audience if audience in named else named[0]
        return audience
    path = route.split("?", 1)[0]
    page = next((p for p in doc.get("pages") or [] if isinstance(p, dict) and str(p.get("route")) == path), None)
    if page is not None:
        if str(page.get("access") or "") == "public" and not page.get("users"):
            return audience
        mine = restricted_roles(doc, page)
        if mine:
            return audience if audience in mine else mine[0]
    return audience


def _session(app: Any, doc: dict, ref: str, guest: str | None = None) -> tuple[str, list[dict]]:
    """`(who, cookies)` — the administrator's seeded login, a login of the
    role on the copy, or a preview session for the role; signed out, only the
    turn's guest token (`Bench.guest`), so it is the same visitor each time."""
    from services.blueprint.page_review import ADMIN_EMAIL, login_of_role
    from services.preview_session import Session, cookies
    from services.seed_backstop import _ADMIN_UUID

    role, is_admin = _role(doc, ref)
    if not role:
        if not guest:
            return "signed out", []
        return ("signed out (the same visitor in every signed-out trial this turn)",
                [{"name": "forge-guest", "value": guest, "url": app.base}])
    if is_admin:
        who = Session(sub=_ADMIN_UUID, name="Admin", email=ADMIN_EMAIL, role=role)
    else:
        found = login_of_role(app, doc, role)
        who = (Session(sub=found[0], name=found[1], email=f"{role.lower().replace(' ', '.')}@example.com",
                       role=role) if found else
               Session(sub=f"preview-{role.lower().replace(' ', '-')}", name=f"{role} (preview)",
                       email=f"{role.lower().replace(' ', '.')}@example.com", role=role))
    return f"{who.name} ({role})", cookies(who, base_url=app.base)


# ── what the database holds ─────────────────────────────────────────────────


def _tables(app: Any) -> list[str]:
    from services.blueprint.page_review import _query
    rows = _query(app, "select table_name from information_schema.tables "
                       "where table_schema = 'public' and table_type = 'BASE TABLE' order by 1")
    return [r[0] for r in rows if r and r[0] and r[0] not in BOOKKEEPING]


def _snapshot(app: Any, tables: list[str]) -> dict[str, Any]:
    """Each table's rows as text (a set), or its count when it is large."""
    from services.blueprint.page_review import _query
    out: dict[str, Any] = {}
    for t in tables:
        q = '"' + t.replace('"', '""') + '"'
        n = _query(app, f"select count(*) from {q}")
        count = int(n[0][0]) if n and n[0] and str(n[0][0]).isdigit() else 0
        if count > DIFF_ROWS_UP_TO:
            out[t] = count
            continue
        rows = _query(app, f"select replace(row_to_json(t)::text, E'\\n', ' ') from {q} t")
        out[t] = {r[0] for r in rows if r}
    return out


def _without_secrets(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _without_secrets(v) for k, v in data.items() if not _SECRET_COLUMN.search(str(k))}
    if isinstance(data, list):
        return [_without_secrets(v) for v in data]
    return data


def _shown(row: str, cap: int = 300) -> str:
    try:
        data = json.loads(row)
    except ValueError:
        return row[:cap]
    text = json.dumps(_without_secrets(data), default=str)
    return text[:cap] + (" …" if len(text) > cap else "")


def _diff(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for t in sorted(set(before) | set(after)):
        b, a = before.get(t), after.get(t)
        if isinstance(b, int) or isinstance(a, int):
            nb = b if isinstance(b, int) else len(b or ())
            na = a if isinstance(a, int) else len(a or ())
            if nb != na:
                lines.append(f"{t}: {nb} -> {na} rows")
            continue
        added, removed = sorted((a or set()) - (b or set())), sorted((b or set()) - (a or set()))
        if not added and not removed:
            continue
        lines.append(f"{t}: {len(added)} row(s) now, {len(removed)} row(s) before "
                     "(a changed row shows in both)")
        lines += [f"  + {_shown(r)}" for r in added[:ROWS_SHOWN]]
        lines += [f"  - {_shown(r)}" for r in removed[:ROWS_SHOWN]]
    return lines or ["no rows were written"]


# ── the three trials ────────────────────────────────────────────────────────


def _http(app: Any, method: str, path: str, body: Any, cookies: list[dict]) -> tuple[int, str, str]:
    """`(status, where it redirected, body)`. Redirects are reported, not followed."""
    class _Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a: Any, **k: Any) -> None:  # noqa: D401
            return None

    data = json.dumps(body).encode() if body is not None and method != "GET" else None
    req = urllib.request.Request(
        app.base + path, data=data, method=method,
        headers={"content-type": "application/json",
                 "cookie": "; ".join(f"{c['name']}={c['value']}" for c in cookies)})
    opener = urllib.request.build_opener(_Stay)
    try:
        with opener.open(req, timeout=240) as r:
            return r.status, "", r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("location") or "", e.read().decode("utf-8", "replace")


def _body(text: str) -> str:
    try:
        text = json.dumps(json.loads(text), default=str)
    except ValueError:
        pass
    return text[:BODY_SHOWN] + (" …(cut)" if len(text) > BODY_SHOWN else "")


def try_workflow(bench: Bench, doc: dict, ref: str, payload: Any, as_: str) -> str:
    from services.blueprint.page_review import _query
    from services.smith.section_change import find_named, names

    flows = [w for w in doc.get("workflows") or [] if isinstance(w, dict)]
    flow = find_named(flows, ref, id_prefix="FLOW-")
    if flow is None:
        return f"No process called {ref!r}. The app has: {names(flows)}."
    app = bench.app()
    as_ = as_ or default_person(doc, flow=flow)
    who, jar = _session(app, doc, as_, bench.guest)
    tables = _tables(app)
    before = _snapshot(app, tables)
    bench.server_said()
    # The run's steps are the log rows written after this moment, by the
    # database's own clock (the copy's, not this process's).
    mark = _query(app, "select coalesce(max(created_at), 'epoch')::text from workflow_execution_log")
    started = mark[0][0] if mark and mark[0] else "epoch"
    payload = dict(payload) if isinstance(payload, dict) else {}
    def reach(table: str) -> list[str] | None:
        """The ids this person reaches in `table`, through the app's own data
        access as them (ownership rules apply); None when it would not say."""
        code, _w, body = _http(app, "GET", f"/api/data/{table}?limit=5", None, jar)
        if code != 200:
            return None
        try:
            rows = json.loads(body).get("data")
        except (ValueError, AttributeError):
            return None
        return [str(r.get("id")) for r in rows or [] if isinstance(r, dict) and r.get("id")]

    filled = fill_records(app, doc, flow, payload, reach=reach)
    status, _where, text = _http(app, "POST", f"/api/workflows/{flow.get('id')}/execute",
                                 {"input": payload}, jar)
    after = _snapshot(app, tables)
    # Kept whole for whoever reads the run back (`round_trips`): the report
    # below cuts a wide row at 300 characters.
    bench.last_written = (before, after)
    steps = _query(app, "select step_index, node_label, action_type, status, coalesce(error, ''), "
                        "replace(coalesce(outputs::text, ''), E'\\n', ' ') "
                        f"from workflow_execution_log where created_at > '{started.replace(chr(39), '')}' "
                        "order by created_at, step_index limit 40")
    out = [f"{flow.get('name')} ({flow.get('id')}) run as {who}: HTTP {status}",
           f"answer: {_body(text)}"]
    if filled:
        out.insert(1, "filled with real records: " + "; ".join(filled))
    if status == 403:
        out += launch_rights(bench.output_dir, doc, flow)
    if steps:
        out.append("steps:")
        # WHAT EACH STEP HANDED ON. F&B's duplicate check read
        # `count(check_existing.output)` from a query whose result had no
        # `output`; the status said "completed" and only the value shows why
        # the next step went the wrong way.
        for r in steps:
            out.append(f"  {r[0]}. {r[1] or '?'} [{r[2]}] {r[3]}"
                       + (f" — {r[4][:300]}" if len(r) > 4 and r[4] else ""))
            if len(r) > 5 and r[5]:
                out.append(f"     output: {_shown(r[5], 500)}")
    out.append("written:")
    out += _diff(before, after)
    said = bench.server_said()
    if said:
        out.append("the server printed:")
        out += [f"  {l}" for l in said]
    return scrub("\n".join(out))


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _an_id(value: Any) -> bool:
    if isinstance(value, dict):
        value = value.get("id")
    return isinstance(value, (str, int)) and bool(_UUID.match(str(value)) or str(value).isdigit())


def fill_records(app: Any, doc: dict, flow: dict, payload: dict,
                 reach: Callable[[str], list[str] | None] | None = None) -> list[str]:
    """A required record input given nothing, or something that is not an id
    ("first"), takes a real record of its kind from the copy — the newest —
    and a declared `<name>Id` beside it takes the same id. TCommerce's empty
    bag was never reproduced: Smith sent `productVariant: "first"`, was told
    "needs productVariantId", sent that, was told "needs productVariant", and
    ran out of steps (measured on a copy, 2026-10-07). Returns what was filled,
    for the observation; a value that is an id is never replaced."""
    from services.blueprint.page_review import _query

    ents = {str(e.get("id")): e for e in (doc.get("data") or {}).get("entities") or [] if isinstance(e, dict)}
    declared = {str(i.get("name")): i for i in flow.get("inputs") or [] if isinstance(i, dict) and i.get("name")}
    said: list[str] = []
    for name, spec in declared.items():
        ent = ents.get(str(spec.get("entity") or ""))
        if spec.get("kind") != "record" or ent is None or _an_id(payload.get(name)):
            continue
        if not spec.get("required") and name not in payload:
            continue
        table = str(ent.get("table") or "")
        if not table or not table.replace("_", "").isalnum():
            continue
        cols = {r[0] for r in _query(app, "select column_name from information_schema.columns "
                                          f"where table_schema = 'public' and table_name = '{table}'") if r}
        label = "".join("_" + c.lower() if c.isupper() else c for c in str(ent.get("labelField") or ""))
        shown = f', "{label}"::text' if label and label in cols else ""
        order = " order by created_at desc nulls last" if "created_at" in cols else ""
        # ONE OF THEIRS. The newest row was another customer's cart line, the
        # app refused it correctly, and the turn read the refusal as the
        # fault (ToroCommerce copy, 2026-10-07). Read as the person when the
        # app will say; the newest row only when it will not.
        theirs = reach(table) if reach else None
        if theirs is not None and not theirs:
            said.append(f"{name}: this person has no {ent.get('name')} — make one first (as them) to try this")
            continue
        where = (" where id::text in (" + ", ".join("'" + t.replace("'", "") + "'" for t in theirs) + ")"
                 if theirs else "")
        rows = _query(app, f'select id::text{shown} from "{table}"{where}{order} limit 1')
        if not rows or not rows[0]:
            said.append(f"{name}: no {ent.get('name')} exists to use")
            continue
        rid = rows[0][0]
        payload[name] = rid
        said.append(f"{name} = {ent.get('name')} {rows[0][1] if len(rows[0]) > 1 and rows[0][1] else ''} ({rid})".replace("  ", " "))
        twin = f"{name}Id"
        if twin in declared and not _an_id(payload.get(twin)):
            payload[twin] = rid
            said.append(f"{twin} = the same id")
    return said


def launch_rights(output_dir: str, doc: dict, flow: dict) -> list[str]:
    """Why a run was refused for the role: who the APP lets launch the process
    — its own `launch-roles.ts`, the file the execute route reads — and where
    that comes from in the definition.

    TCommerce's published app refused the administrator's every save with
    "This action is not available to your role"; the file said `[]` for every
    admin process, and Smith, never shown it, read code around it for two
    turns and asked the owner which screen it was on (2026-10-05)."""
    import re as _re

    file = Path(output_dir) / "app" / "src" / "lib" / "workflows" / "launch-roles.ts"
    try:
        text = file.read_text("utf-8")
    except OSError:
        return [f"who may launch it: {file.relative_to(Path(output_dir))} is missing — every launch is refused "
                "or admitted by default; `sync_app` writes it from the definition"]
    from services.blueprint.projection import _workflow_slug
    keys = [str(flow.get("id") or ""), _workflow_slug(flow)]
    m = next((_re.search(r'"%s"\s*:\s*(\[[^\]]*\]|null)' % _re.escape(k), text) for k in keys
              if _re.search(r'"%s"\s*:' % _re.escape(k), text)), None)
    said = m.group(1) if m else "(no entry: anyone may launch it)"
    pages = {str(pg.get("id")): pg for pg in doc.get("pages") or [] if isinstance(pg, dict)}
    froms = []
    for pid in flow.get("launchedFrom") or []:
        pg = pages.get(str(pid)) or {}
        froms.append(f"{pid} {pg.get('route', '?')} (access {pg.get('access') or 'authenticated'}, "
                     f"users {pg.get('users') or 'none named'}{', ' + pg['status'] if pg.get('status') == 'DEPRECATED' else ''})")
    return [
        f"who may launch it, as the app reads it: app/src/lib/workflows/launch-roles.ts says {flow.get('id')}: {said}"
        + (" — [] admits nobody" if said.replace(" ", "") == "[]" else ""),
        "  that file is written from the definition: the roles of the pages the process is launched from "
        "(a public page admits everyone, a signed-in page any signed-in role, a role-restricted page the "
        "roles it names) — " + ("; ".join(froms) if froms else "it names no launching page"),
        "  fix it where it comes from — who may open those pages (`edit_access`), or the pages the process "
        "is launched from — never by editing the file, which the next sync rewrites; `sync_app` rewrites it "
        "now if the definition is already right",
    ]


def try_request(bench: Bench, doc: dict, method: str, path: str, body: Any, as_: str) -> str:
    method = (method or "GET").strip().upper()
    path = (path or "").strip()
    if not path.startswith("/"):
        return "`path` is the app's own path, starting with `/` — `/api/notifications`."
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        return f"`method` is GET, POST, PUT, PATCH or DELETE, not {method!r}."
    app = bench.app()
    if not as_:
        from services.blueprint.projection import _workflow_slug
        m = re.match(r"^/api/workflows/([^/]+)/execute", path)
        flow = next((w for w in doc.get("workflows") or [] if isinstance(w, dict) and m
                     and m.group(1) in (str(w.get("id")), _workflow_slug(w))), None) if m else None
        as_ = default_person(doc, flow=flow) if flow else default_person(doc, route=path)
    who, jar = _session(app, doc, as_, bench.guest)
    tables = _tables(app) if method != "GET" else []
    before = _snapshot(app, tables) if tables else {}
    bench.server_said()
    status, where, text = _http(app, method, path, body, jar)
    out = [f"{method} {path} as {who}: HTTP {status}" + (f", redirected to {where}" if where else ""),
           f"answer: {_body(text)}"]
    if tables:
        out.append("written:")
        out += _diff(before, _snapshot(app, tables))
    said = bench.server_said()
    if said:
        out.append("the server printed:")
        out += [f"  {l}" for l in said]
    return scrub("\n".join(out))


def open_page(bench: Bench, doc: dict, route: str, as_: str, sign_in: bool = False) -> str:
    from services.blueprint.page_review import BROKEN_OUTCOMES, ReviewUnavailable, run_shots

    route = (route or "").strip()
    if sign_in:
        return _sign_in(bench, doc, route, as_)
    if not route.startswith("/"):
        return "`route` is a screen's path, starting with `/`."
    pages = [p for p in doc.get("pages") or [] if isinstance(p, dict)]
    page = next((p for p in pages if str(p.get("route") or "") == route), None)
    ents = {str(e.get("id")): e for e in (doc.get("data") or {}).get("entities") or []}
    ent = ents.get(str(((page or {}).get("data") or {}).get("primaryEntity") or ""))
    app = bench.app()
    as_ = as_ or default_person(doc, route=route)
    who, jar = _session(app, doc, as_, bench.guest)
    role, is_admin = _role(doc, as_)
    entry: dict[str, Any] = {"id": str((page or {}).get("id") or "trial"), "route": route,
                             "entity": (ent or {}).get("name"), "as": who}
    if not role:
        # Signed out, but the same visitor: the guest cookie and nothing else.
        if jar:
            entry["cookies"] = jar
        else:
            entry["anonymous"] = True
    elif not is_admin:
        entry["cookies"] = jar
    bench.server_said()
    try:
        shot = run_shots(app, [entry], Path(bench.output_dir) / ".forge" / "trials" / "shots",
                         states=False)[0]
    except ReviewUnavailable as exc:
        return f"The page could not be opened in a browser: {exc}"
    if shot.get("skipped"):
        return f"{route} as {who}: not opened — {shot['skipped']}."
    out = [f"{shot.get('url') or route} as {who}: HTTP {shot.get('status')}"
           + (f", ended up at {shot['landed']}" if shot.get("landed") and shot["landed"] != shot.get("url") else "")]
    if shot.get("state"):
        out.append(f"the page says it is: {shot['state']}")
    out += [f"browser error: {e}" for e in shot.get("errors") or []]
    controls = shot.get("controls") or []
    if controls:
        out.append("controls, each pressed from a fresh load:")
        for c in controls:
            verdict = BROKEN_OUTCOMES.get(str(c.get("outcome")), str(c.get("outcome")))
            out.append(f"  {c.get('kind')} \"{c.get('label')}\": {verdict}"
                       + (f" ({c.get('detail')})" if c.get("detail") else ""))
    text = " ".join(str(shot.get("text") or "").split())
    out.append(f"text on the page: {text[:BODY_SHOWN]}" if text else "the page shows no text")
    said = bench.server_said()
    if said:
        out.append("the server printed:")
        out += [f"  {l}" for l in said]
    return scrub("\n".join(out))


def _sign_in(bench: Bench, doc: dict, route: str, as_: str) -> str:
    """Sign in through the form as the administrator; where it lands."""
    from services.blueprint.page_review import ReviewUnavailable, run_shots

    role, is_admin = _role(doc, as_)
    if not is_admin:
        return ("Only the administrator's sign-in can be tried: the seeded administrator's "
                "password is the one known. To see another role's pages, `open_page` "
                "with `as` opens them already signed in as that role.")
    if not route:
        auth = [str(p.get("route")) for p in doc.get("pages") or []
                if isinstance(p, dict) and str(p.get("pattern") or "") == "auth"]
        route = next((r for r in auth if "login" in r or "sign-in" in r or "signin" in r), "/login")
    app = bench.app()
    bench.server_said()
    try:
        shot = run_shots(app, [{"id": "sign-in", "route": route, "signIn": True, "as": role}],
                         Path(bench.output_dir) / ".forge" / "trials" / "shots", probe=False, states=False)[0]
    except ReviewUnavailable as exc:
        return f"The sign-in could not be tried in a browser: {exc}"
    out = [f"signed in as the administrator ({role}) through the form at {route}: "
           f"landed on {shot.get('landed') or '?'}"]
    out += [f"browser error: {e}" for e in shot.get("errors") or []]
    text = " ".join(str(shot.get("text") or "").split())
    out.append(f"text on the page: {text[:BODY_SHOWN]}" if text else "the page shows no text")
    said = bench.server_said()
    if said:
        out.append("the server printed:")
        out += [f"  {l}" for l in said]
    return scrub("\n".join(out))


def _upload(bench: Bench, doc: dict, kind: str, as_: str) -> tuple[str, str, int, str, list[dict], Any]:
    """Upload a small picture (or PDF) as a role: (who, filename, status, body, cookies, app)."""
    import uuid as _uuid
    pdf = (kind or "").strip().lower() in ("file", "pdf", "document")
    data, name, ctype = (_PDF, "trial.pdf", "application/pdf") if pdf else (_PNG, "trial.png", "image/png")
    app = bench.app()
    who, jar = _session(app, doc, as_, bench.guest)
    boundary = _uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(app.base + "/api/files/upload", data=body, method="POST", headers={
        "content-type": f"multipart/form-data; boundary={boundary}",
        "cookie": "; ".join(f"{c['name']}={c['value']}" for c in jar)})
    bench.server_said()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            status, text = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf-8", "replace")
    return who, name, status, text, jar, app


def stored_file(bench: Bench, doc: dict, kind: str, as_: str) -> str | None:
    """The id of a small test picture (or PDF) stored as a role — what a
    process's file or image input takes — or None when the app would not
    store it."""
    try:
        _who, _name, status, text, _jar, _app = _upload(bench, doc, kind, as_)
        return str(json.loads(text).get("id") or "") or None if status < 400 else None
    except Exception:  # noqa: BLE001 — no file is a refusal the run will show
        return None


def try_upload(bench: Bench, doc: dict, kind: str, as_: str) -> str:
    who, name, status, text, jar, app = _upload(bench, doc, kind, as_)
    out = [f"upload of {name} as {who}: HTTP {status}", f"answer: {_body(text)}"]
    try:
        stored = json.loads(text).get("id")
    except ValueError:
        stored = None
    if stored:
        code, _w, back = _http(app, "GET", f"/api/files/preview?src={stored}", None, jar)
        out.append(f"read back from /api/files/preview?src={stored}: HTTP {code}, {len(back)} byte(s)"
                   + ("" if code == 200 and back else " — the app stored it and cannot show it"))
    said = bench.server_said()
    if said:
        out.append("the server printed:")
        out += [f"  {l}" for l in said]
    return scrub("\n".join(out))


def run(name: str, args: dict, *, bench: Bench, doc: dict) -> str:
    """Carry out one trial. The observation is returned, never raised."""
    args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    as_ = str(args.get("as") or "")
    try:
        if name == "try_workflow":
            return try_workflow(bench, doc, str(args.get("workflow") or ""), args.get("input"), as_)
        if name == "try_request":
            return try_request(bench, doc, str(args.get("method") or "GET"), str(args.get("path") or ""),
                               args.get("body"), as_)
        if name == "try_upload":
            return try_upload(bench, doc, str(args.get("kind") or "image"), as_)
        if name == "open_page":
            sign_in = str(args.get("sign_in") or "").strip().lower() in ("true", "1", "yes")
            return open_page(bench, doc, str(args.get("route") or ""), as_, sign_in=sign_in)
        if name == "try_expectation":
            return try_expectation(bench, doc, str(args.get("statement") or ""))
    except TrialUnavailable as exc:
        return str(exc)
    except ValueError as exc:
        return f"`{name}` could not run with those arguments: {exc}"
    except Exception as exc:  # noqa: BLE001 — a trial that breaks is an observation, not a crash
        logger.exception("[trials] %s failed", name)
        return f"`{name}` failed: {type(exc).__name__}: {str(exc)[:300]}"
    raise KeyError(name)


#: The first line of a statement tried (`expects.build.observation`).
EXPECTATION_HEAD = re.compile(r"^EXP-\d+ (holds|does not hold|could not be tried) — ")


def try_expectation(bench: Bench, doc: dict, ref: str) -> str:
    """One statement, tried on the turn's running copy and put back after."""
    from services.expects.build import observation
    from services.expects.runner import run as run_statements
    from services.expects.statements import expectations
    rows = {str(st.get("id")): st for st in expectations(doc)}
    want = ref.strip().upper()
    if want not in rows:
        listed = ", ".join(list(rows)[:30]) or "none"
        return f"There is no statement {ref!r} to try. The statements are: {listed}."
    report = run_statements(bench.app(), doc, Path(bench.output_dir), only=[want], restore=True)
    got = (report.get("results") or [None])[0]
    if got is None:
        return f"{want} could not be tried — the runner returned nothing"
    said = observation(got)
    server = bench.server_said()
    if server:
        said += "\nthe server printed:\n" + "\n".join(f"  {l}" for l in server[-12:])
    return scrub(said)


def failed(said: str) -> bool:
    """Whether a trial's observation shows something not working: an HTTP
    error, a step that failed, a browser error, a control that does not work,
    or the server printing an error."""
    from services.blueprint.page_review import BROKEN_OUTCOMES
    head = said.split("\n", 1)[0]
    m = EXPECTATION_HEAD.match(head)
    if m:
        return m.group(1) != "holds"
    m = re.search(r"HTTP (\d{3})", head)
    if m and int(m.group(1)) >= 400:
        return True
    if re.search(r"^\s+\d+\. .*\] failed", said, re.M):
        return True
    if "browser error:" in said or "\nthe server printed:" in said:
        return True
    return any(f": {v}" in said for v in BROKEN_OUTCOMES.values())


__all__ = ["TRIALS", "TRIAL_NAMES", "Bench", "TrialUnavailable", "run", "failed",
           "try_workflow", "try_request", "open_page", "try_expectation"]
