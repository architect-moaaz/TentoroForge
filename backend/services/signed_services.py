"""Outside systems the runtime signs a call to by itself.

Most systems a step calls are signed with one secret the step names
(`auth: {"secretRef": "XERO_API_KEY", "in": "bearer"}`). Some cannot be:
Mews's Connector API reads two tokens and a client name from the JSON BODY
of every request, and its host differs between the demo and live
environments. For those the step names the provider (`auth: {"provider":
"mews"}`) and the path; the runtime's `http_call` handler adds the host and
the credentials from the organisation's keys (Settings → Integrations), which
are the registry's keys for that provider (`node_config_specs`).

One table, read by the step checks, the agents' prompts and the settings, so
none of them says more than the runtime can do.
"""
from __future__ import annotations

from typing import Any

#: provider → what a step needs to know to reach it.
SIGNED: dict[str, dict[str, Any]] = {
    "mews": {
        "name": "Mews",
        "keys": ("MEWS_CLIENT_TOKEN", "MEWS_ACCESS_TOKEN"),
        "path": "/api/connector/v1/<resource>/<operation>",
        "example": "/api/connector/v1/reservations/getAll/2023-06-06",
        "docs": "https://docs.mews.com/connector-api",
    },
}


def signed(provider: Any) -> bool:
    """Whether the runtime signs calls to this provider itself."""
    return str(provider or "").strip().lower() in SIGNED


def step_lines() -> str:
    """For whoever writes steps: how a step reaches each such system."""
    return " ".join(
        f"A call to {s['name']} is an `http_call` with `auth: {{\"provider\": \"{p}\"}}` and `url` the API path "
        f"(`{s['example']}`; {s['path']}): the runtime posts it to the right host and adds the credentials, "
        "so the step names no secret and writes none in its body; the body carries the operation's own "
        f"fields. It needs an integration with `provider: \"{p}\"`."
        for p, s in SIGNED.items()
    )


def adapter_lines() -> list[str]:
    """For the integrations agent: the names such a system's integration declares."""
    return [f"- {s['name']} — provider `{p}`, `serves: \"\"`: {', '.join(s['keys'])} (the runtime signs its calls)"
            for p, s in SIGNED.items()]


__all__ = ["SIGNED", "adapter_lines", "signed", "step_lines"]
