"""A plan longer than the output budget is reported as cut off, not as bad JSON.

A request for a dozen workflows in one turn came back as 50,891 characters of
valid JSON ending mid-string. `interpret` reported "reply was not JSON", re-asked
once with that verdict, got the same cut-off reply, and Smith answered "I could
not turn that into a change I am confident about". The model had stopped at
`max_tokens`; the transport knew and the reader did not.
"""
import pytest

from services.blueprint.executors import ModelReply
from services.smith.turn import Context, TurnRejected, interpret


class _CutOff:
    enforces_schema = True
    calls = 0

    def __call__(self, *, system, user, schema=None):
        self.calls += 1
        return ModelReply(text='{"intent": "change", "reply": "adding the app', stop_reason="max_tokens")


def _context():
    try:
        return Context(request="add twelve workflows")
    except TypeError:
        return Context.__new__(Context)


def test_the_rejection_names_the_output_limit_and_does_not_re_ask():
    client = _CutOff()
    with pytest.raises(TurnRejected) as err:
        interpret(client, _context(), {"requirements": [], "pages": []}, retries=1)
    assert "cut off at the output limit" in str(err.value)
    assert "part of it at a time" in str(err.value)
    assert client.calls == 1


def test_a_reply_that_ended_normally_is_read_as_before():
    class _Bad:
        enforces_schema = True

        def __call__(self, *, system, user, schema=None):
            return ModelReply(text="not json at all", stop_reason="end_turn")
    with pytest.raises(TurnRejected) as err:
        interpret(_Bad(), _context(), {"requirements": [], "pages": []}, retries=0)
    assert "not JSON" in str(err.value)
