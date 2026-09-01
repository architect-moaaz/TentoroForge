"""A2UI's own log, turned into something the user can read.

The composer already says what it is doing. `tools/a2ui-mcp/tracing.py` writes
a line per phase to **stderr** — deliberately, because an MCP stdio server
speaks the protocol on stdout and a stray print corrupts the session:

    [a3f1] provider.request  kimi/kimi-latest images=1 bytes=1.4MB
    [a3f1] provider.response 8.2s in=11k out=7k
    [a3f1] validate.fail     attempt=1 errors=3
    [a3f1] validate.ok       attempt=2 components=35

And the parent swallows it. tracing.py says so in its own comment — "which the
parent usually swallows" — which is why it also writes a file nobody reads.

So the minute a composition takes was never silent; the account of it went to a
stream with no listener. That is this session's shape once more, and the fix is
again to connect what exists rather than to build a second one: no change to
the A2UI repo, no new protocol, just reading the pipe.

WHAT IS NOT SURFACED. Byte counts, token counts, correlation ids and the
tool-call bookends are the composer talking to its own developer. The user is
waiting on one question — is it working, and how far has it got — so the
phrases answer that and nothing else.
"""

from __future__ import annotations

import re

#: `[rid] event.name            k=v k=v`
_LINE = re.compile(r"^\[(?P<rid>\w+)\]\s+(?P<event>\S+)\s*(?P<rest>.*)$")


def _fields(rest: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", rest or ""))


def phrase(line: str) -> str | None:
    """One line of A2UI's log as a sentence, or None to leave it unsaid."""
    m = _LINE.match((line or "").strip())
    if not m:
        return None
    event, f = m.group("event"), _fields(m.group("rest"))

    if event == "attempt.start":
        n, of = f.get("n"), f.get("of")
        return (f"Composing the layout — attempt {n} of {of}."
                if n and of else "Composing the layout.")
    if event == "provider.request":
        return "Asking the composition model for a layout."
    if event == "provider.response":
        secs = re.search(r"(\d+(?:\.\d+)?)s", m.group("rest") or "")
        return (f"The composer answered after {secs.group(1)}s; checking it."
                if secs else "The composer answered; checking it.")
    if event == "validate.fail":
        # The interesting half of the wait: a rejected surface is why a
        # composition takes three attempts instead of one.
        n, errors = f.get("attempt"), f.get("errors")
        return (f"Attempt {n} did not pass the checks ({errors} problem"
                f"{'' if errors == '1' else 's'}) — composing again."
                if n and errors else "That attempt did not pass the checks.")
    if event == "validate.ok":
        comps = f.get("components")
        return (f"The layout passed, with {comps} components."
                if comps else "The layout passed its checks.")
    if event.endswith(".error") or event == "tool.error":
        detail = (f.get("detail") or f.get("type") or "").strip()
        return f"The composer hit an error{f': {detail}' if detail else ''}."
    # tool.call / tool.result / provider byte counts / correlation ids: the
    # composer talking to its own developer.
    return None
