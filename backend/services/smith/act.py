"""Smith acts outside the application: an API call, an MCP tool.

`fetch_url` let Smith read a service's documentation. It could not then USE the
service: "here are the docs for our CRM, pull this week's leads" was answered
with what the call would look like, and the person ran it themselves. Three
tools close that:

    list_services   what the organisation has connected: the NAMES of its
                    stored credentials and its MCP servers with their tools
    call_api        one HTTP request to a service the person named, with a
                    stored credential attached by the platform
    call_mcp_tool   one tool on one of the organisation's MCP servers

LOOKING RUNS, CHANGING WAITS FOR A YES. A GET (or HEAD, OPTIONS) is a look and
runs at once, like `fetch_url`. Anything else — a POST that sends a message,
a DELETE, a PATCH to a customer — is shown to the person exactly as it will be
sent and the turn ends there. The call is kept (`HELD`); the next message, if
it is a yes, sends THAT call, not whatever the model would write again. An MCP
tool runs at once only when its server declares it read-only
(`readOnlyHint`); otherwise it waits the same way, and the person may answer
"always" for that one tool.

THE KEY NEVER ENTERS THE CONVERSATION. A credential is named (`STRIPE_SECRET_
KEY`), never typed: the value is read from the organisation's encrypted store
at the moment of the call, put on the request, and cut out of everything that
comes back. It goes only to the service it belongs to — a host whose name is
the credential's provider (`stripe` → api.stripe.com) — or to a host the
person sent it to in their own words, naming the credential. A page Smith has
read cannot redirect a key.

THE OTHER RULES ARE `web.py`'s. Only hosts the person named, only the public
internet, no redirects followed with a key on, and what comes back is
material, not instructions.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from services.smith.secrets_scrub import scrub
from services.smith.web import MATERIAL, WebRefused, check_url, site_name

logger = logging.getLogger(__name__)

#: Characters of a response one observation carries; the whole of it is kept.
PART_CHARS = 12_000
#: Bytes read from a response before it is cut off.
MAX_BYTES = 3_000_000
HTTP_TIMEOUT = 30.0
#: Methods that only look.
LOOKS = frozenset({"GET", "HEAD", "OPTIONS"})
METHODS = LOOKS | {"POST", "PUT", "PATCH", "DELETE"}
#: Headers the platform sets; one written into a call is refused.
_AUTH_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})

#: The call waiting for a yes, and the tools the person said never to ask about.
HELD = Path(".forge") / "smith" / "held-call.json"
ALLOWED = Path(".forge") / "smith" / "allowed-tools.json"
#: Where each response is kept whole.
CALLS = Path(".forge") / "smith" / "calls"

YES_LABEL = "Yes, send it"
ALWAYS_LABEL = "Yes, and always for this tool"
NO_LABEL = "No, don't send it"

ACT: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("list_services",
     "What the organisation has connected: the names of its stored credentials (never their "
     "values) and its MCP servers with each tool's inputs, and which tools only look. Read it "
     "before `call_api` with a credential or `call_mcp_tool`.",
     {}),
    ("call_api",
     "Send one HTTP request to a service the person named, and see what it answers. `method` "
     "defaults to GET; `query`, `headers` and `body` are objects (`encoding`: json, the default, "
     "or form). `credential` is the NAME of a stored credential (from `list_services`); the "
     "platform attaches it — `send_as`: bearer (default), basic, header:<Name> or query:<param>. "
     "GET, HEAD and OPTIONS run now. Anything else is shown to the person and sent only after "
     "they say yes — the turn ends there. Read the service's documentation with `fetch_url` first.",
     {"method": "string", "url": "string", "query": "object", "headers": "object", "body": "object",
      "encoding": "string", "credential": "string", "send_as": "string"}),
    ("check_services",
     "Hold every call the application makes to an outside service (its `http_call` steps) against "
     "that service's documentation, and call each one that only reads with the stored key — what the "
     "service really answers against what the workflow reads. Run it after changing such a step.",
     {}),
    ("app_mcp",
     "This application as an MCP server, so an assistant such as Claude can use it as a person: "
     "`action` status (default) says whether it is on and which tools it offers each role; on or off "
     "turns it on or off. A person connects on the app's /connect-ai page with their own token; "
     "the live app hears a change with its next publish.",
     {"action": "string"}),
    ("call_mcp_tool",
     "Run one tool on one of the organisation's MCP servers (`list_services` names them) with "
     "`arguments` as an object. A tool its server marks read-only runs now; any other is shown "
     "to the person and runs after they say yes.",
     {"server": "string", "tool": "string", "arguments": "object"}),
)
ACT_NAMES: frozenset[str] = frozenset(name for name, _d, _a in ACT)


@dataclass
class Step:
    """What a call did: an observation, or a question that ends the turn."""
    said: str
    ask: str = ""
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Credential:
    provider: str
    key: str
    value: str = field(repr=False)


# --------------------------------------------------------------------------- #
# The organisation's store — every read goes through these two, so tests and
# turns without a database row see "nothing connected", never an exception.
# --------------------------------------------------------------------------- #

def _credentials(output_dir: str) -> list[Credential]:
    """The organisation's stored credentials, decrypted. Platform-only keys —
    the ones the platform itself spends — are never offered."""
    from services.figma.integrations import _org_for_output_dir, _run, _session_on_this_loop

    async def fetch() -> list[Credential]:
        from sqlalchemy import select

        from models.platform_integration import PlatformIntegration
        from services.node_config_specs import platform_only_keys
        from services.platform_integrations_crypto import decrypt

        org = await _org_for_output_dir(output_dir)
        if org is None:
            return []
        async with _session_on_this_loop() as db:
            rows = (await db.execute(select(PlatformIntegration).where(
                PlatformIntegration.org_id == org))).scalars().all()
        hidden = platform_only_keys()
        out: list[Credential] = []
        for row in rows:
            if not row.value_ct or not row.value_iv or row.key in hidden:
                continue
            try:
                out.append(Credential(row.provider, row.key, decrypt(row.provider, row.value_ct, row.value_iv)))
            except Exception:  # noqa: BLE001 — one bad row reads as "not set"
                logger.warning("[smith-act] could not decrypt %s", row.key)
        return out

    try:
        return _run(fetch())
    except Exception as exc:  # noqa: BLE001
        logger.info("[smith-act] credential store unavailable: %s", type(exc).__name__)
        return []


def _servers(output_dir: str) -> list[dict]:
    """The organisation's enabled MCP servers, each with its tools:
    `{name, tools: [{name, description, inputs, required, read_only}] | None, error}`."""
    from services.figma.integrations import _org_for_output_dir, _run, _session_on_this_loop

    async def fetch() -> list[dict]:
        from sqlalchemy import select

        from models.platform_mcp_server import PlatformMcpServer
        from services.mcp_client import list_tools

        org = await _org_for_output_dir(output_dir)
        if org is None:
            return []
        async with _session_on_this_loop() as db:
            rows = (await db.execute(select(PlatformMcpServer).where(
                PlatformMcpServer.org_id == org, PlatformMcpServer.enabled.is_(True)))).scalars().all()
        out: list[dict] = []
        for row in rows:
            entry: dict[str, Any] = {"name": row.name, "tools": None}
            try:
                entry["tools"] = [{
                    "name": t.name, "description": " ".join(str(t.description or "").split())[:240],
                    "inputs": sorted((t.input_schema.get("properties") or {}).keys())[:30],
                    "required": [str(r) for r in t.input_schema.get("required") or []],
                    "read_only": bool(getattr(t, "read_only", False)),
                } for t in await list_tools(row)]
            except Exception as exc:  # noqa: BLE001 — said, not fatal
                entry["error"] = str(exc)[:200]
            out.append(entry)
        return out

    try:
        return _run(fetch())
    except Exception as exc:  # noqa: BLE001
        logger.info("[smith-act] MCP servers unavailable: %s", type(exc).__name__)
        return []


def _mcp_call(output_dir: str, server: str, tool: str, arguments: dict) -> dict:
    """`{content: [...], isError}` from the named server, or raises."""
    from services.figma.integrations import _org_for_output_dir, _run, _session_on_this_loop

    async def call() -> dict:
        from sqlalchemy import select

        from models.platform_mcp_server import PlatformMcpServer
        from services.mcp_client import call_tool

        org = await _org_for_output_dir(output_dir)
        async with _session_on_this_loop() as db:
            rows = (await db.execute(select(PlatformMcpServer).where(
                PlatformMcpServer.org_id == org, PlatformMcpServer.enabled.is_(True)))).scalars().all()
        row = next((r for r in rows if r.name.strip().lower() == server.strip().lower()), None)
        if row is None:
            raise WebRefused(f"The organisation has no MCP server called {server!r}.")
        return await call_tool(row, tool, arguments)

    return _run(call())


def _send(method: str, url: str, headers: dict[str, str], content: bytes | None) -> tuple[int, dict[str, str], bytes]:
    """One request, no redirects followed: `(status, headers, body)`."""
    import httpx

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
        with client.stream(method, url, headers=headers, content=content) as resp:
            body = bytearray()
            for chunk in resp.iter_bytes():
                body.extend(chunk)
                if len(body) >= MAX_BYTES:
                    break
            return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, bytes(body)


# --------------------------------------------------------------------------- #
# Whose key goes where
# --------------------------------------------------------------------------- #

def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def belongs_to(cred: Credential, host: str) -> bool:
    """The credential is this service's own: the host's name and the
    credential's provider (or its key's first word) are the same name —
    `stripe` / api.stripe.com, `app:openweather` / api.openweathermap.org."""
    name = _squash(site_name(host))
    if len(name) < 3:
        return False
    marks = {_squash(cred.provider.removeprefix("app:")), _squash(cred.key.split("_")[0])}
    return any(len(m) >= 3 and (m in name or name in m) for m in marks)


def sent_by_person(cred: Credential, host: str, said: Iterable[str]) -> bool:
    """The person named both the credential and the host in one message."""
    for text in said:
        low = str(text or "").lower()
        if cred.key.lower() in low and (host in low or host.removeprefix("www.") in low
                                        or _squash(site_name(host)) in _squash(low)):
            return True
    return False


def _attach(cred: Credential, send_as: str, headers: dict[str, str], url: str) -> str:
    """Put the credential on the request; returns the URL (a query key changes it)."""
    how = (send_as or "bearer").strip()
    low = how.lower()
    if low == "bearer":
        headers["Authorization"] = f"Bearer {cred.value}"
    elif low == "basic":
        import base64
        headers["Authorization"] = "Basic " + base64.b64encode(f"{cred.value}:".encode()).decode()
    elif low.startswith("header:") and how[7:].strip():
        headers[how[7:].strip()] = cred.value
    elif low.startswith("query:") and how[6:].strip():
        url = _with_query(url, {how[6:].strip(): cred.value})
    else:
        raise WebRefused(f"`send_as` is bearer, basic, header:<Name> or query:<param>, not {send_as!r}.")
    return url


def _with_query(url: str, extra: dict) -> str:
    parts = urlparse(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    for k, v in extra.items():
        if isinstance(v, (list, tuple)):
            pairs += [(str(k), str(x)) for x in v]
        else:
            pairs.append((str(k), v if isinstance(v, str) else json.dumps(v) if isinstance(v, (dict, bool)) else str(v)))
    return urlunparse(parts._replace(query=urlencode(pairs)))


def _hide(text: str, secrets: Iterable[str]) -> str:
    for s in secrets:
        if s and len(s) >= 4:
            text = text.replace(s, "[credential]")
    return scrub(text)


# --------------------------------------------------------------------------- #
# The call that waits for a yes
# --------------------------------------------------------------------------- #

def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _write(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), "utf-8")
    except Exception as exc:  # noqa: BLE001 — a hold that cannot be written is asked again
        logger.warning("[smith-act] could not write %s: %s", path, exc)


def held(output_dir: str) -> dict | None:
    """The call shown last turn and waiting for its answer — read, not taken."""
    raw = _read(Path(output_dir) / HELD)
    return raw if isinstance(raw, dict) and raw.get("tool") in ACT_NAMES else None


def clear_held(output_dir: str) -> None:
    try:
        (Path(output_dir) / HELD).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def _hold(output_dir: str, tool: str, args: dict, shown: str) -> None:
    _write(Path(output_dir) / HELD, {"tool": tool, "args": args, "shown": shown, "at": time.time()})


def allowed(output_dir: str, server: str, tool: str) -> bool:
    raw = _read(Path(output_dir) / ALLOWED)
    return isinstance(raw, dict) and f"{server.lower()}/{tool}" in (raw.get("mcp") or [])


def _allow(output_dir: str, server: str, tool: str) -> None:
    raw = _read(Path(output_dir) / ALLOWED)
    raw = raw if isinstance(raw, dict) else {}
    names = sorted(set(raw.get("mcp") or []) | {f"{server.lower()}/{tool}"})
    _write(Path(output_dir) / ALLOWED, {**raw, "mcp": names})


def answer_held(output_dir: str, message: str, *, said: Iterable[str]) -> tuple[str, dict, str] | None:
    """The person's reply to a held call: `(tool, args, observation)`, or None
    when nothing was held. A yes sends exactly what was shown; anything else
    drops it, and the observation says so."""
    from services.smith.confirm import is_yes

    waiting = held(output_dir)
    if waiting is None:
        return None
    clear_held(output_dir)
    tool, args = str(waiting["tool"]), dict(waiting.get("args") or {})
    typed = " ".join(str(message or "").split())
    always = typed == ALWAYS_LABEL
    if not (always or typed == YES_LABEL or is_yes(typed)):
        return tool, args, (
            "Last turn this call was shown and held for a yes:\n" + str(waiting.get("shown") or "")
            + "\nTheir reply is not a yes, so it was NOT sent. If they changed what it should do, "
              "make the call again with the change — it will be shown to them again.")
    if always and tool == "call_mcp_tool":
        _allow(output_dir, str(args.get("server") or ""), str(args.get("tool") or ""))
    step = run(tool, args, said=said, output_dir=output_dir, consented=True)
    return tool, args, ("They agreed, and the call shown last turn has been sent — do not send it "
                        "again. Tell them what it did.\n" + step.said)


# --------------------------------------------------------------------------- #
# The tools
# --------------------------------------------------------------------------- #

def list_services(output_dir: str) -> str:
    creds = _credentials(output_dir)
    servers = _servers(output_dir)
    out: list[str] = []
    if creds:
        out.append("Stored credentials (pass the NAME as `credential`; the value is never shown):")
        by: dict[str, list[str]] = {}
        for c in creds:
            by.setdefault(c.provider.removeprefix("app:"), []).append(c.key)
        out += [f"- {p}: {', '.join(sorted(keys))}" for p, keys in sorted(by.items())]
    else:
        out.append("No credentials are stored for this organisation. A service that needs a key is "
                   "connected under Settings → Integrations; ask the person to add it there — never "
                   "to type it into the chat.")
    if servers:
        out.append("")
        out.append("MCP servers (`call_mcp_tool` server + tool):")
        for s in servers:
            if s.get("tools") is None:
                out.append(f"- {s['name']}: did not answer ({s.get('error') or 'no tools listed'})")
                continue
            out.append(f"- {s['name']}:")
            for t in s["tools"][:40]:
                needs = f" — needs {', '.join(t['required'])}" if t.get("required") else ""
                mark = " [only looks]" if t.get("read_only") else ""
                out.append(f"    `{t['name']}`{mark}({', '.join(t.get('inputs') or [])}){needs}: {t.get('description') or ''}")
    else:
        out.append("")
        out.append("The organisation has no MCP server connected (Settings → Integrations → MCP servers).")
    return "\n".join(out)


def _request_of(args: dict, said: list[str], output_dir: str) -> tuple[str, str, dict[str, str], bytes | None, Credential | None, str]:
    """Everything a call will send, checked: `(method, url, headers, body,
    credential, how it is shown)`. The shown form never carries the value."""
    method = str(args.get("method") or "GET").strip().upper()
    if method not in METHODS:
        raise WebRefused(f"`method` is one of {', '.join(sorted(METHODS))}, not {method!r}.")
    url = check_url(str(args.get("url") or ""), said)
    query = args.get("query")
    if isinstance(query, dict) and query:
        url = _with_query(url, query)
    headers: dict[str, str] = {"Accept": "application/json, text/*;q=0.9, */*;q=0.5",
                               "User-Agent": "TentoroForge-Smith/1.0"}
    for k, v in (args.get("headers") or {}).items() if isinstance(args.get("headers"), dict) else ():
        if str(k).strip().lower() in _AUTH_HEADERS:
            raise WebRefused(f"`{k}` is set by the platform from a stored credential — name it in "
                             "`credential` instead of writing the header.")
        headers[str(k)] = str(v)
    body, content = args.get("body"), None
    encoding = str(args.get("encoding") or "json").strip().lower()
    if body not in (None, "", {}, []):
        if method in ("GET", "HEAD"):
            raise WebRefused(f"A {method} carries no body; put the values in `query`.")
        if isinstance(body, str):
            content = body.encode()
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
        elif encoding == "form":
            if not isinstance(body, dict):
                raise WebRefused("A form body is an object of fields.")
            content = _with_query("http://x/", body).split("?", 1)[-1].encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            content = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    host = (urlparse(url).hostname or "").lower()
    cred = None
    name = str(args.get("credential") or "").strip()
    if name:
        cred = next((c for c in _credentials(output_dir) if c.key.lower() == name.lower()), None)
        if cred is None:
            raise WebRefused(f"No credential called {name} is stored for this organisation. "
                             "`list_services` names the ones that are; a missing one is added under "
                             "Settings → Integrations by the person — never typed into the chat.")
        if not (belongs_to(cred, host) or sent_by_person(cred, host, said)):
            raise WebRefused(f"{cred.key} belongs to {cred.provider.removeprefix('app:')} and is sent only "
                             f"to its own addresses, not {host}. If the person wants it sent there, "
                             "they say so, naming both.")
        url = _attach(cred, str(args.get("send_as") or "bearer"), headers, url)
    shown_url = _hide(url, [cred.value] if cred else [])
    shown = [f"{method} {shown_url}"]
    if cred:
        shown.append(f"with {cred.key} attached by the platform ({str(args.get('send_as') or 'bearer')})")
    if content:
        text = content.decode("utf-8", "replace")
        try:
            text = json.dumps(json.loads(text), indent=2)
        except ValueError:
            pass
        shown.append("body:\n" + text[:3000])
    return method, url, headers, content, cred, "\n".join(shown)


def _keep(output_dir: str, record: dict) -> str:
    """The whole exchange, on disk, for `read_file`."""
    if not output_dir:
        return ""
    rel = CALLS / f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.json"
    _write(Path(output_dir) / rel, record)
    return str(rel)


def _readable(body: bytes, ctype: str) -> str:
    text = body.decode("utf-8", "replace")
    if "json" in ctype or text.lstrip()[:1] in ("{", "["):
        try:
            return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except ValueError:
            pass
    if "html" in ctype:
        from services.smith.web import html_text
        _title, words, _links = html_text(text, "")
        return words
    return text


def call_api(args: dict, *, said: Iterable[str], output_dir: str = "", consented: bool = False,
             unattended: bool = False) -> Step:
    said = list(said)
    method, url, headers, content, cred, shown = _request_of(args, said, output_dir)
    if method not in LOOKS and not consented:
        if unattended:
            return Step(said=("This call would change something outside the application, and nobody "
                              "is here to agree to it, so it was not sent:\n" + shown))
        _hold(output_dir, "call_api", dict(args), shown)
        return Step(said=shown, options=[YES_LABEL, NO_LABEL], ask=(
            "This would change something outside the application, so I have not sent it. "
            "Here is exactly what I would send:\n\n" + shown + "\n\nShall I send it?"))
    secrets = [cred.value] if cred else []
    try:
        status, rheaders, body = _send(method, url, headers, content)
    except Exception as exc:  # noqa: BLE001 — the observation says what happened
        return Step(said=_hide(f"{shown}\n{urlparse(url).hostname} could not be reached "
                               f"({exc.__class__.__name__}: {str(exc)[:160]}).", secrets))
    ctype = rheaders.get("content-type", "").split(";")[0].strip().lower()
    text = _hide(_readable(body, ctype), secrets)
    kept = _keep(output_dir, {"request": _hide(shown, secrets), "status": status,
                              "content_type": ctype, "response": text})
    head = f"{shown.splitlines()[0]} — HTTP {status}, {ctype or 'no content type'}, {len(body)} bytes"
    if 300 <= status < 400 and rheaders.get("location"):
        head += f"; it redirects to {_hide(rheaders['location'], secrets)}, which was not followed"
    out = [head, MATERIAL, "--- response ---", text[:PART_CHARS] or "(empty)"]
    if len(text) > PART_CHARS:
        out.append(f"--- cut at {PART_CHARS} of {len(text)} characters; the whole response is in "
                   f"`{kept}` (read_file) ---")
    elif kept:
        out.append(f"--- kept in `{kept}` ---")
    if status in (401, 403):
        out.append("The service refused the credentials. If none was attached, `list_services` shows "
                   "what is stored; a wrong or missing key is fixed by the person under Settings → "
                   "Integrations.")
    return Step(said="\n".join(out))


def _tool_of(output_dir: str, server: str, tool: str) -> tuple[dict, dict]:
    servers = _servers(output_dir)
    if not servers:
        raise WebRefused("The organisation has no MCP server connected (Settings → Integrations → MCP servers).")
    entry = next((s for s in servers if str(s["name"]).strip().lower() == server.strip().lower()), None)
    if entry is None:
        raise WebRefused(f"There is no MCP server called {server!r}; the organisation's are: "
                         + ", ".join(str(s["name"]) for s in servers) + ".")
    if entry.get("tools") is None:
        raise WebRefused(f"{entry['name']} did not answer: {entry.get('error') or 'no tools listed'}.")
    found = next((t for t in entry["tools"] if t["name"] == tool), None)
    if found is None:
        raise WebRefused(f"{entry['name']} has no tool called {tool!r}; it has: "
                         + ", ".join(t["name"] for t in entry["tools"][:40]) + ".")
    return entry, found


def call_mcp_tool(args: dict, *, output_dir: str = "", consented: bool = False,
                  unattended: bool = False) -> Step:
    server, tool = str(args.get("server") or "").strip(), str(args.get("tool") or "").strip()
    arguments = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
    if not server or not tool:
        raise WebRefused("`call_mcp_tool` needs `server` and `tool` (`list_services` names them).")
    entry, found = _tool_of(output_dir, server, tool)
    missing = [r for r in found.get("required") or [] if r not in arguments]
    if missing:
        raise WebRefused(f"`{tool}` needs {', '.join(missing)} in `arguments`.")
    shown = f"{entry['name']} → {tool}\narguments:\n{json.dumps(arguments, indent=2)[:3000]}"
    looks = found.get("read_only") or allowed(output_dir, entry["name"], tool)
    if not looks and not consented:
        if unattended:
            return Step(said="This tool may change something and nobody is here to agree, so it did not run:\n" + shown)
        _hold(output_dir, "call_mcp_tool", {"server": entry["name"], "tool": tool, "arguments": arguments}, shown)
        return Step(said=shown, options=[YES_LABEL, ALWAYS_LABEL, NO_LABEL], ask=(
            f"{entry['name']} does not say `{tool}` only looks, so I have not run it. Here is exactly "
            "what I would run:\n\n" + shown + "\n\nShall I run it?"))
    try:
        result = _mcp_call(output_dir, entry["name"], tool, arguments)
    except WebRefused:
        raise
    except Exception as exc:  # noqa: BLE001
        return Step(said=f"{shown}\nThe tool failed: {str(getattr(exc, 'detail', exc))[:300]}")
    parts: list[str] = []
    for block in result.get("content") or []:
        if block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        else:
            parts.append(f"[{block.get('type')} content, {len(json.dumps(block))} characters]")
    text = scrub("\n".join(parts))
    try:
        text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        pass
    kept = _keep(output_dir, {"request": shown, "isError": bool(result.get("isError")), "response": text})
    head = f"{entry['name']} → {tool}" + (" — the tool reported an error" if result.get("isError") else "")
    out = [head, MATERIAL, "--- result ---", text[:PART_CHARS] or "(empty)"]
    if len(text) > PART_CHARS:
        out.append(f"--- cut at {PART_CHARS} of {len(text)} characters; the whole result is in `{kept}` (read_file) ---")
    return Step(said="\n".join(out))


def app_mcp(output_dir: str, action: str, *, unattended: bool = False) -> str:
    """Say, or change, whether assistants may connect to this application."""
    from services import app_settings
    from services.blueprint.app_mcp import CATALOG

    action = action.strip().lower()
    if action in ("on", "off"):
        if unattended:
            return "Whether assistants may connect is the owner's choice; nothing was changed."
        app_settings.set_mcp(output_dir, action == "on", by="smith")
    elif action not in ("", "status"):
        return "`action` is status, on or off."
    on = app_settings.mcp_enabled(output_dir)
    lines = [("On" if on else "Off") + " — assistants " + ("may" if on else "may not") + " connect to this app"
             + (" (the preview now; the live app with its next publish)." if action in ("on", "off") else ".")]
    try:
        data = json.loads((Path(output_dir) / "app" / CATALOG).read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    def who(roles: Any) -> str:
        return "anyone signed in" if not roles else ", ".join("everyone" if r == "*" else
                                                               "anyone signed in" if r == "@signed-in" else r
                                                               for r in roles)
    flows, records = data.get("workflows") or [], data.get("records") or []
    if flows or records:
        lines.append(f"Tools ({len(flows)} processes, {len(records)} record types — each as the person whose token it is):")
        lines += [f"- `{w['tool']}` runs {w['name']} — {who(w.get('roles'))}" for w in flows[:40]]
        lines += [f"- `{r['find']}` / `{r['get']}` read {r['name']} — {who(r.get('roles'))}" for r in records[:40]]
    else:
        lines.append("The tool list has not been written for this app yet; it is written with the next sync.")
    if on:
        lines.append("A person connects on the app's “Connect an AI assistant” page (/connect-ai): "
                     "the address is the app's /api/mcp, with a token they make there.")
    return "\n".join(lines)


def run(name: str, args: dict, *, said: Iterable[str], output_dir: str = "", consented: bool = False,
        unattended: bool = False, doc: dict | None = None) -> Step:
    """Carry out one call. A refusal IS the observation."""
    args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    try:
        if name == "list_services":
            return Step(said=list_services(output_dir))
        if name == "app_mcp":
            return Step(said=app_mcp(output_dir, str(args.get("action") or "status"), unattended=unattended))
        if name == "check_services":
            from services.blueprint import api_reference
            return Step(said=scrub(api_reference.check_report(output_dir, doc or {})))
        if name == "call_api":
            return call_api(args, said=said, output_dir=output_dir, consented=consented, unattended=unattended)
        if name == "call_mcp_tool":
            return call_mcp_tool(args, output_dir=output_dir, consented=consented, unattended=unattended)
    except WebRefused as refused:
        return Step(said=str(refused))
    except (ValueError, TypeError) as exc:
        return Step(said=f"`{name}` could not run with those arguments: {exc}")
    raise KeyError(name)


__all__ = ["ACT", "ACT_NAMES", "ALWAYS_LABEL", "NO_LABEL", "YES_LABEL", "Credential", "Step",
           "allowed", "answer_held", "belongs_to", "call_api", "call_mcp_tool", "clear_held",
           "held", "list_services", "run", "sent_by_person"]
