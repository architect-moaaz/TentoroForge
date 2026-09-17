"""Chat restore ordering + control-signal filtering (Task 1 / RC-2.1, RC-2.3).

created_at is the transaction timestamp, identical for rows written together, so
the transcript reordered on every reload. The monotonic `seq` identity fixes the
order; control-signal rows ([APPROVE_PLAN] …) must not resurface as chat bubbles.
"""
from routers.projects import _is_control_signal


def test_control_signals_are_filtered():
    for s in (
        "[APPROVE_PLAN]", "[APPROVE_DISCOVERY]", "[SELECT_TEMPLATE:abc123]",
        "[BEGIN_QUEST]", "[GENERATION_PROFILE:fast]", "  [APPROVE]  ",
        # The REAL formats the UI sends — a signal with a JSON payload. The old
        # filter required the string to END with "]", so these leaked into the
        # transcript as raw bubbles (reproduced live on the invoice project).
        '[APPROVE_DISCOVERY] {"mode":"fast"}',
        '[APPROVE_DISCOVERY] {"mode":"fast","domain":"Invoicing"}',
        '[SELECT_TEMPLATE:tpl_9] {"palette":"teal"}',
        "[APPLY_FIX]", "[SEED_DATA]", "[VALIDATE_REPAIR]", "[DONE]",
    ):
        assert _is_control_signal(s), f"{s!r} should be treated as a control signal"


def test_real_user_messages_are_kept():
    for s in (
        "add a login page", "[TODO] my list app", "remove the sidebar",
        "make it blue [please]", "", "I want an app for [my team]",
        "[URGENT] please fix the checkout",  # real msg, not a known signal
    ):
        assert not _is_control_signal(s), f"{s!r} is a real message, must be kept"


def test_conversation_seq_column_is_crash_proof():
    """REGRESSION GUARD for the catastrophic seq-NULL 500.

    The seq column MUST carry a server_default on the MODEL (so SQLAlchemy omits
    it from INSERT and the Postgres sequence fills it) and MUST be nullable (so a
    stray NULL can never violate a constraint). Without the server_default the
    ORM sent seq=NULL and EVERY chat/Smith/generation write 500'd. The sqlite
    test harness can't reproduce the Postgres sequence, so this asserts the model
    CONTRACT directly.

    THE HARNESS TAKES THE DEFAULT AWAY, so the live column is not the whole
    answer. `conftest._strip_pg_only_server_defaults` removes `nextval(...)`
    from the real model metadata — SQLite cannot compile it — the moment any
    test takes the `test_db` fixture. This guard therefore read None and failed
    in a full run while passing on its own, which reads as the model having
    lost its default rather than the harness having taken it. The strip records
    what it removed; either source proves the model declared one.
    """
    from tests.conftest import stripped_server_default

    from models.project import Conversation
    col = Conversation.__table__.c.seq
    declared = col.server_default or stripped_server_default("conversations", "seq")
    assert declared is not None, (
        "Conversation.seq needs a server_default (nextval) or the ORM sends "
        "seq=NULL on every insert and all conversation writes 500"
    )
    # And it is the SEQUENCE, not merely something non-None: a constant
    # default would hand every row the same number and lose the ordering this
    # column exists for.
    assert "nextval" in str(getattr(declared, "arg", declared)).lower(), declared
    assert col.nullable is True, "Conversation.seq must be nullable so a stray NULL can't 500 a write"
