"""A decision id is data, not a route — it must never affect routing.

Decision ids are ``kind:scope:identity`` and the scope routinely embeds an
app route, so real ids look like::

    form_submit:file-documents/new-json:form-submit
                             ↑ a slash

The old endpoint took the id as a path parameter. Starlette's ``{param}``
converter matches a single segment and never ``/``, and the ASGI server
percent-DECODES before routing — so the frontend's correct
``encodeURIComponent`` produced ``%2F``, which decoded back to ``/``, added
a path segment, and matched no route. FastAPI answered its default
``{"detail": "Not Found"}``, which the chat panel rendered verbatim as a red
"Not Found" banner with no clue what was missing.

Flat-route decisions worked, so the bug looked intermittent.

`{decision_id:path}` is NOT the fix — the ``path`` converter is greedy and
swallows the trailing ``/confirm`` too. The id moves into the body instead,
which makes the whole class impossible rather than fixing one instance.
"""
from __future__ import annotations

import pytest

from routers.open_decisions import ConfirmBody, _split_binding_key


class TestSlashIdsRoundTrip:
    """The exact id from the live 404, plus its neighbours."""

    def test_the_live_failing_id_parses(self):
        parts = _split_binding_key("form_submit:file-documents/new-json:form-submit")
        assert parts is not None
        kind, scope, identity = parts
        assert kind == "form_submit"
        assert scope == "file-documents/new-json", "the slash must survive intact"
        assert identity == "form-submit"

    def test_scope_may_contain_both_a_slash_and_a_colon(self):
        kind, scope, identity = _split_binding_key("binding:page:/docs/new:table")
        assert (kind, scope, identity) == ("binding", "page:/docs/new", "table")

    def test_flat_id_still_parses(self):
        assert _split_binding_key("form_submit:members:form-submit") == (
            "form_submit", "members", "form-submit")

    def test_too_few_segments_is_rejected(self):
        assert _split_binding_key("nope") is None
        assert _split_binding_key("kind:only") is None


class TestConfirmBody:
    """decision_id now rides in the body, so no id can break routing."""

    def test_carries_both_fields(self):
        b = ConfirmBody(decision_id="form_submit:file-documents/new-json:form-submit",
                        target="CreateDocumentWorkflow")
        assert "/" in b.decision_id
        assert b.target == "CreateDocumentWorkflow"

    def test_decision_id_is_required(self):
        with pytest.raises(Exception):
            ConfirmBody(target="x")

    def test_target_is_required(self):
        with pytest.raises(Exception):
            ConfirmBody(decision_id="a:b:c")

    def test_empty_decision_id_is_rejected(self):
        """An empty id would 404 on lookup with a confusing message; reject
        it at the schema boundary where the error names the field."""
        with pytest.raises(Exception):
            ConfirmBody(decision_id="", target="x")


class TestRouteShape:
    """The confirm route must expose no id path-parameter at all."""

    def test_confirm_route_has_no_decision_id_in_the_path(self):
        from routers.open_decisions import router
        paths = [r.path for r in router.routes if r.path.endswith("/confirm")]
        assert paths, "the confirm route must exist"
        for p in paths:
            assert "{decision_id}" not in p, (
                f"{p} still takes the id as a path param — slash ids will 404")
