"""Playful, conversational chat lines for generation progress.

The pipeline otherwise streams dry `[Schema] …` log lines. These friendly one-liners
are emitted as `sse_event("message", {"text": …})` so they land as persistent
assistant chat bubbles — giving the chat a lively, Claude-Code-style narration
("Your pages are landing…" → "7 pages generated — yay!").

IMPORTANT: never prefix these with a `[Tag]` — the chat store routes `[Tag]`-prefixed
messages to the office/agent view instead of showing them as a chat bubble.
"""
from __future__ import annotations

import random

# Whimsical "starting a phase" lines. A few variants each so repeat runs feel fresh.
_START: dict[str, list[str]] = {
    "design":    ["🎨 Picking colors and vibes for your app…",
                  "🎨 Sketching the look & feel…"],
    "data":      ["🧱 Laying the data foundations…",
                  "🗄️ Designing your data models…"],
    "pages":     ["🛬 Your pages are landing…",
                  "✨ Bringing your screens to life…",
                  "📄 Painting your pages, one pixel at a time…"],
    "workflows": ["⚙️ Wiring up the behind-the-scenes logic…",
                  "🔗 Connecting the moving parts…"],
    "polish":    ["🪄 Adding the finishing touches…",
                  "🧹 Tidying everything up…"],
}

# Celebratory "phase done" lines. {n}=count, {s}=plural suffix.
_DONE: dict[str, str] = {
    "data":      "🧱 {n} data model{s} ready to go!",
    "pages":     "🎉 {n} page{s} generated successfully — yay!",
    "workflows": "⚙️ {n} workflow{s} wired up!",
}


def start(phase: str) -> str:
    """A friendly 'starting <phase>' line (empty string if the phase is unknown)."""
    opts = _START.get(phase)
    return random.choice(opts) if opts else ""


def done(phase: str, n: int) -> str:
    """A celebratory 'finished <phase>' line with a count (empty if unknown)."""
    tmpl = _DONE.get(phase)
    return tmpl.format(n=n, s="" if n == 1 else "s") if tmpl else ""


_READY = [
    "🚀 Your app is ready — go take a look!",
    "🎊 All done! Your app is live in the preview.",
    "✅ That's a wrap — your app is ready to explore!",
]


def ready() -> str:
    """The grand-finale line once the whole app has finished generating."""
    return random.choice(_READY)
