"""Outbound email: from "connect it to our Outlook" to an app that sends.

WHAT WAS WRONG. `add_integration` records a row in the Blueprint's
`integrations` — a name, a kind, a provider and the NAMES of the secrets it
would need — and changes nothing else. From the owner's chair that is
indistinguishable from a broken application: the workflow still has its "email
the customer" step, the step still runs, and the run still reports success,
because the runtime's send falls back to an in-app notification when no
provider is configured. Two of the sentences owners arrive with — "the
confirmation email never came" and "it's sending from a weird address" — are
that one gap, and this closes them. The third, "it's supposed to text the
customer and it doesn't", is SMS: there is no adapter for it, so it gets the
refusal below rather than a connection it would be a lie to claim.

WHAT A CONNECTION IS HERE. Four things, and Claude never holds the third:

1. The owner names their service. "Our Outlook", "Resend", "send the emails
   through our own account" — :data:`SERVICES` is the list of the services
   there is an adapter for, in the words owners use for them.
2. The Blueprint records the service and the NAMES of the variables that
   carry its credential (§42/§99: names only, never a value, and that holds
   for the ledger and the conversation too).
3. The owner sets the value themselves, once, on the platform's
   Settings → Integrations page. It is encrypted per organisation, and it
   reaches the application two ways that already existed:
   `services.env_writer` writes it into `<output>/.env.local` for a local
   run, and `services.deploy.env_sync.build_deploy_env` pushes it into the
   deployment's environment at publish. So a PUBLISHED app's variable is set
   on the platform and shipped by the publish — not typed into a chat, not
   committed to the app, and not read back by anything (the settings API
   never echoes a `password` field).
4. The projection writes the binding into the app —
   `src/lib/integrations/connected.ts` — so the step that sends knows which
   service it is sending through, and the app can say plainly when none is
   connected instead of quietly not sending.

WHY A DECLARED LIST OF SERVICES AND NOT A GUESS. An owner's word is not a
provider key: "Outlook", "Office 365" and "our own mail server" are all the
SMTP adapter, and Xero is not an email service at all. The runtime has exactly
two ways to send — SMTP, and Resend's API (`templates/runtime/workflows`
chooses between them, SMTP first) — so exactly two adapters can be honest.
Everything else is refused with the reason and the nearest thing that works,
the shape `services.smith.limits` uses for the other asks Smith cannot serve.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: The workflow action type an email connection serves. One string, used by
#: the Blueprint's `integrations[].serves`, by the projection and by the
#: runtime — so "is this app's email connected" is one question everywhere.
SERVES = "send_email"

#: The from-address. Not a secret and not optional in practice: unset, mail
#: goes out from the provider's sandbox address, which is the owner sentence
#: "it's sending from a weird address". Declared under `resend` in
#: `node_config_specs` and read by BOTH paths, so it is named here as well.
FROM_KEY = "FORGE_EMAIL_FROM"

#: provider -> the key whose presence makes the application actually send.
#: This mirrors the runtime's own precedence (SMTP wins when SMTP_HOST is
#: set, Resend otherwise); `project_integrations` hands it to the app so the
#: rule is stated once rather than re-decided in TypeScript.
LIVE_KEY: dict[str, str] = {"smtp": "SMTP_HOST", "resend": "RESEND_API_KEY"}


@dataclass(frozen=True)
class EmailService:
    """One service an owner can name, and the adapter that carries it.

    `words` are what owners type, not what the provider calls itself: this is
    the only place the two vocabularies meet, and it is a list rather than a
    pattern because "no adapter for that" has to be a real answer.
    """

    name: str
    provider: str
    words: tuple[str, ...]
    #: What the provider documents for its SMTP relay. Advice, not a secret —
    #: the owner's own server overrides it, and it is what turns "connected"
    #: into something they can finish without leaving the conversation.
    host: str = ""
    port: str = ""
    #: The one thing that surprises people about this service's credential.
    caveat: str = ""

    @property
    def keys(self) -> list[str]:
        return keys_for(self.provider)

    @property
    def live_key(self) -> str:
        return LIVE_KEY[self.provider]


#: Ordered so the longest, most specific word wins a match: "google workspace"
#: before "google", "our own mail server" before "mail server".
SERVICES: tuple[EmailService, ...] = (
    EmailService(
        "Resend", "resend", ("resend",),
        caveat="the API key is enough; there is no host or password.",
    ),
    EmailService(
        "Microsoft 365 / Outlook", "smtp",
        ("microsoft 365", "microsoft365", "office 365", "office365", "outlook",
         "exchange online", "exchange", "microsoft"),
        host="smtp.office365.com", port="587",
        caveat="Microsoft requires an account with SMTP AUTH enabled; a "
               "mailbox with modern authentication only will refuse the login.",
    ),
    EmailService(
        "Google Workspace / Gmail", "smtp",
        ("google workspace", "g suite", "gsuite", "gmail", "google mail", "google"),
        host="smtp.gmail.com", port="587",
        caveat="use an app password, not the account password.",
    ),
    EmailService(
        "SendGrid", "smtp", ("sendgrid", "send grid"),
        host="smtp.sendgrid.net", port="587",
        caveat="the username is literally `apikey`, and the password is the API key.",
    ),
    EmailService("Mailgun", "smtp", ("mailgun",), host="smtp.mailgun.org", port="587"),
    EmailService("Postmark", "smtp", ("postmark",), host="smtp.postmarkapp.com", port="587"),
    EmailService(
        "your own mail server", "smtp",
        ("our own mail server", "your own mail server", "own mail server",
         "our own email account", "our own account", "our own email", "our own server",
         "own account", "mail server", "smtp server", "smtp"),
        caveat="I need the server's address, and the account it should sign in as.",
    ),
)


#: The services offered as chips when Smith has to ask which one. The order is
#: how often an owner means them, not the order of the registry, and it is
#: short because a question carrying five answers is a click and a question
#: carrying nine is a directory.
CHOICES: tuple[str, ...] = (
    "Microsoft 365 / Outlook",
    "Google Workspace / Gmail",
    "your own mail server",
    "Resend",
    "SendGrid",
)


class NoEmailAdapter(RuntimeError):
    """The named service is not one the runtime can send through."""


def keys_for(provider: str) -> list[str]:
    """Every variable NAME this provider's send path reads.

    Read from `node_config_specs`, which is what the settings page renders and
    what `env_writer` is allowed to write — so a key Smith names is a key the
    owner can actually set, and there is no second list of them.
    """
    from services.node_config_specs import keys_for_provider

    keys = [e.key for e in keys_for_provider(provider)]
    if FROM_KEY not in keys:
        keys.append(FROM_KEY)
    return keys


def service_for(said: str) -> EmailService | None:
    """The service these words name, or None when no adapter carries it."""
    from services.smith.labels import normalise

    text = normalise(said or "")
    if not text:
        return None
    hits = [(len(word), s) for s in SERVICES for word in s.words
            if normalise(word) in text]
    if not hits:
        return None
    # The longest word that matched: "google workspace" is Google Workspace,
    # not the bare "google" of some other sentence.
    return max(hits, key=lambda h: h[0])[1]


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict)
            and r.get("status") not in ("DEPRECATED", "SUPERSEDED")]


def declared(doc: dict) -> dict | None:
    """The integration this application sends its email through, if one is
    declared. One row at most: `connect` retires any other that claimed it."""
    for row in _live((doc or {}).get("integrations")):
        if str(row.get("serves") or "") == SERVES:
            return row
    return None


def sending_steps(doc: dict) -> list[tuple[str, str]]:
    """Every workflow step that sends email, as (workflow name, step name).

    This is what makes the gap concrete: an application with one of these and
    no connected service has a step that runs and a message that is never
    delivered.
    """
    out: list[tuple[str, str]] = []
    for wf in _live((doc or {}).get("workflows")):
        for step in wf.get("steps") or []:
            if not isinstance(step, dict):
                continue
            config = step.get("config") if isinstance(step.get("config"), dict) else {}
            if str(config.get("actionType") or "") == SERVES:
                out.append((str(wf.get("name") or wf.get("id") or "a workflow"),
                            str(step.get("name") or step.get("key") or SERVES)))
    return out


@dataclass(frozen=True)
class Connection:
    """What is true right now about this application's outbound email."""

    row: dict | None
    #: NAMES of the variables that are set, from the platform store or the
    #: environment. Never a value — see `services.platform_secrets`.
    set_keys: frozenset[str] = frozenset()

    @property
    def keys(self) -> list[str]:
        return [str(k) for k in (self.row or {}).get("secretRefs") or []]

    @property
    def live_key(self) -> str:
        provider = str((self.row or {}).get("provider") or "")
        return LIVE_KEY.get(provider, "")

    @property
    def connected(self) -> bool:
        """Declared AND its credential is set where the app will read it."""
        return bool(self.row) and self.live_key in self.set_keys

    @property
    def missing(self) -> list[str]:
        """The names still unset, `FORGE_EMAIL_FROM` among them — a send that
        works from an address nobody chose is the third owner complaint."""
        return [k for k in self.keys if k not in self.set_keys]


def status(doc: dict, output_dir: str | None = None) -> Connection:
    """The connection as it stands: the declaration, and which names are set.

    `output_dir` is optional so a caller with only a document — a test, a
    projection — gets the declaration without a store lookup.
    """
    row = declared(doc)
    if row is None or not output_dir:
        return Connection(row=row, set_keys=frozenset())
    from services.platform_secrets import keys_set_for

    keys = [str(k) for k in row.get("secretRefs") or []]
    return Connection(row=row, set_keys=frozenset(keys_set_for(output_dir, keys)))


# --- the change ------------------------------------------------------------------

def connect(svc: Any, *, service: str, output_dir: str | None = None,
            reasoning: Any = None) -> dict[str, Any]:
    """Record the service this application's email goes through.

    Raises :class:`NoEmailAdapter` when the named service is not one the
    runtime can send through — the caller answers that with `refusal`.
    """
    from services.blueprint.ids import integration_key
    from services.llm_client import tell
    from services.smith.section_change import record_requirement

    chosen = service_for(service)
    if chosen is None:
        raise NoEmailAdapter(service)

    req = record_requirement(
        svc, f"Send the application's email through {chosen.name}.",
        owner="integrations")

    # ONE SERVICE CARRIES THE EMAIL. Two rows claiming `send_email` would make
    # "which one does it send through?" unanswerable, and the projection would
    # have to pick — so a new choice retires the old one rather than joining it.
    for row in _live(svc.doc.get("integrations")):
        if str(row.get("serves") or "") == SERVES and str(row.get("name") or "") != chosen.name:
            row["status"] = "DEPRECATED"

    before = svc.snapshot()
    row = svc.upsert("integrations", {
        "name": chosen.name,
        "kind": "email",
        "provider": chosen.provider,
        # NAMES. The value is the owner's to set, on the platform, once.
        "secretRefs": chosen.keys,
        "serves": SERVES,
        "status": "APPROVED",
        "requirements": [str(req.get("id"))] if req.get("id") else [],
    }, natural_key=integration_key(chosen.name))
    # COMMITTED, NOT JUST SAVED. §91 snapshots the pre-change document on
    # commit, which is what `revert` restores and what the history shows —
    # so choosing the wrong service is undoable like every other change, and
    # the entry says what changed without ever naming a value.
    svc.commit(user_request=f"connect the email to {service}".strip(),
               smith_interpretation=f"send email through {chosen.name} "
                                    f"({chosen.provider}); its credential is "
                                    f"read from {chosen.live_key}",
               before=before, affected=[str(row.get("id") or "")])
    tell(reasoning, f"Recorded {chosen.name} as the service that sends this "
                    f"application's email.", "step")

    files: list[str] = []
    if output_dir:
        from pathlib import Path

        from services.blueprint.projection import project_integrations

        # ONLY INTO AN APPLICATION THAT EXISTS. Asked before anything is
        # built, the choice is recorded and the build projects it; writing a
        # lone file into an empty `app/` would leave a directory that looks
        # like half an application to everything that probes for one.
        app_root = Path(output_dir) / "app"
        if app_root.is_dir():
            files = list(project_integrations(svc.doc, app_root).get("files") or [])

    conn = status(svc.doc, output_dir)
    return {"applied": True, "integration": str(row.get("id") or ""),
            "name": chosen.name, "provider": chosen.provider,
            "secrets": list(chosen.keys), "requirement": str(req.get("id") or ""),
            "connected": conn.connected, "set": sorted(conn.set_keys),
            "missing": conn.missing, "steps": sending_steps(svc.doc),
            "edited_paths": files}


# --- what Smith says -------------------------------------------------------------

def _where_to_set(keys: list[str]) -> str:
    named = ", ".join(f"`{k}`" for k in keys)
    return (f"Set {named} under **Settings → Integrations** on this platform — "
            "once per organisation, encrypted, and never shown back to anyone. "
            "A local run picks it up on the next sync; a published app gets it "
            "in its environment at the next publish. Do not paste the value "
            "here: this conversation is written to disk, so I only ever handle "
            "the NAME.")


def summarise(out: dict) -> str:
    """The reply to a connect, saying plainly which of the two states it is in."""
    name, keys = out["name"], list(out["secrets"])
    chosen = service_for(name)
    head = (f"**{name}** is now the service this application sends email "
            f"through ({out['integration']}, recorded as {out['requirement']}).")
    steps = out.get("steps") or []
    if steps:
        head += ("\n\nIt carries: "
                 + "; ".join(f"{step} in {wf}" for wf, step in steps[:5]) + ".")
    else:
        head += ("\n\nNothing sends email yet — say what should be emailed and "
                 "when, and the step will go through this service.")

    if out.get("connected"):
        body = (f"\n\n**Connected.** `{chosen.live_key if chosen else ''}` is set "
                "where the application reads it, so those steps send for real.")
        missing = [k for k in out.get("missing") or []]
        if FROM_KEY in missing:
            body += (f"\n\nOne thing left: `{FROM_KEY}` is not set, so mail goes "
                     "out from the provider's sandbox address rather than yours. "
                     "Set it to the address you want people to see.")
        elif missing:
            body += ("\n\nStill unset, which the send path can live without: "
                     + ", ".join(f"`{k}`" for k in missing) + ".")
        return head + body

    body = (f"\n\n**Declared, not yet connected** — nothing is sent until the "
            f"credential is set. " + _where_to_set(keys))
    if chosen and chosen.host:
        body += (f"\n\nFor {name} that is `SMTP_HOST` = `{chosen.host}` and "
                 f"`SMTP_PORT` = `{chosen.port}`, with the account's own "
                 "username and password.")
    if chosen and chosen.caveat:
        body += f" One catch: {chosen.caveat}"
    # WHAT THE APP WILL SAY, WORD FOR WORD ENOUGH TO RECOGNISE. The owner
    # meets the consequence before they read anything else, so the reply says
    # in advance what they are about to see.
    body += (f"\n\nUntil then the application says so where it happens: a step "
             f"that should have emailed reports that it is set up to go "
             f"through {name} but the credential is not set, and the message "
             "is kept as a notification. It does not report a send it did not "
             "make.")
    return head + body


def refusal(said: str, doc: dict) -> tuple[str, list[str]]:
    """Why a service cannot be connected, and the nearest thing that works.

    The shape `services.smith.limits` uses: what cannot be done, why in one
    clause, and what can — as sentences a click can say. Nothing changes.
    """
    from services.smith.labels import normalise

    what = (said or "").strip() or "that service"
    why = (f"I cannot connect **{what}** — connecting means an adapter that "
           "knows how to talk to it, and the only ones this application has "
           f"send email: {', '.join(CHOICES)}.")
    # ALREADY WRITTEN DOWN IS WORTH SAYING. Told "connect it to Xero" twice,
    # the second refusal used to read as though nothing had ever been
    # recorded, and the owner would declare it again.
    existing = next((r for r in _live((doc or {}).get("integrations"))
                     if normalise(str(r.get("name") or "")) == normalise(what)), None)
    if existing:
        why += (f"\n\nIt is already written down as {existing.get('id')} — the "
                "names of its secrets and nothing else. Recording it again "
                "would not change that.")
    nearest = ("\n\nWhat I can do:\n\n"
               f"• **Connect the email** for real, if that is what {what} was "
               "for — name the service and I will wire it up.\n"
               + ("" if existing else
                  f"• **Declare {what}** in the definition with the names of the "
                  "secrets it would need, so it is written down and a developer "
                  "can wire it up. I will say it is a declaration, not a "
                  "connection, every time it comes up.\n")
               + "• **Call its API from a workflow step**, if it has an HTTP API "
                 "and you tell me the request to make — that path is real today.")
    options = ["Connect the email instead"]
    if not existing:
        options.append(f"Declare {what} without connecting it")
    options.append(f"Call {what}'s API from a workflow step")
    return why + nearest, options


# --- the envelope ----------------------------------------------------------------

def run(output_dir: str, *, service: str, reasoning: Any = None) -> dict[str, Any]:
    """Connect `service`, or refuse it with the nearest thing that works.

    The same envelope every other seam answers in — `{applied, edited_paths,
    diff_summary, reason}` — plus `options`, because a refusal here offers
    three next moves and the panel renders them as chips. A refusal is
    `applied: False` with nothing changed, which is what makes it safe to give
    an honest answer instead of a wrong connection.
    """
    from services.blueprint.service import BlueprintService
    from services.smith.secrets_scrub import carries_secret, scrub

    said = (service or "").strip()
    if not said:
        return {"applied": False, "edited_paths": [],
                "reason": "which service should it use?", "options": list(CHOICES)}
    # A CREDENTIAL NEVER TRAVELS FURTHER THAN THE MESSAGE IT ARRIVED IN. The
    # conversation is scrubbed before it is stored; this is the same guard one
    # step further in, so a pasted key cannot reach a Blueprint field, a
    # requirement's wording or a reply by way of this argument.
    if carries_secret(said):
        return {"applied": False, "edited_paths": [], "options": list(CHOICES),
                "reason": ("That looks like it had a key in it, so I have not "
                           "recorded any of it. Name the service — \"our "
                           "Outlook\", \"Resend\" — and set the key itself "
                           "under Settings → Integrations, where it is "
                           "encrypted and never shown back. I only ever handle "
                           "the NAME of the variable it lives in.")}
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "this project has no Blueprint yet.", "options": []}
    try:
        out = connect(svc, service=said, output_dir=str(output_dir),
                      reasoning=reasoning)
    except NoEmailAdapter:
        why, options = refusal(scrub(said), svc.doc)
        return {"applied": False, "edited_paths": [], "reason": why,
                "options": options}
    except Exception as exc:  # noqa: BLE001 — a turn reports, never crashes
        logger.exception("[smith] connect_service failed for %r", said)
        return {"applied": False, "edited_paths": [],
                "reason": f"{type(exc).__name__}: {exc}", "options": []}
    return {"applied": True, "edited_paths": list(out.get("edited_paths") or []),
            "diff_summary": summarise(out), "reason": "", "options": [],
            **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["SERVES", "FROM_KEY", "LIVE_KEY", "SERVICES", "CHOICES", "EmailService",
           "Connection", "NoEmailAdapter", "connect", "declared", "keys_for",
           "refusal", "run", "sending_steps", "service_for", "status", "summarise"]
