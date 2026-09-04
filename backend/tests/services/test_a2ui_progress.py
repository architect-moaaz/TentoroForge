"""A2UI's account of its own work reaches the person waiting on it.

The composer has always reported its phases — `tools/a2ui-mcp/tracing.py`
writes a line per attempt, per model call, per rejected surface. It writes them
to stderr, because an MCP stdio server speaks the protocol on stdout and a
stray print corrupts the session, and the parent discarded that stream.

tracing.py's own comment says so: "which the parent usually swallows". So the
minute a composition takes was never silent; nobody was reading.
"""
from __future__ import annotations

from services.a2ui_progress import phrase


def test_the_phases_that_explain_the_wait_are_said():
    assert phrase("[a3f1] attempt.start     n=1 of=3") == (
        "Composing the layout — attempt 1 of 3.")
    assert phrase("[a3f1] provider.request  kimi/kimi-latest images=1") == (
        "Asking the composition model for a layout.")
    assert phrase("[a3f1] provider.response 8.2s in=11k out=7k") == (
        "The composer answered after 8.2s; checking it.")
    assert phrase("[a3f1] validate.ok       attempt=2 components=35") == (
        "The layout passed, with 35 components.")


def test_a_rejection_is_the_interesting_half_of_the_wait():
    """A surface that fails its checks is why a composition takes three
    attempts instead of one. Without it the wait has no explanation."""
    assert phrase("[a3f1] validate.fail     attempt=1 errors=3") == (
        "Attempt 1 did not pass the checks (3 problems) — composing again.")
    assert "(1 problem)" in phrase("[a3f1] validate.fail attempt=2 errors=1")


def test_the_developer_half_is_left_unsaid():
    """Byte counts, correlation ids and the tool-call bookends are the
    composer talking to its own developer. The user is waiting on one
    question — is it working, and how far has it got."""
    for line in ("[a3f1] tool.call    generate_a2ui_surface catalog=plc",
                 "[a3f1] tool.result  ok 41.5s",
                 "not a tracing line at all",
                 ""):
        assert phrase(line) is None


def test_an_error_is_reported_rather_than_swallowed():
    said = phrase("[a3f1] tool.error   type=RuntimeError detail=no_catalog")
    assert said and "error" in said and "no_catalog" in said


def test_the_pump_gives_the_child_a_real_file_descriptor():
    """`stdio_client` hands `errlog` to `anyio.open_process(stderr=...)` and
    the OS wires the child to it, so a file-like object with a `write` method
    is not enough — it needs a fileno."""
    from services.a2ui_authority import _stderr_pump

    said: list[str] = []
    write_end, pump, close = _stderr_pump(said.append)
    try:
        assert isinstance(write_end.fileno(), int)
        pump.start()
        write_end.write("[a3f1] validate.fail attempt=1 errors=2\n")
        write_end.flush()
    finally:
        close()
        pump.join(5)
    assert said == ["Attempt 1 did not pass the checks (2 problems) — "
                    "composing again."]


def test_the_console_keeps_what_it_had(capsys):
    """Redirecting the child's stderr must not cost the developer the output
    they were reading before."""
    from services.a2ui_authority import _stderr_pump

    write_end, pump, close = _stderr_pump(None)
    try:
        pump.start()
        write_end.write("[a3f1] provider.request kimi\n")
        write_end.flush()
    finally:
        close()
        pump.join(5)
    assert "provider.request" in capsys.readouterr().err


def test_the_composition_seam_is_bound_with_the_sink():
    """A2UI is the longest stretch of a compose turn and makes no model call
    of ours, so the router's sink alone would leave it silent."""
    import inspect

    from services.blueprint import executors

    assert "progress=reasoning" in inspect.getsource(executors.make_executor)


def test_an_injected_provider_keeps_its_two_argument_seam():
    """Every test supplies `lambda requirement, domain: {...}`."""
    import inspect

    from services import a2ui_authority

    src = inspect.getsource(a2ui_authority.compose_page_via_a2ui)
    # Bound, not passed positionally — however many keywords it grows. Pinned
    # to the property rather than the spelling: this failed when the partial
    # gained `workflows=`, for a change that was entirely correct.
    assert "partial(" in src and "_mcp_surface" in src
    import inspect as _i
    params = list(_i.signature(a2ui_authority._mcp_surface).parameters)
    assert params[:2] == ["requirement", "domain_context"], (
        "the injected seam is called with two positional arguments; every test "
        "supplies `lambda requirement, domain: {...}`")
