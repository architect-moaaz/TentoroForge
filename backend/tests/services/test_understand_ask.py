"""§16 — asking is a first-class answer."""

from services.smith.understand_ask import understand_ask

CTX = "pages: /plants (Plants list), /plants/new (Add Plant)"


def _says(text):
    return lambda _prompt: text


def test_a_clear_request_names_its_target():
    out = understand_ask(
        "Rename the Add plant button to New plant", CTX,
        provider=_says('{"clarification_needed":"","target_file":"/plants",'
                       '"element_label":"Add plant"}'),
    )
    assert out["clarification_needed"] == ""
    assert out["target_file"] == "/plants"
    assert out["element_label"] == "Add plant"


def test_an_underspecified_request_asks_instead_of_guessing():
    """"Make it nicer" names no screen and no element. A model pushed to
    always produce a target produces one anyway, and the turn then edits a
    file nobody chose."""
    out = understand_ask(
        "make it nicer", CTX,
        provider=_says('{"clarification_needed":"Which screen?",'
                       '"target_file":"","element_label":""}'),
    )
    assert out["clarification_needed"] == "Which screen?"
    assert out["target_file"] == ""


def test_json_wrapped_in_prose_or_fences_still_parses():
    out = understand_ask(
        "x", CTX,
        provider=_says('Sure!\n```json\n{"clarification_needed":"",'
                       '"target_file":"/plants","element_label":"Add"}\n```'),
    )
    assert out["target_file"] == "/plants"


def test_an_unreachable_model_asks_rather_than_returning_a_blank():
    """A blank understanding reads downstream as "clear enough to act on, but
    no target", and the real reason goes unrecorded."""
    def boom(_prompt):
        raise RuntimeError("no network")

    out = understand_ask("Rename it", CTX, provider=boom)
    assert out["clarification_needed"]
    assert out["target_file"] == ""


def test_unparseable_output_asks_too():
    out = understand_ask("Rename it", CTX, provider=_says("I think maybe?"))
    assert out["clarification_needed"]


def test_an_empty_message_asks_without_calling_the_model():
    def never(_prompt):
        raise AssertionError("should not be called")

    assert understand_ask("   ", CTX, provider=never)["clarification_needed"]


def test_missing_keys_normalise_to_strings():
    """`run_iteration` calls .strip() on all three."""
    out = understand_ask("x", CTX, provider=_says('{"target_file":"/plants"}'))
    assert out == {"clarification_needed": "", "target_file": "/plants",
                   "element_label": ""}
