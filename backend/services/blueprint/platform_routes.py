"""The routes the platform adds to every application, declared like its pages.

An application's own pages come from its Blueprint and each says who may open
it (`access`). These do not: the platform puts them in every app, so no
Blueprint lists them. They were a list of words (`_ALWAYS_OPEN`) spliced into
the middleware's negative lookahead, which matches a path that STARTS with the
word — `pay` opened `/payments` and `/payroll`, and adding `install` would have
opened `/installments` in every app (PR #28 review, 2026-10-22).

Declared here instead, each with its route, whether what lies under it is
included, and why it is open, and turned into the same anchored patterns the
role-restricted pages use. The middleware asks one question of one list: is
this exact route public?
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class PlatformRoute:
    route: str
    #: True: the route and everything under it (`/api/auth/...`); False: the
    #: route alone.
    subtree: bool
    why: str
    #: Present in this application at all — a route the platform adds only to
    #: some applications says when.
    when: Callable[[dict], bool] | None = None


#: Every route the platform adds that a signed-out visitor must reach.
PUBLIC: tuple[PlatformRoute, ...] = (
    # The pages that create or restore a session cannot themselves require one.
    PlatformRoute("/login", False, "where a person signs in"),
    PlatformRoute("/signup", False, "where a person makes an account"),
    # Where a setup link lands: someone invited, or whose password was reset,
    # chooses a password. Gated, it would send the one visitor who certainly
    # cannot sign in yet to the sign-in they cannot complete. It shows only
    # the email its own one-time token resolves to.
    PlatformRoute("/set-password", False, "where an invited person chooses a password"),
    # What an installed app shows with no network. The service worker keeps
    # it; gated, a signed-out visitor offline was sent to a sign-in that
    # cannot load.
    PlatformRoute("/offline", False, "what an installed app shows with no network"),
    # The stand-in checkout: a signed-out buyer (a guest cart) is sent here
    # too; it shows an amount by a session id and charges nothing.
    PlatformRoute("/pay", True, "the stand-in checkout, for a guest's cart too"),
    PlatformRoute("/api/auth", True, "the sign-in machinery itself"),
    # Machines, not people: the scheduler's tick and another system's signed
    # call. Each authenticates itself — the tick by CRON_SECRET, a webhook by
    # its signature — and neither can hold a session; gated, every scheduled
    # process in every published app slept (2026-10-11).
    PlatformRoute("/api/cron", True, "the scheduler's tick, which carries CRON_SECRET"),
    PlatformRoute("/api/webhooks", True, "another system's signed call"),
    PlatformRoute("/api/pay", True, "the stand-in checkout's answers"),
    # An assistant holds a token, not a session: the MCP route checks the
    # person's token itself (and answers 404 unless the owner turned it on).
    PlatformRoute("/api/mcp", True, "an assistant's calls, which carry their own token"),
    # Where a link or a QR code sends someone who wants the app on their phone: they have not signed in, and the page shows what installing
    # is and nothing of theirs. Only an installable app has it (`projection.project_pwa` writes it, and removes it when the app stops being one).
    PlatformRoute("/install", False, "where someone who wants the app on their phone is sent", when=lambda doc: _installable(doc)),
)


def _installable(doc: dict) -> bool:
    from services.blueprint.pwa_check import installable

    return installable(doc)


def public_for(doc: dict) -> list[PlatformRoute]:
    """The platform's public routes present in this application."""
    return [r for r in PUBLIC if r.when is None or r.when(doc)]


__all__ = ["PlatformRoute", "PUBLIC", "public_for"]
