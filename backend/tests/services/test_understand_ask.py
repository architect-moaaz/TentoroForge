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
    """`run_iteration` calls .strip() on these."""
    out = understand_ask("x", CTX, provider=_says('{"target_file":"/plants"}'))
    assert out == {"answer": "", "clarification_needed": "", "target_file": "/plants",
                   "element_label": "", "new_value": "",
                   # `run_iteration` dispatches on the verb and reads route and
                   # widgets off the same dict. An absent verb still means
                   # rename, which is what every turn used to be.
                   "verb": "", "route": "", "widgets": [],
                   "figma_url": "", "token_env": "", "treat_as": ""}


def test_a_replacement_carries_the_value_to_write():
    """`move_dispatcher` needs a literal. target_file and element_label say
    where and what; without new_value they do not say what to write."""
    out = understand_ask(
        "Rename the Add plant button to New plant", CTX,
        provider=_says('{"clarification_needed":"","target_file":"/plants",'
                       '"element_label":"Add plant","new_value":"New plant"}'),
    )
    assert out["new_value"] == "New plant"


def test_a_request_with_nothing_to_write_has_an_empty_new_value():
    """A removal is a real move and has no replacement text."""
    out = understand_ask(
        "Remove the export button", CTX,
        provider=_says('{"clarification_needed":"","target_file":"/plants",'
                       '"element_label":"Export","new_value":""}'),
    )
    assert out["new_value"] == ""
    assert out["element_label"] == "Export"


def test_every_early_return_carries_the_full_shape():
    """A partial dict would make a caller's .get("new_value") return None on
    exactly the paths that already went wrong."""
    def boom(_prompt):
        raise RuntimeError("no network")

    for out in (
        understand_ask("", CTX, provider=boom),
        understand_ask("x", CTX, provider=boom),
        understand_ask("x", CTX, provider=_says("not json")),
    ):
        assert set(out) == {"answer", "clarification_needed", "target_file",
                            "element_label", "new_value",
                            "verb", "route", "widgets",
                            # connect_figma. `token_env` is a variable NAME;
                            # the token itself is never a field Smith carries.
                            # `treat_as` is evidence vs specification (§48).
                            "figma_url", "token_env", "treat_as"}
