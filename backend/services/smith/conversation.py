"""Layer 1 — the active conversation, made durable (PRD §8, §14).

§8's first instruction is a warning: *"Smith must not rely exclusively on
conversation history."* It is easy to read that as "the transcript doesn't
matter". It says the opposite — the transcript is one of four layers, and a
layer nothing can address is not a layer.

§14 is what forces the shape. A requirement retains its origin::

    evidence:
      - type: conversation
        message: MSG-052

For that citation to mean anything two months later, the message it names must
still exist and still be MSG-052. So the transcript is append-only, its ids are
monotonic, and nothing rewrites history.

Why this is not a Blueprint section
-----------------------------------
Two reasons, and the second is the real one.

§91 snapshots the entire Blueprint per version. A transcript living inside it
would be copied into every snapshot — a two-hundred-turn conversation
duplicated across forty versions, and every ``blueprintDiff`` (§92) polluted
with message appends that changed no artifact.

More importantly, §115 puts the chain at::

    Approved User Intent  →  Living Blueprint  →  Generated Implementation

The conversation is the *first* box. It is upstream of the Blueprint, not part
of it. Filing it inside the thing it feeds would collapse a distinction the
whole architecture rests on.

So it sits beside the Blueprint under the same application root, at
``.forge/smith/conversation.jsonl``, and the Blueprint cites into it.

On MSG ids
----------
They come from this store's own sequence, not from :class:`IdAllocator`. Adding
``MSG`` to ``ID_PREFIXES`` would make ``is_valid_id("MSG-001")`` return true
while ``BlueprintService.find`` has no section to resolve it in — a claim the
rest of the system would then act on. A message is not a Blueprint artifact; it
is the evidence one was created.
"""
from __future__ import annotations

import errno
import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

try:  # POSIX only; degrades to unlocked append elsewhere.
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

#: Who produced a message. ``system`` covers platform events the user did not
#: type but that a later decision may legitimately cite — a verification
#: failure, a build result.
ROLES: tuple[str, ...] = ("user", "smith", "system")

MSG_RE = re.compile(r"^MSG-(\d{3,})$")
_PAD = 3


class MalformedTranscript(ValueError):
    """The transcript on disk is not readable as an append-only message log."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Message:
    """One turn. Immutable once written — §14 citations depend on it."""

    id: str
    role: str
    text: str
    at: str = ""
    #: Blueprint artifacts this message is about. For a user turn these are the
    #: anchors a preview selection supplied (§69); for a Smith turn they are
    #: what the reply concerned. Either way it is what makes the transcript
    #: searchable by artifact rather than only by word.
    refs: tuple[str, ...] = ()
    #: Free-form provenance — a preview selection, an uploaded document.
    #: Deliberately untyped: §14 admits six evidence sources and this store
    #: should not need changing to carry a seventh.
    context: dict = field(default_factory=dict)

    def as_evidence(self) -> dict:
        """This message in the shape ``requirements[].evidence[]`` expects (§14)."""
        return {"type": "conversation", "message": self.id, "source": self.role}


class Conversation:
    """Append-only message log for one application.

    Reads are cheap and writes are rare, so there is no in-memory cache to go
    stale: every append re-reads under an exclusive lock. A conversation is
    hundreds of lines, not millions.
    """

    def __init__(self, output_dir: str | Path):
        self.output_dir = str(output_dir)

    # -- paths --------------------------------------------------------------

    @property
    def root(self) -> Path:
        return Path(self.output_dir) / ".forge" / "smith"

    @property
    def path(self) -> Path:
        return self.root / "conversation.jsonl"

    # -- reading ------------------------------------------------------------

    def messages(self) -> list[Message]:
        """Every message, oldest first."""
        if not self.path.exists():
            return []
        out: list[Message] = []
        for lineno, line in enumerate(self.path.read_text("utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                # Never skip past it. A transcript with a hole in it would let
                # a §14 citation resolve to the wrong message, which is worse
                # than failing to resolve at all.
                raise MalformedTranscript(
                    f"{self.path}:{lineno} is not valid JSON: {exc}"
                ) from exc
            out.append(Message(
                id=raw.get("id", ""),
                role=raw.get("role", ""),
                text=raw.get("text", ""),
                at=raw.get("at", ""),
                refs=tuple(raw.get("refs") or ()),
                context=raw.get("context") or {},
            ))
        return out

    def __iter__(self) -> Iterator[Message]:
        return iter(self.messages())

    def __len__(self) -> int:
        return len(self.messages())

    def get(self, message_id: str) -> Message:
        """Resolve a §14 citation. Raises rather than returning ``None``: a
        Blueprint pointing at a message that is not there is a defect to
        surface, not a value to branch on."""
        for m in self.messages():
            if m.id == message_id:
                return m
        raise KeyError(f"no such message: {message_id!r}")

    def recent(self, limit: int = 10) -> list[Message]:
        """§8 Layer 1 — *"current request and immediate conversation"*.

        Deliberately a small window. The reason §8 lists four layers is that
        the transcript is the *worst* place to look for what the application
        is; anything older than the immediate exchange should be answered from
        the Blueprint, which knows it as structure rather than as prose.
        """
        return self.messages()[-limit:] if limit > 0 else []

    def about(self, artifact_id: str) -> list[Message]:
        """Messages that concern one artifact — the reverse of §14's citation."""
        return [m for m in self.messages() if artifact_id in m.refs]

    # -- writing ------------------------------------------------------------

    def append(
        self, role: str, text: str, *,
        refs: tuple[str, ...] | list[str] = (),
        context: dict | None = None,
    ) -> Message:
        """Add one message and return it, with its allocated id.

        Held under an exclusive file lock for the same reason
        :class:`IdAllocator` is: two writers that both read "last was MSG-007"
        both mint MSG-008, and a §14 citation then names two different things.
        """
        if role not in ROLES:
            raise ValueError(f"{role!r} is not a conversation role; expected one of {ROLES}")

        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / "conversation.lock"
        fh = open(lock_path, "a+")
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            message = Message(
                id=self._next_id(),
                role=role,
                text=text,
                at=_now(),
                refs=tuple(refs),
                context=dict(context or {}),
            )
            with open(self.path, "a", encoding="utf-8") as out:
                payload = asdict(message)
                payload["refs"] = list(message.refs)
                out.write(json.dumps(payload, sort_keys=True) + "\n")
                out.flush()
                os.fsync(out.fileno())
            return message
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError as exc:  # pragma: no cover
                if exc.errno != errno.EBADF:
                    raise
            fh.close()

    def _next_id(self) -> str:
        """Highest id seen plus one — never a line count.

        The two agree today. They would stop agreeing the moment a line is
        unreadable or a message is filtered on read, and the failure would be
        silent: a reused id pointing at the wrong turn.
        """
        highest = 0
        for m in self.messages():
            match = MSG_RE.match(m.id or "")
            if match:
                highest = max(highest, int(match.group(1)))
        return f"MSG-{highest + 1:0{_PAD}d}"
