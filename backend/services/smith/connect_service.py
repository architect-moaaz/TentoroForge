"""One verb, many adapters: "connect it to X".

`connect_service` used to be the email adapter alone. The registry holds
every adapter the runtime has — each a module with `SERVES` (the action it
carries), `SERVICES` (the owner's words for a provider), `service_for`,
`connect`, `summarise` and `refusal` — and the verb tries each. A system
no adapter carries is DECLARED, with the names of its secrets, and the
reply says how a step reaches it: that is not a refusal, it is the shape
such a system has in this application.
"""
from __future__ import annotations

import logging
from typing import Any

from services.smith import email_connect

logger = logging.getLogger(__name__)

#: The adapters, in the order they are tried.
ADAPTERS: tuple[Any, ...] = (email_connect,)


def actions() -> set[str]:
    """Every action an adapter carries (`send_email`, …)."""
    return {str(a.SERVES) for a in ADAPTERS}


def adapter_for(action: str) -> Any | None:
    return next((a for a in ADAPTERS if str(a.SERVES) == action), None)


def providers_of(action: str) -> dict[str, list[str]]:
    """`{provider: [key names]}` for the adapter that carries `action`."""
    adapter = adapter_for(action)
    if adapter is None:
        return {}
    out: dict[str, list[str]] = {}
    for svc in getattr(adapter, "SERVICES", ()) or ():
        provider = str(getattr(svc, "provider", "") or "")
        if provider and provider not in out:
            out[provider] = list(adapter.keys_for(provider))
    return out


def live_key(action: str, provider: str) -> str | None:
    """The variable whose presence means `provider` carries `action` live."""
    adapter = adapter_for(action)
    table = getattr(adapter, "LIVE_KEY", {}) if adapter else {}
    return table.get(provider)


def from_key(action: str) -> str:
    adapter = adapter_for(action)
    return str(getattr(adapter, "FROM_KEY", "") or "") if adapter else ""


def adapter_lines() -> str:
    """The adapters, for the integrations agent: what the runtime can carry."""
    lines = ["The runtime has adapters for these actions; an integration that `serves` one uses that "
             "adapter's provider and the NAMES it reads:"]
    for action in sorted(actions()):
        for provider, keys in providers_of(action).items():
            lines.append(f"- {action} — provider `{provider}`: {', '.join(keys)}")
    lines.append("Any other system is declared with `serves: \"\"` and its own names, and reached from a "
                 "workflow step's `auth`; one that calls the application declares `inbound`.")
    return "\n".join(lines)


def run(output_dir: str, *, service: str, reasoning: Any = None) -> dict[str, Any]:
    """Connect `service` through the adapter that carries it; declare it
    when none does."""
    from services.smith.secrets_scrub import carries_secret
    said = (service or "").strip()
    if said and carries_secret(said):
        return email_connect.run(output_dir, service=said, reasoning=reasoning)   # the same guard, the same words
    for adapter in ADAPTERS:
        if said and adapter.service_for(said) is not None:
            return adapter.run(output_dir, service=said, reasoning=reasoning)
    if not said:
        return email_connect.run(output_dir, service=said, reasoning=reasoning)
    return declare(output_dir, said, reasoning=reasoning)


def declare(output_dir: str, service: str, *, reasoning: Any = None) -> dict[str, Any]:
    """A system no adapter carries: declared with the names of its secrets,
    reachable from a step. The reply says exactly how."""
    from services.blueprint.service import BlueprintService
    from services.smith.definition_change import add_integration
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no Blueprint yet.", "options": []}
    try:
        out = add_integration(svc, f"Connect the application to {service}", reasoning=reasoning)
    except Exception as exc:  # noqa: BLE001 — the agent could not declare it: say so, offer what does work
        logger.warning("[connect-service] could not declare %r", service, exc_info=True)
        why, options = email_connect.refusal(service, svc.doc)
        return {"applied": False, "edited_paths": [], "reason": f"{why} ({type(exc).__name__}: {str(exc)[:160]})",
                "options": options}
    names = ", ".join(out.get("secrets") or []) or "its key"
    return {"applied": True, "edited_paths": list(out.get("edited_paths") or []), "reason": "", "options": [],
            "diff_summary": (f"Declared {out.get('name') or service} ({out.get('provider') or 'no adapter'}). "
                             f"Nothing in the runtime sends through it by itself: a process reaches it with a step "
                             f"that calls it, carrying `auth` naming {names}. Set {names} under Settings → "
                             "Integrations; the value never leaves the platform."),
            **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["ADAPTERS", "actions", "adapter_for", "adapter_lines", "declare", "from_key", "live_key",
           "providers_of", "run"]
