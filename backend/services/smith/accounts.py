"""The people who log in — added, removed, and given a way back in.

"Set up logins for my six staff" and "reset Dave's password" are the moment an
owner hands the application to their team, and both were dead ends. `edit_access`
changes what a ROLE may do; nothing could create, retire or restore one
PERSON's account, so an application whose roles were perfectly modelled still
had exactly one login — the seeded administrator — and everything else went
through it.

THIS IS NOT A BLUEPRINT CHANGE, and that is the decision the rest of the module
follows from. People are data, not definition: a staff list is not what the
application IS, it is who happens to use it this month. Recorded in the
Blueprint it would be versioned, cited by requirements, re-authored by agents,
and — worst — an `undo` of an unrelated change would silently re-admit someone
who had been removed. So the roster is a project ledger beside the pending
plan and the design records (`.forge/accounts.json`), and `revert` does not
touch it.

NOR DOES IT WRITE A CREDENTIAL. §97 makes `users` a platform table; a workflow
that writes `password` or `passwordHash` is refused at the author
(`functional_completeness`, rule `platform-credential-write`), and the reason
is not tidiness — the platform column holds a bcrypt hash, so anything else
written there is a password nobody can log in with. Account creation therefore
goes the way sign-up goes: through platform code that hashes. Smith mints a
one-time setup link, stores only its SHA-256, and the person chooses their own
password at `/set-password`, which `/api/auth/set-password` hashes with the
algorithm `auth.ts` verifies. No plaintext password is ever in Smith's hands,
in the conversation, or in the project.

WHAT A REMOVAL MEANS. Deactivation, not deletion. `authorize` rejects a falsy
`isActive`, so the person cannot sign in from the next start; the row stays
because every record they created points at it, and deleting it would orphan
their work to solve a problem that isActive already solves.

WHAT A RESET MEANS. Their password is replaced with the hash of a fresh random
UUID — a valid hash whose input nobody holds — so the old one stops working,
and a new setup link is issued. Smith never sends "here is your new password",
because it never has one.

WHEN IT TAKES EFFECT. The next time the application starts. A login has to
survive a redeploy or it is not a login: the database behind a generated app is
pushed, seeded and republished, so the roster is a file the seed applies on
every start (`seedAccounts` in `src/db/seed.ts`) rather than a row inserted
once into whichever database happened to be up.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

#: The roster, beside the other project ledgers — NOT in the Blueprint.
ROSTER_RELATIVE = Path(".forge") / "accounts.json"

#: What the seed reads. Written from the ledger, never edited by hand.
PROJECTED_RELATIVE = Path("src") / "db" / "accounts.json"

#: How long a setup link is good for. Long enough that a person on leave can
#: still use it, short enough that a link left in an inbox stops working.
INVITE_DAYS = 7

#: The account the seed creates so a fresh application is loginable at all
#: (`SEED_ADMIN_EMAIL` overrides it in a deployment; this is the default the
#: seed template and every journey fixture use).
SEEDED_ADMIN = "admin@example.com"

#: An address, not a name. Deliberately the shape a mail server would accept
#: and nothing more: this rejects "Dave" and accepts everything a person can
#: actually receive mail at, rather than ruling on which domains are real.
_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


class AccountsError(RuntimeError):
    """Said to the user as the reason nothing was changed."""


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------

def roster_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / ROSTER_RELATIVE


def load(output_dir: str | Path) -> dict:
    """The roster as it stands, or an empty one."""
    path = roster_path(output_dir)
    if not path.is_file():
        return {"accounts": []}
    try:
        doc = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise AccountsError(
            f"I could not read the list of people who log in ({exc}), so I "
            "have changed nothing.") from exc
    rows = doc.get("accounts") if isinstance(doc, dict) else doc
    return {"accounts": [r for r in (rows or []) if isinstance(r, dict)]}


def save(output_dir: str | Path, roster: dict) -> None:
    path = roster_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(roster, indent=2, sort_keys=True) + "\n", "utf-8")


def project(output_dir: str | Path, app_root: str | Path | None = None) -> list[str]:
    """Write the roster where the seed reads it. The files written.

    Called on every account change and again by `reproject` and assembly, so a
    rebuilt or restored application still knows who may log in.
    """
    root = Path(app_root) if app_root else Path(output_dir) / "app"
    roster = load(output_dir)
    if not roster["accounts"] and not (root / PROJECTED_RELATIVE).exists():
        return []
    out = root / PROJECTED_RELATIVE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(roster, indent=2, sort_keys=True) + "\n", "utf-8")
    return [str(PROJECTED_RELATIVE)]


def live(roster: dict) -> list[dict]:
    """The accounts that can still be signed into."""
    return [a for a in roster["accounts"] if str(a.get("status") or "active") != "removed"]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mint_invite(purpose: str) -> tuple[str, dict]:
    """A setup link's token, and the record of it that may be stored.

    The token is returned ONCE, to be shown to the owner and then forgotten.
    What goes to disk and to the database is its digest, so neither the project
    nor a copy of the database is a way in.
    """
    token = secrets.token_urlsafe(32)
    return token, {
        "issue": f"INV-{uuid.uuid4().hex[:12]}",
        "tokenHash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "purpose": purpose,
        "expiresAt": (datetime.now(timezone.utc).replace(microsecond=0)
                      + timedelta(days=INVITE_DAYS)).isoformat(),
    }


def _entry(roster: dict, email: str) -> dict | None:
    for account in roster["accounts"]:
        if str(account.get("email") or "").strip().lower() == email:
            return account
    return None


def resolve(roster: dict, person: str) -> dict:
    """The account `person` names — by email, or by the name it was added under.

    Refuses rather than guesses. "Dave" with two Daves on the roster is a real
    question, and picking one resets the wrong person's password; "Dave" with
    none is a typo worth saying out loud rather than an account to create.
    """
    said = " ".join(str(person or "").split()).strip().lower()
    if not said:
        raise AccountsError("nobody was named, so there is no account to change.")
    accounts = roster["accounts"]
    if not accounts:
        raise AccountsError(
            "nobody has been given a login yet, so there is none to change. "
            "Ask me to add one with the email address they should sign in with.")

    by_email = [a for a in accounts if str(a.get("email") or "").strip().lower() == said]
    if by_email:
        return by_email[0]
    by_name = [a for a in accounts
               if str(a.get("name") or "").strip().lower() == said]
    if not by_name:
        # A first name is how people refer to each other, so it is matched —
        # but only as a whole word, and only when it picks out exactly one.
        by_name = [a for a in accounts
                   if said in str(a.get("name") or "").strip().lower().split()]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise AccountsError(
            f"“{person}” matches {len(by_name)} of the people who log in — "
            + ", ".join(f"{a.get('name') or a.get('email')} ({a.get('email')})" for a in by_name)
            + ". Say which by email address.")
    raise AccountsError(
        f"nobody who logs in is called “{person}”. The people who do: "
        + _roster_line(roster) + ".")


def _roster_line(roster: dict) -> str:
    parts = []
    for account in roster["accounts"]:
        who = str(account.get("email") or "")
        name = str(account.get("name") or "").strip()
        label = f"{name} ({who})" if name else who
        if str(account.get("status") or "active") == "removed":
            label += " — removed"
        parts.append(label)
    return ", ".join(parts) or "nobody yet"


def _log(account: dict, did: str) -> None:
    account.setdefault("log", []).append({"at": _now(), "did": did})


# ---------------------------------------------------------------------------
# the three changes
# ---------------------------------------------------------------------------

def add(output_dir: str | Path, *, email: str, name: str = "", role: str = "",
        app_root: str | Path | None = None, reasoning: Any = None) -> dict:
    """Give one person a login, waiting for the password only they will know."""
    address = " ".join(str(email or "").split()).strip().lower()
    if not address:
        raise AccountsError(
            "I need the email address they will sign in with — that is what "
            "identifies an account.")
    if not _EMAIL.match(address):
        raise AccountsError(
            f"“{email}” is not an email address, and an account is identified "
            "by one. Give me the address they will sign in with.")

    roster = load(output_dir)
    existing = _entry(roster, address)
    if existing is not None and str(existing.get("status") or "active") != "removed":
        raise AccountsError(
            f"{address} can already log in. If they cannot get in, ask me to "
            f"reset {address} and I will send a fresh setup link.")
    if address == SEEDED_ADMIN:
        raise AccountsError(
            f"{SEEDED_ADMIN} is the administrator account every application is "
            "seeded with, so it already exists. Ask me to reset it if the "
            "password needs changing.")

    token, invite = _mint_invite("invite")
    account = existing if existing is not None else {"email": address}
    account.update({"email": address, "status": "active", "invite": invite})
    if name.strip():
        account["name"] = " ".join(name.split())
    if role.strip():
        account["role"] = " ".join(role.split())
    if existing is None:
        roster["accounts"].append(account)
    _log(account, "added" if existing is None else "re-added")

    save(output_dir, roster)
    files = project(output_dir, app_root)
    tell(reasoning, f"Added a login for {address}, waiting for its password.", "step")
    return {"applied": True, "did": "added", "account": account, "token": token,
            "roster": roster, "edited_paths": files}


def remove(output_dir: str | Path, *, person: str,
           app_root: str | Path | None = None, reasoning: Any = None) -> dict:
    """Stop one person signing in, without deleting what they did."""
    roster = load(output_dir)
    account = resolve(roster, person)
    address = str(account.get("email") or "").strip().lower()
    if address == SEEDED_ADMIN:
        raise AccountsError(
            f"{SEEDED_ADMIN} is the account that makes the application "
            "loginable at all — the seed creates it on every start, so "
            "removing it would lock everyone out and not even hold. Reset it "
            "instead, or remove the people who no longer need it.")
    if str(account.get("status") or "active") == "removed":
        raise AccountsError(f"{address} cannot sign in already.")

    account["status"] = "removed"
    # A LINK IN AN INBOX IS A WAY IN. Setting a password activates the account,
    # so a pending invite has to go with the person it was issued to.
    account["invite"] = None
    _log(account, "removed")

    save(output_dir, roster)
    files = project(output_dir, app_root)
    tell(reasoning, f"Removed the login for {address}.", "step")
    return {"applied": True, "did": "removed", "account": account, "token": "",
            "roster": roster, "edited_paths": files}


def reset(output_dir: str | Path, *, person: str,
          app_root: str | Path | None = None, reasoning: Any = None) -> dict:
    """Invalidate one person's password and issue a fresh setup link."""
    roster = load(output_dir)
    account = resolve(roster, person)
    address = str(account.get("email") or "").strip().lower()
    if str(account.get("status") or "active") == "removed":
        raise AccountsError(
            f"{address} was removed, so there is no password to reset. Ask me "
            f"to add {address} again and they will get a fresh setup link.")

    token, invite = _mint_invite("reset")
    account["invite"] = invite
    _log(account, "reset")

    save(output_dir, roster)
    files = project(output_dir, app_root)
    tell(reasoning, f"Reset the password for {address}.", "step")
    return {"applied": True, "did": "reset", "account": account, "token": token,
            "roster": roster, "edited_paths": files}


# ---------------------------------------------------------------------------
# what the user is told
# ---------------------------------------------------------------------------

def _base_url(output_dir: str | Path, app_root: str | Path | None = None) -> str:
    """The address the application answers on, as the app itself records it.

    Read from `NEXTAUTH_URL` in the app's own env file rather than guessed. An
    application published since that file was written answers somewhere else,
    which is why the summary gives the PATH as well and says so.
    """
    root = Path(app_root) if app_root else Path(output_dir) / "app"
    for candidate in (root / ".env.local", root / ".env",
                      Path(output_dir) / ".env.local"):
        if not candidate.is_file():
            continue
        try:
            for line in candidate.read_text("utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "NEXTAUTH_URL" and value.strip():
                    return value.strip().rstrip("/")
        except OSError:
            continue
    return ""


def setup_link(token: str, base_url: str = "") -> str:
    """Where the person goes to choose their password."""
    path = f"/set-password?token={token}"
    return f"{base_url}{path}" if base_url else path


def summary_of(out: dict, base_url: str = "") -> str:
    """What happened, the link if there is one, and when it takes effect."""
    account = out["account"]
    email = str(account.get("email") or "")
    name = str(account.get("name") or "").strip()
    who = f"**{name}** ({email})" if name else f"**{email}**"
    lines: list[str] = []

    if out["did"] == "removed":
        lines += [f"{who} can no longer sign in.",
                  "",
                  "Their account is deactivated rather than deleted — every record "
                  "they created still points at it, so deleting it would take their "
                  "work with it. Any setup link they were sent has been cancelled."]
    else:
        role = str(account.get("role") or "").strip()
        opened = "has a login" if out["did"] == "added" else "has a new password to set"
        lines += [f"{who} {opened}" + (f", signing in as **{role}**" if role else "") + ".",
                  "",
                  "Send them this link — it is the only time I can show it, because "
                  "all I keep is a fingerprint of it:",
                  "",
                  f"`{setup_link(out['token'], base_url)}`",
                  "",
                  f"It works once, expires in {INVITE_DAYS} days, and asks them to "
                  "choose their own password. I never see it: nobody — not me, not "
                  "the application's definition — holds a password for anyone."]
        if not base_url:
            lines += ["",
                      "Put that path after your application's own address."]
        elif out["did"] == "reset":
            lines += ["",
                      "If you have published the application since, use the published "
                      "address with the same path."]

    people = live(out["roster"])
    lines += ["",
              f"{len(people)} {'person' if len(people) == 1 else 'people'} can sign in: "
              + ", ".join(sorted(str(a.get("email")) for a in people)) + ".",
              "",
              "This takes effect the next time the application starts — preview it "
              "or publish it — because who may log in is written into the project so "
              "that it survives a redeploy, not into whichever database is up now."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# the shape a verb and a tool need
# ---------------------------------------------------------------------------

#: verb -> the function that serves it.
_RUNNERS = {"add_login": add, "remove_login": remove, "reset_login": reset}


def run(output_dir: str, verb: str, *, email: str = "", person: str = "",
        name: str = "", role: str = "", reasoning: Any = None) -> dict:
    """One account change from an `output_dir` — the shape a handler needs."""
    runner = _RUNNERS.get(verb)
    if runner is None:
        return {"applied": False, "edited_paths": [],
                "reason": f"{verb} is not something I do to a login."}
    app_root = Path(output_dir) / "app"
    kwargs: dict[str, Any] = {"app_root": str(app_root), "reasoning": reasoning}
    if verb == "add_login":
        kwargs.update({"email": email or person, "name": name, "role": role})
    else:
        kwargs["person"] = person or email
    try:
        out = runner(str(output_dir), **kwargs)
    except AccountsError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a turn degrades, it does not crash
        logger.exception("[smith] %s failed", verb)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out.get("edited_paths") or [],
            "diff_summary": summary_of(out, _base_url(output_dir, app_root)),
            "reason": "", "did": out["did"],
            "email": str(out["account"].get("email") or "")}


def people(output_dir: str | Path) -> str:
    """Who can sign in, for an answer that does not change anything."""
    return _roster_line(load(output_dir))


__all__ = ["AccountsError", "INVITE_DAYS", "PROJECTED_RELATIVE", "ROSTER_RELATIVE",
           "SEEDED_ADMIN", "add", "live", "load", "people", "project", "remove",
           "reset", "resolve", "roster_path", "run", "save", "setup_link",
           "summary_of"]
