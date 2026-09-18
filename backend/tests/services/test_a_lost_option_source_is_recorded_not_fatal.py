"""A Form field naming an option source the page cannot resolve.

UAT, 2026-09-18: the first page to reach this branch raised AttributeError
and took the whole build down — twice in one morning, on two apps. The branch
(73b29f2) called `binder._record(...)` with an argument naming `c`, which does
not exist in that scope, on a binder that on this path is `_SourceBook`, which
had no `_record`. Neither exception is a refusal the orchestrator catches.
"""
import ast
import inspect

from services import a2ui_to_forge
from services.a2ui_to_forge import _rewrite_option_sources
from services.blueprint.layout_vocabulary import _SourceBook


def _form_with_a_lost_source():
    return {"type": "Form", "id": "packageForm", "props": {"fields": [
        {"name": "testIds", "label": "Tests",
         "optionsFrom": {"entity": "NoSuchEntity", "valueField": "id"}}]}}


def test_the_layout_pass_records_the_loss_instead_of_crashing():
    book = _SourceBook({"entities": []}, [])
    root = _form_with_a_lost_source()
    _rewrite_option_sources(root, book, {"entities": []})
    assert book.recorded, "the lost source is said, not dropped"
    assert "packageForm" in book.recorded[0], "and says where"


def test_the_stand_in_has_every_binder_method_the_shared_path_calls():
    """`_SourceBook` impersonates the translator's `_Binder` for one shared
    function. A method call it lacks is found here, not on a customer's build.
    Only direct `binder.<name>` access counts — a `getattr(binder, ...)` read
    is already written to tolerate an absent attribute."""
    called = set()
    for fn in (a2ui_to_forge._rewrite_option_sources, a2ui_to_forge.option_source):
        for n in ast.walk(ast.parse(inspect.getsource(fn).strip() if False else
                                    __import__("textwrap").dedent(inspect.getsource(fn)))):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "binder"):
                called.add(n.attr)
    book = _SourceBook({"entities": []}, [])
    missing = sorted(a for a in called if not hasattr(book, a))
    assert not missing, f"_SourceBook lacks what the shared path calls: {missing}"
