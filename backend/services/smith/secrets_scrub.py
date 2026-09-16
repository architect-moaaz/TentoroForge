"""Credentials taken out of a message before it is written down.

§42 names chat history as the first place a raw credential must not come to
rest, and `understand_ask._env_name_only` already drops one out of the FIELD
the model returns, so a token never reaches the Blueprint or a reply. The
message itself was written to the conversation table exactly as typed: paste a
Figma token, and it is on disk, and it comes back through the history endpoint
to every later turn. The user-facing catalogue says a pasted key "is thrown
away before the message is saved". This is what makes that true.

ANCHORED, NOT CLEVER. Every pattern here starts from a prefix a provider
issues or a word the person typed themselves ("password:"). A general
high-entropy rule would redact ids, hashes and the odd long word, and a
conversation with holes punched in it is its own defect — the cost of missing
one unusual token is that it is stored, which is where we are today, while the
cost of a false positive is a message the user can no longer read back.
"""

from __future__ import annotations

import re

#: What replaces a credential, in the words a reader needs: it explains the
#: hole and says what to do instead.
MASK = "[secret removed — give me the NAME of the variable instead]"

#: (pattern, what it is) — the second half is documentation, not behaviour.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfigd_[A-Za-z0-9_-]{8,}"), "Figma personal access token"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}"), "GitHub fine-grained token"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}"), "Stripe key"),
    (re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}"), "OpenAI / Anthropic key"),
    (re.compile(r"\bSG\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "SendGrid key"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}"), "AWS access key id"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "Google API key"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "JSON web token"),
    (re.compile(r"\b(?:AC|SK)[0-9a-f]{30,}"), "Twilio sid or key"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"), "bearer token"),
    (re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----"),
     "private key block"),
)

#: "password: hunter2", "API_KEY=abc123" — the person labelled it themselves,
#: which is a better signal than any shape. The LABEL is kept: what Smith needs
#: to read back is that a password was given, not the password.
_LABELLED = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|client[_-]?secret|token|access[_-]?token|"
    r"api[_-]?key|apikey|private[_-]?key)\b(\s*(?:[:=]|is)\s*)"
    r"(?![A-Z_]{3,}\b)"          # "API_KEY = SENDGRID_API_KEY" names a variable
    r"(\"|')?([^\s\"']{8,})\1?"
)


def scrub(text: str) -> str:
    """`text` with anything that looks like a credential replaced.

    Idempotent, and safe on text that contains none: the common case returns
    the string it was given.
    """
    out = str(text or "")
    if not out:
        return out
    for pattern, _what in _PATTERNS:
        out = pattern.sub(MASK, out)
    out = _LABELLED.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", out)
    return out


def carries_secret(text: str) -> bool:
    """Whether scrubbing `text` would change it."""
    return scrub(text) != str(text or "")


__all__ = ["scrub", "carries_secret", "MASK"]
