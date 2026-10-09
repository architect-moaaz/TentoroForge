"""Compiling is not starting, and the gate has to know the difference.

MEASURED. A generated app with two files resolving to "/" — the scaffold's
landing page inside a route group, and the optional catch-all — built clean:
`next build`, exit 0, full route listing. `next dev` refused:

    You cannot define a route with the same specificity as a optional
    catch-all route ("/" and "/[[...slug]]")

Every node had completed, the projection was correct, and the first person to
learn the application was broken was the person running it. So the build gate
was never going to catch this, and no stricter version of a BUILD check will:
the fault does not exist at build time.

SHAPE-AGNOSTIC, WHICH IS THE OTHER HALF. A gate saying "the root must
redirect" or "something must serve /" would refuse a single-page tool for
correctly being its own landing page. What every application owes is the same
regardless of shape: it starts, and its way in is served. The way in comes
from the Blueprint.
"""
import pytest

from services.blueprint.projection import _entry_route


def test_the_way_in_is_read_from_the_blueprint_not_assumed():
    """A calculator IS the root; a master-data app forwards to its entry."""
    calculator = {"pages": [{"id": "P1", "route": "/", "pattern": "tool",
                             "entry": True}]}
    assert _entry_route(calculator) == ""

    master_data = {"pages": [{"id": "P1", "route": "/add-data", "entry": True},
                             {"id": "P2", "route": "/master-data"}]}
    assert _entry_route(master_data) == "/add-data"


def test_a_single_page_app_is_never_sent_somewhere_else():
    """The case the redirect would break. An app whose only page is the root
    has nowhere to forward to, and must not try."""
    for pattern in ("tool", "dashboard", "form"):
        doc = {"pages": [{"id": "P1", "route": "/", "pattern": pattern}]}
        assert _entry_route(doc) == "", pattern


def test_the_entry_flag_outranks_navigation_order():
    doc = {"pages": [{"id": "P1", "route": "/a"},
                     {"id": "P2", "route": "/b", "entry": True}],
           "navigation": {"tree": [{"page": "P1"}, {"page": "P2"}]}}
    assert _entry_route(doc) == "/b"


def test_navigation_answers_when_nothing_is_flagged():
    doc = {"pages": [{"id": "P1", "route": "/a"}, {"id": "P2", "route": "/b"}],
           "navigation": {"tree": [{"page": "P2"}, {"page": "P1"}]}}
    assert _entry_route(doc) == "/b"


def test_a_retired_page_is_not_the_way_in():
    doc = {"pages": [{"id": "P1", "route": "/gone", "entry": True,
                      "status": "DEPRECATED"},
                     {"id": "P2", "route": "/here"}]}
    assert _entry_route(doc) == "/here"


def test_an_app_with_no_pages_asks_for_nothing():
    assert _entry_route({}) == ""
    assert _entry_route({"pages": []}) == ""


def test_the_boot_check_reports_the_servers_own_words():
    """A failure has to name the cause, not the symptom. The route collision
    is reported in Next's wording, because that is what a person searches."""
    from services.blueprint.assembly import _last_error

    output = (
        " ✓ Starting...\n"
        "[Error: You cannot define a route with the same specificity as a "
        "optional catch-all route (\"/\" and \"/[[...slug]]\").]\n"
    )
    said = _last_error(output)
    assert "same specificity" in said
    assert "Starting" not in said


def test_a_silent_death_still_says_something():
    from services.blueprint.assembly import _last_error

    assert _last_error("") == "no output"
    assert _last_error("just a line\n") == "just a line"


def test_any_answer_counts_as_started():
    """A 500 from an unreachable database and a 307 to a sign-in both mean the
    server routed. This gate checks booting, not behaviour — and must not need
    a database to run."""
    import inspect

    from services.blueprint.assembly import verify_boot

    src = inspect.getsource(verify_boot)
    assert "HTTPError" in src, "a 4xx/5xx must count as served"
    assert "status = exc.code" in src


def test_the_whole_process_tree_is_ended_not_just_npm():
    """A RUN WENT SILENT AFTER A CLEAN BUILD BECAUSE OF THIS.

    `npm run dev` spawns `next dev`, which spawns `next-server`, and all of
    them inherit the pipe this reads. Terminating npm alone leaves the
    grandchildren running and HOLDING THE PIPE OPEN, so a read waits for an
    EOF that cannot come — the build node blocked for ever with no CPU, no
    subprocess of its own to see, and nothing written to the ledger.

    Its own session, killed as a group, and every read bounded.
    """
    import inspect

    from services.blueprint.assembly import verify_boot

    src = inspect.getsource(verify_boot)
    assert "start_new_session=True" in src
    assert "killpg" in src
    # NO UNBOUNDED READ ANYWHERE. Every `communicate` carries a timeout, and
    # the bare `proc.stdout.read()` that could wait for an EOF a surviving
    # grandchild would never send is gone.
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert "proc.stdout.read()" not in code, (
        "reading to EOF waits for a grandchild that may never close the pipe")
    for line in code.splitlines():
        if ".communicate(" in line:
            assert "timeout" in line, line


def test_the_tree_is_ended_even_when_npm_has_already_exited():
    """`poll()` reports on npm, and npm exiting says nothing about the server
    it spawned — which outlives it, on a port, holding the pipe."""
    import inspect

    from services.blueprint.assembly import verify_boot

    src = inspect.getsource(verify_boot)
    tail = src[src.index("finally:"):]
    assert "_kill_tree()" in tail
    assert "if proc.poll() is None" not in tail, (
        "the cleanup must not be conditional on npm still running")


def test_the_first_request_is_given_the_time_a_compile_takes():
    """Lifestyle App (forge-v3, 2026-10-09) listened, then its first page —
    compiled on demand by `next dev` on a host building two other apps — took
    longer than 60 s, and a working app's build ended "did not answer: timed
    out". The first request gets a compile's time and one more try while the
    process lives; a refusal or a dead process still fails at once."""
    import inspect

    from services.blueprint import assembly

    assert assembly.FIRST_COMPILE_S >= 180
    src = inspect.getsource(assembly.verify_boot)
    assert "timeout=FIRST_COMPILE_S" in src and "timeout=60)" not in src
    assert "attempt == 1 and timed_out and proc.poll() is None" in src


def test_an_install_that_was_cut_off_is_thrown_away_not_built_on(tmp_path):
    """TStyle (forge-v3, 2026-10-09): the install was killed mid-write, the
    Next compiler was 62,976 bytes of 143 MB, the next install moved on over
    it and `next build` died with a bus error."""
    from services.blueprint.assembly import INSTALLED_MARK, _clear_unfinished_install, _mark_install_finished

    nm = tmp_path / "node_modules" / "@next" / "swc"
    nm.mkdir(parents=True)
    (nm / "next-swc.node").write_bytes(b"x" * 10)
    assert _clear_unfinished_install(tmp_path) and not (tmp_path / "node_modules").exists()
    nm.mkdir(parents=True)
    _mark_install_finished(tmp_path)
    assert (tmp_path / "node_modules" / INSTALLED_MARK).exists()
    assert not _clear_unfinished_install(tmp_path), "a finished install is kept"
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "node_modules").symlink_to(tmp_path / "node_modules")
    (tmp_path / "node_modules" / INSTALLED_MARK).unlink()
    assert not _clear_unfinished_install(linked), "a linked tree is never removed"


def test_a_lockfile_npm_cannot_read_is_written_again(tmp_path):
    """TStyle (forge-v3, 2026-10-09): a cut-off install left 28 packages in
    the lockfile with no version, and every install after it died on
    "Invalid Version" — whether or not `node_modules` was still there."""
    import json
    from services.blueprint.assembly import _drop_unreadable_lockfile

    lock = tmp_path / "package-lock.json"
    assert not _drop_unreadable_lockfile(tmp_path), "no lockfile, nothing to do"
    whole = {"packages": {"": {"name": "app"}, "vendor/@forge/schema": {},
                          "node_modules/next": {"version": "15.5.15"},
                          "node_modules/@tentoroforge/engine": {"resolved": "vendor/@tentoroforge/engine", "link": True}}}
    lock.write_text(json.dumps(whole))
    assert not _drop_unreadable_lockfile(tmp_path) and lock.exists(), "a whole lockfile is kept"
    whole["packages"]["node_modules/braces"] = {}
    lock.write_text(json.dumps(whole))
    assert _drop_unreadable_lockfile(tmp_path) and not lock.exists()
    lock.write_text('{"packages": {"node_modules/next": {"vers')
    assert _drop_unreadable_lockfile(tmp_path) and not lock.exists(), "a lockfile cut off mid-JSON too"


def test_a_server_that_will_not_start_says_so(tmp_path, monkeypatch):
    """The slot was given back twice when the dev server did not start, and
    the second time raised AttributeError over the reason (TStyle, 2026-10-09)."""
    from services import dev_servers
    from services.blueprint import page_review

    released = []

    class Slot:
        def acquire(self):
            pass

        def release(self):
            released.append(1)

    monkeypatch.setattr(dev_servers, "TrialSlot", Slot)
    app = page_review.RunningApp(tmp_path)

    def will_not_start():
        app.__exit__(None, None, None)
        raise page_review.ReviewUnavailable("the dev server did not start within 180s")

    monkeypatch.setattr(app, "_enter", will_not_start)
    monkeypatch.setattr(app, "_stop", lambda: None)
    with pytest.raises(page_review.ReviewUnavailable, match="did not start"):
        app.__enter__()
    assert released == [1]
