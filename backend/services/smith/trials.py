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
import os
import re
import time
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
     "Open a screen in a browser signed in as `as`. Shows where it ended up, "
     "the text on it and errors in the browser — in about half a minute. "
     "`press: \"all\"` also presses every control from a fresh load and says "
     "what each did; that takes minutes on a screen with many buttons, so ask "
     "for it when a control is the question, not to look at a page. A route "
     "with `[id]` opens the first record. `sign_in: true` instead signs in "
     "through the sign-in page's own form, as the administrator, and shows "
     "where that lands — the only way to see where a sign-in takes someone. "
     "On a copy of the data.",
     {"route": "string", "as": "string", "press": "string", "sign_in": "boolean"}),
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
    ("run_checks",
     "Run the application's own checks on the bench and read the result the way "
     "the build does — in one step instead of one try per screen. `what`: "
     "`routes` (every screen asked as every kind of person: answers, sign-in "
     "redirects and refusals as declared), `access` (every scoped record type: "
     "a person sees only their own), `rules` (every rule with a process: the "
     "process refuses the case the rule forbids), `pages` (open and press every "
     "control on the screens named in `routes`, as `as`), `guards` (every fix "
     "made before on this app: the try that failed and then passed, run again), "
     "or `all` (routes, access, rules and guards). `routes` narrows routes/pages to those screens (a route "
     "or a page name); `entities` narrows access to those record types. Lines "
     "marked ✗ are what is not right, with the reason; read them before "
     "deciding what to change, and run the same check again after changing it. "
     "On a copy of the data.",
     {"what": "string", "routes": "array", "entities": "array", "as": "string"}),
)

TRIAL_NAMES: frozenset[str] = frozenset(name for name, _d, _a in TRIALS)
#: How a check's report marks one thing that is not right.
CHECK_RED = "✗"
#: How many screens `pages` presses in one call; each takes minutes.
PAGES_PER_CALL = 4

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
#: What a browser reports when the app's server is not there to answer:
#: `next dev` restarting itself near its heap limit, or gone. None of these
#: says anything about the page that was being opened.
_SERVER_GONE = re.compile(r"ERR_EMPTY_RESPONSE|ERR_INCOMPLETE_CHUNKED_ENCODING|ERR_CONNECTION_REFUSED"
                          r"|ERR_CONNECTION_RESET|ERR_CONNECTION_CLOSED|ERR_CONNECTION_ABORTED")
#: The line Next's dev server prints before it restarts itself.
_RESTARTING = "approaching the used memory threshold"
#: How long a try waits for the app's server to answer again after it restarted.
RESTART_WAIT_S = float(os.environ.get("FORGE_TRIAL_RESTART_WAIT_S") or 120)
SERVER_RESTARTED = ("the app's server restarted while this page was being opened — it was near its "
                    "memory limit and started again; that says nothing about the page")


class TrialUnavailable(RuntimeError):
    """The app could not be started for a trial. The message is the observation."""


#: A bench nobody has tried anything on for this long is stopped. Its dev
#: server holds gigabytes: E-commerce's held 6-8 GB through a 34-minute Smith
#: turn that spent most of it thinking, and with two such turns the host ran
#: out of memory (forge-v3, 2026-10-09). Long enough that a trial and the
#: next one that looks at what it did share one copy.
IDLE_S = float(os.environ.get("FORGE_TRIAL_IDLE_S") or 120)


class Bench:
    """One running copy of the application for a turn: started on the first
    trial, stopped when the turn ends (`close`) or after `IDLE_S` with no trial,
    started again after a change to the data model (`reset`) and on the next
    trial after an idle stop."""

    def __init__(self, output_dir: str, *, factory: Callable[..., Any] | None = None,
                 idle_s: float | None = None):
        import threading
        self.output_dir = output_dir
        self._factory = factory
        self._app: Any = None
        self._lock = threading.RLock()
        self._busy = 0
        self._idle_s = IDLE_S if idle_s is None else idle_s
        self._timer: Any = None
        self._log_at = 0
        self.log = Path(output_dir) / ".forge" / "trials" / "server.log"
        #: How many times the server restarted itself (Next's memory watchdog),
        #: counted as the log is read.
        self.restarts = 0
        #: Names and values the copy's environment gets beyond the platform's
        #: (a check's own signing secrets). Set before the first `app()`.
        self.extra_env: dict[str, str] = {}
        #: The last `try_workflow`'s tables before and after it ran.
        self.last_written: tuple[dict[str, Any], dict[str, Any]] | None = None
        #: ONE SIGNED-OUT VISITOR FOR THE TURN. A shopper's browser keeps the
        #: `forge-guest` cookie between adding to the bag and opening it; each
        #: trial used to arrive as a stranger, so TCommerce's guest bag read
        #: empty on the bench and Smith blamed a cart page that worked
        #: (2026-10-06). Every signed-out trial carries this token.
        import uuid as _uuid
        self.guest = str(_uuid.uuid4())

    def begin(self) -> None:
        """A trial is starting: the bench is not idle."""
        with self._lock:
            self._busy += 1
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def end(self) -> None:
        """A trial has finished: stop the bench if no other starts soon."""
        import threading
        with self._lock:
            self._busy = max(0, self._busy - 1)
            if self._busy or self._app is None or self._idle_s <= 0:
                return
            self._timer = threading.Timer(self._idle_s, self._idle_stop)
            self._timer.daemon = True
            self._timer.start()

    def _idle_stop(self) -> None:
        with self._lock:
            self._timer = None
            if not self._busy and self._app is not None:
                logger.info("[trials] %s: no trial for %.0fs; stopping its dev server",
                            Path(self.output_dir).name, self._idle_s)
                self.close()

    def app(self) -> Any:
        if self._app is None:
            from services.blueprint.page_review import ReviewUnavailable, RunningApp
            factory = self._factory or RunningApp
            self.log.parent.mkdir(parents=True, exist_ok=True)
            self.log.write_bytes(b"")
            self._log_at = 0
            import uuid
            app = factory(Path(self.output_dir) / "app", log=self.log,
                          **({"extra_env": self.extra_env} if self.extra_env else {}),
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
        text = fresh.decode("utf-8", "replace")
        self.restarts += text.count(_RESTARTING)
        lines = [l.strip() for l in text.splitlines()]
        return [l[:300] for l in lines if l and _SERVER_ERROR.search(l)][:15]

    def reset(self) -> None:
        self.close()

    def close(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
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
    if not want:
        return admin, True
    if want.lower() in SIGNED_OUT:
        return "", False
    # A ROLE THE APP NAMES WINS OVER THE ALIAS. "Admin" meant the computed
    # back-office role even when the app had a role called Admin, so on a
    # marketplace whose back office ranked as Vendor every trial "as Admin"
    # ran as a vendor: 200 on /vendor, refused on /admin (rwt6ef5p, 2026-10-11).
    for r in doc.get("roles") or []:
        if not isinstance(r, dict):
            continue
        if want.lower() in (str(r.get("id") or "").lower(), str(r.get("name") or "").lower()):
            name = str(r.get("name") or r.get("id"))
            return name, name == admin
    if want.lower() in ("admin", "administrator", admin.lower()):
        return admin, True
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
        # THE ORGANISATION THEY ACT IN rides in the minted session: the app's
        # own sign-in is not run for it, and every scoped read needs it.
        # AND THE LOGIN'S OWN EMAIL: a workflow finds the person's membership
        # by it (DITANS: `OrganisationMember where email`), and the made-up
        # `<role>@example.com` matched no member of a role with `&` in it.
        org, email = "", f"{role.lower().replace(' ', '.')}@example.com"
        if found:
            from services.blueprint.page_review import _query
            rows = _query(app, "select coalesce(active_org_id::text, ''), coalesce(email, '') from users "
                               f"where id = '{str(found[0]).replace(chr(39), chr(39)*2)}'")
            if rows and rows[0]:
                org = rows[0][0]
                email = (rows[0][1] if len(rows[0]) > 1 and rows[0][1] else email)
        who = (Session(sub=found[0], name=found[1], email=email,
                       role=role, active_org_id=org) if found else
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
    # ONE RETRY WHEN THE SERVER HANGS UP. A dev server compiling the route it
    # was just asked for can close the connection without a reply; read as
    # the trial's crash it took every process down as "untried" (ECom L5,
    # 2026-10-11). A second ask a moment later is answered.
    import http.client
    import time as _time
    for attempt in (1, 2):
        try:
            with opener.open(req, timeout=240) as r:
                return r.status, "", r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("location") or "", e.read().decode("utf-8", "replace")
        except (http.client.RemoteDisconnected, ConnectionResetError, urllib.error.URLError) as e:
            if attempt == 2 or isinstance(e, urllib.error.URLError) and not isinstance(
                    getattr(e, "reason", None), (http.client.RemoteDisconnected, ConnectionResetError)):
                raise
            _time.sleep(3)
    raise RuntimeError("unreachable")


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
        # Required unless it says it is not — as the app reads it
        # (`projection` → `requiredInputs`). Read the other way, Close Job's
        # `job` was left out and every DITANS job process was refused for
        # want of its job (wzml1sa6, 2026-10-31).
        if not spec.get("required", True) and name not in payload:
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


def _server_gone(shot: dict, restarted: bool) -> bool:
    """The open hit no server: no status and only connection errors, or the
    server said it was restarting while the page was opened."""
    if restarted:
        return True
    errs = [str(e) for e in shot.get("errors") or []]
    return shot.get("status") is None and bool(errs) and all(_SERVER_GONE.search(e) for e in errs)


def _server_back(app: Any, timeout: float | None = None) -> bool:
    """Wait for the app's server to answer again; False when it does not."""
    deadline = time.monotonic() + (RESTART_WAIT_S if timeout is None else timeout)
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{app.base}/api/auth/csrf", timeout=10)
            return True
        except Exception:  # noqa: BLE001 — not back yet
            time.sleep(2)
    return False


def open_page(bench: Bench, doc: dict, route: str, as_: str, sign_in: bool = False,
              press: bool = False) -> str:
    """The page as a browser sees it. `press` presses every control from a
    fresh load as well — what the after-change check does; for a look at a
    page it cost Mark 8 four minutes an open (6 opens, 24 of 32 minutes,
    2026-10-16), so it is asked for, not assumed."""
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
    shots_dir = Path(bench.output_dir) / ".forge" / "trials" / "shots"
    printed: list[str] = []
    notes: list[str] = []
    try:
        shot = run_shots(app, [entry], shots_dir, probe=press, states=False)[0]
        # A RESTARTING SERVER IS NOT A BROKEN PAGE. `next dev` restarts itself
        # near its heap limit; the request in flight dies with a connection
        # error and the page "says it is loading". Three pages were rewritten
        # for that on 2026-10-15 (Personal Finance) and none of them was at
        # fault. Wait for the server, open the page once more, and say so.
        before = bench.restarts
        printed += bench.server_said()
        if _server_gone(shot, bench.restarts > before):
            if not _server_back(app):
                return scrub(f"{route} as {who}: {SERVER_RESTARTED}; it had not answered again after "
                             f"{int(RESTART_WAIT_S)}s. Try it again in a moment — do not change the page for this.")
            notes.append(SERVER_RESTARTED + "; opened again once it was back")
            shot = run_shots(app, [entry], shots_dir, probe=press, states=False)[0]
            before = bench.restarts
            printed += bench.server_said()
            if _server_gone(shot, bench.restarts > before):
                return scrub(f"{route} as {who}: {SERVER_RESTARTED}, twice in a row. Try it again in a "
                             f"moment — do not change the page for this.")
    except ReviewUnavailable as exc:
        return f"The page could not be opened in a browser: {exc}"
    if shot.get("skipped"):
        return f"{route} as {who}: not opened — {shot['skipped']}."
    out = [f"{shot.get('url') or route} as {who}: HTTP {shot.get('status')}"
           + (f", ended up at {shot['landed']}" if shot.get("landed") and shot["landed"] != shot.get("url") else "")]
    out += [f"note: {n}" for n in notes]
    if shot.get("state"):
        out.append(f"the page says it is: {shot['state']}")
    out += [f"browser error: {e}" for e in shot.get("errors") or []]
    controls = shot.get("controls") or []
    if not press:
        out.append("controls not pressed (say `press: \"all\"` to press each from a fresh load)")
    if controls:
        out.append("controls, each pressed from a fresh load:")
        for c in controls:
            detail = str(c.get("detail") or "")
            if _SERVER_GONE.search(detail):
                # The press landed while the server was restarting: not pressed, not broken.
                out.append(f"  {c.get('kind')} \"{c.get('label')}\": could not be pressed — the app's server "
                           "was restarting (not the control's fault); press it again later")
                continue
            verdict = BROKEN_OUTCOMES.get(str(c.get("outcome")), str(c.get("outcome")))
            out.append(f"  {c.get('kind')} \"{c.get('label')}\": {verdict}"
                       + (f" ({detail})" if detail else ""))
    text = " ".join(str(shot.get("text") or "").split())
    out.append(f"text on the page: {text[:BODY_SHOWN]}" if text else "the page shows no text")
    said = printed + bench.server_said()
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


# ── the application's own checks, as one try ────────────────────────────────

def _page_ids(doc: dict, named: list) -> set[str] | None:
    """Page ids for the routes or names the call gave; None means every page."""
    wanted = [str(n).strip().lower() for n in (named or []) if str(n).strip()]
    if not wanted:
        return None
    out: set[str] = set()
    for p in (doc.get("pages") or []):
        if not isinstance(p, dict):
            continue
        keys = {str(p.get(k) or "").strip().lower() for k in ("id", "route", "name", "path")}
        if any(w in keys for w in wanted):
            out.add(str(p.get("id")))
    return out


def _entity_ids(doc: dict, named: list) -> set[str] | None:
    wanted = [str(n).strip().lower() for n in (named or []) if str(n).strip()]
    if not wanted:
        return None
    out: set[str] = set()
    for e in (doc.get("data") or {}).get("entities") or []:
        if isinstance(e, dict) and any(
                w in {str(e.get(k) or "").strip().lower() for k in ("id", "name", "table")} for w in wanted):
            out.add(str(e.get("id")))
    return out


def _rules_client() -> Any:
    """What composes a rule's breaking input: the build's own small model."""
    from services.blueprint.executors import DEFAULT_MODEL, AnthropicModel
    return AnthropicModel(model=DEFAULT_MODEL, effort="low")


def _check_lines(kind: str, result: dict, *, holds: str) -> list[str]:
    total = int(result.get("total") or 0)
    green = result.get("green") or []
    n_green = len(green) if isinstance(green, list) else int(green or 0)
    red = list(result.get("red") or [])
    untried = list(result.get("untried") or [])
    skipped = list(result.get("skipped") or [])
    if total == 0 and not skipped:
        return [f"checks · {kind}: nothing to check"]
    head = f"checks · {kind}: {n_green} of {total} {holds}"
    if red:
        head += f", {len(red)} not right"
    if untried:
        head += f", {len(untried)} could not be tried"
    if skipped:
        head += f", {len(skipped)} outside the count"
    lines = [head]
    lines += [f"  {CHECK_RED} {i.get('label')}: {i.get('why')}" for i in red[:25]]
    if len(red) > 25:
        lines.append(f"  … and {len(red) - 25} more not right")
    lines += [f"  ? {i.get('label')}: {i.get('why')}" for i in untried[:8]]
    if len(untried) > 8:
        lines.append(f"  … and {len(untried) - 8} more untried")
    lines += [f"  – {i.get('label')}: {i.get('why')}" for i in skipped[:4]]
    return lines


def run_checks(bench: Bench, doc: dict, what: str, routes: list, entities: list, as_: str) -> str:
    """The build's own checks, run on the bench, reported as one observation.

    A fault a check can see used to be found by Smith one `open_page` at a
    time, four minutes each (Mark 8, 2026-10-17). The build already knows how
    to ask every screen as every person, every scoped record type and every
    rule; this is that knowledge offered as one try.
    """
    from services.blueprint import access_check, route_check, rule_trials
    what = (what or "all").strip().lower()
    kinds = {"all": ("routes", "access", "rules", "guards"), "routes": ("routes",), "access": ("access",),
             "rules": ("rules",), "pages": ("pages",), "guards": ("guards",)}.get(what)
    if kinds is None:
        raise ValueError(f"`what` is one of routes, access, rules, pages, all — not {what!r}")
    if "pages" in kinds and not routes:
        raise ValueError("`pages` presses the screens named in `routes`; name at least one")
    lines: list[str] = []
    page_ids = _page_ids(doc, routes)
    if routes and page_ids == set():
        return f"No screen is called {', '.join(str(r) for r in routes)} — name a route or a page name."
    for kind in kinds:
        try:
            if kind == "routes":
                lines += _check_lines("routes", route_check.check_routes(bench.app(), doc, only=page_ids),
                                      holds="screens answer as declared")
            elif kind == "access":
                lines += _check_lines("access", access_check.check_access(bench.app(), doc,
                                                                          only=_entity_ids(doc, entities)),
                                      holds="record scopes hold")
            elif kind == "rules":
                lines += _check_lines("rules", rule_trials.refuse_rules(doc, bench, _rules_client()),
                                      holds="rules refuse their refused case")
            elif kind == "guards":
                from services.smith import guards as _guards
                lines += _guards.run(bench, doc, only_routes=[str(r) for r in routes] or None)["lines"]
            elif kind == "pages":
                named = [str(r) for r in routes][:PAGES_PER_CALL]
                for route in named:
                    said = open_page(bench, doc, route, as_, press=True)
                    bad = failed(said)
                    lines.append(f"checks · page {route} as {as_ or 'the administrator'}: "
                                 f"{'not right' if bad else 'nothing wrong seen'}")
                    body = said.splitlines()[:40]
                    if bad and body:
                        body[0] = f"{CHECK_RED} {body[0]}"
                    lines += ["  " + l for l in body]
                if len(routes) > PAGES_PER_CALL:
                    lines.append(f"  ({len(routes) - PAGES_PER_CALL} more screens were not pressed this call; "
                                 f"name them in another)")
        except TrialUnavailable as exc:
            lines.append(f"checks · {kind}: could not run — {exc}")
            break
        except Exception as exc:  # noqa: BLE001 — one check breaking is a line, not the end
            logger.exception("[trials] run_checks %s failed", kind)
            lines.append(f"checks · {kind}: the check itself failed — {type(exc).__name__}: {str(exc)[:200]}")
    server = bench.server_said() if bench.running else []
    if server:
        lines.append("the server printed:")
        lines += [f"  {l}" for l in server[:8]]
    return scrub("\n".join(lines))


def run(name: str, args: dict, *, bench: Bench, doc: dict) -> str:
    """Carry out one trial. The observation is returned, never raised."""
    args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    as_ = str(args.get("as") or "")
    # The idle stop's bookkeeping, where the bench keeps it: a stand-in bench
    # (a test's, a caller's own) has none and needs none.
    begin, end = getattr(bench, "begin", None), getattr(bench, "end", None)
    if callable(begin):
        begin()
    try:
        return _run(name, args, as_, bench=bench, doc=doc)
    finally:
        if callable(end):
            end()


def _run(name: str, args: dict, as_: str, *, bench: Bench, doc: dict) -> str:
    try:
        if name == "try_workflow":
            return try_workflow(bench, doc, str(args.get("workflow") or ""), args.get("input"), as_)
        if name == "try_request":
            return try_request(bench, doc, str(args.get("method") or "GET"), str(args.get("path") or ""),
                               args.get("body"), as_)
        if name == "try_upload":
            return try_upload(bench, doc, str(args.get("kind") or "image"), as_)
        if name == "run_checks":
            routes = args.get("routes") or []
            routes = routes if isinstance(routes, list) else [routes]
            entities = args.get("entities") or []
            entities = entities if isinstance(entities, list) else [entities]
            return run_checks(bench, doc, str(args.get("what") or "all"), routes, entities, as_)
        if name == "open_page":
            sign_in = str(args.get("sign_in") or "").strip().lower() in ("true", "1", "yes")
            press = str(args.get("press") or "").strip().lower() in ("all", "true", "1", "yes", "every")
            return open_page(bench, doc, str(args.get("route") or ""), as_, sign_in=sign_in, press=press)
    except TrialUnavailable as exc:
        return str(exc)
    except ValueError as exc:
        return f"`{name}` could not run with those arguments: {exc}"
    except Exception as exc:  # noqa: BLE001 — a trial that breaks is an observation, not a crash
        logger.exception("[trials] %s failed", name)
        return f"`{name}` failed: {type(exc).__name__}: {str(exc)[:300]}"
    raise KeyError(name)


def failed(said: str) -> bool:
    """Whether a trial's observation shows something not working: an HTTP
    error, a step that failed, a browser error, a control that does not work,
    or the server printing an error."""
    from services.blueprint.page_review import BROKEN_OUTCOMES
    head = said.split("\n", 1)[0]
    m = re.search(r"HTTP (\d{3})", head)
    if m and int(m.group(1)) >= 400:
        return True
    if re.search(r"^\s+\d+\. .*\] failed", said, re.M):
        return True
    if "browser error:" in said or "\nthe server printed:" in said:
        return True
    # A CHECK'S REPORT MARKS EACH THING NOT RIGHT. One ✗ line is a fault seen.
    if re.search(rf"^\s*{re.escape(CHECK_RED)} ", said, re.M):
        return True
    return any(f": {v}" in said for v in BROKEN_OUTCOMES.values())


__all__ = ["TRIALS", "TRIAL_NAMES", "Bench", "TrialUnavailable", "run", "failed",
           "try_workflow", "try_request", "open_page", "run_checks", "CHECK_RED"]
