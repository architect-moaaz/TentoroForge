"""An open tab costs nothing while nothing changes (DITANS Test, 2026-11-24).

5.85 GB left DITANS's Test database in six days and Neon cut it off. The
live-refresh stream kept its watermark as a JS Date: microseconds cut to
milliseconds, so `created_at > since` matched the newest event again on every
2.5 s poll, and on a machine east of UTC the zoneless `created_at` read into a
Date jumped hours back. Every stream end (the platform caps it) reloaded the
whole page "to cover missed events", hidden tabs too; a hidden tab kept its
stream polling the database and the bell asking twice a minute.

Now the watermark is the database's own text, each frame carries it as the
SSE id, a reconnect carries on from it, and a hidden tab holds no stream and
asks nothing.
"""
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
STREAM = TEMPLATES / "runtime" / "api-events-stream" / "route.ts"
LIVE = TEMPLATES / "app-foundation" / "src" / "lib" / "LiveRefresh.tsx"
BELL = TEMPLATES / "app-foundation" / "src" / "app" / "(dashboard)" / "NotificationBell.tsx"


def _code(path: Path) -> str:
    """The file without its comments, so a rule is read from what runs."""
    out = []
    for line in path.read_text("utf-8").splitlines():
        t = line.strip()
        if t.startswith(("//", "*", "/*")):
            continue
        out.append(line)
    return "\n".join(out)


def test_the_watermark_is_the_databases_own_text():
    src = _code(STREAM)
    assert "fromDbTime" not in src and "new Date()" not in src
    assert "created_at::text AS at" in src
    assert "WHERE created_at > ${since}::timestamp" in src
    assert "since = String(rows[rows.length - 1].at);" in src


def test_a_first_visit_starts_at_the_tail():
    src = _code(STREAM)
    assert "COALESCE(max(created_at), localtimestamp)::text AS at FROM forge_events" in src


def test_every_frame_carries_the_watermark_and_a_reconnect_carries_on_from_it():
    src = _code(STREAM)
    assert 'req.headers.get("last-event-id")' in src and 'searchParams.get("since")' in src
    assert "send(`id: ${since}\\ndata: ${JSON.stringify({ events })}\\n\\n`);" in src
    assert '`id: ${since}\\ndata: {"events":[]}\\n\\n`' in src
    # Only a watermark is taken from the request: it goes into the query.
    assert "WATERMARK.test(asked) ? asked : null" in src


def test_a_reconnect_does_not_reload_the_page():
    src = _code(LIVE)
    assert "hadDrop" not in src and "onopen" not in src
    assert "if (msg.lastEventId) lastId = msg.lastEventId;" in src


def test_a_hidden_tab_holds_no_stream():
    src = _code(LIVE)
    assert 'if (document.visibilityState === "hidden") close();' in src
    assert 'document.visibilityState === "hidden") return;' in src
    assert 'document.removeEventListener("visibilitychange", onVisibility);' in src


def test_a_hidden_tab_does_not_ask_for_its_notifications():
    src = _code(BELL)
    assert "setInterval(load, 30_000)" not in src
    assert 'setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, 30_000)' in src
    assert 'document.addEventListener("visibilitychange", onVisible);' in src
