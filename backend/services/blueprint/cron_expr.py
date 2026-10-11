"""What the engine's clock can read, as the author's check needs it.

A mirror of `templates/runtime/events/cron.ts` (five fields: minute, hour,
day of month, month, day of week; `*`, `*/n`, `a`, `a-b`, `a-b/n`, lists)
and of `parseDurationMs` in `workflows/engine.ts` (ISO-8601 durations and
words). A validator may refuse only what the runtime would refuse, so both
sides read the same grammar.
"""
from __future__ import annotations

import re

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _field_ok(field: str, lo: int, hi: int) -> bool:
    for item in field.split(","):
        item = item.strip()
        if not item:
            return False
        if item == "*":
            continue
        m = re.fullmatch(r"\*/(\d+)", item)
        if m:
            if int(m.group(1)) < 1:
                return False
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?(?:/(\d+))?", item)
        if not m:
            return False
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) is not None else a
        step = int(m.group(3)) if m.group(3) is not None else 1
        if not (lo <= a <= hi and lo <= b <= hi and a <= b and step >= 1):
            return False
    return True


def is_valid_cron(expr: str | None) -> bool:
    """Five fields the engine's matcher reads."""
    parts = str(expr or "").strip().split()
    if len(parts) != 5:
        return False
    return all(_field_ok(p, lo, hi) for p, (lo, hi) in zip(parts, _RANGES))


_UNITS = {"s": 1000, "sec": 1000, "second": 1000, "m": 60_000, "min": 60_000, "minute": 60_000,
          "h": 3_600_000, "hr": 3_600_000, "hour": 3_600_000, "d": 86_400_000, "day": 86_400_000,
          "w": 604_800_000, "week": 604_800_000}


def parse_duration_ms(value: object) -> int:
    """How long a `wait` waits, in milliseconds; 0 when unreadable."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value or "").strip()
    if not text:
        return 0
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return max(0, int(float(text)))
    iso = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", text, re.I)
    if iso:
        w, d, h, m, s = (int(g or 0) for g in iso.groups())
        return ((((w * 7 + d) * 24 + h) * 60 + m) * 60 + s) * 1000
    total, matched = 0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(weeks?|w|days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b",
                                text, re.I):
        u = unit.lower().rstrip("s")
        ms = _UNITS.get(u) or _UNITS.get(u.rstrip("e")) or 0
        if ms:
            total += int(float(num) * ms)
            matched = True
    return total if matched else 0


def tick_minutes(crons: list[str], default: int = 15) -> int:
    """How often the app's tick must run so every schedule fires on time:
    the finest `*/n` minute step, every minute for `*`, else the default."""
    finest = default
    for cron in crons:
        parts = str(cron or "").split()
        if len(parts) != 5:
            continue
        minute = parts[0]
        if minute == "*":
            finest = 1
        else:
            m = re.fullmatch(r"\*/(\d+)", minute)
            if m:
                finest = min(finest, max(1, int(m.group(1))))
    return max(1, min(finest, default))


__all__ = ["is_valid_cron", "parse_duration_ms", "tick_minutes"]
