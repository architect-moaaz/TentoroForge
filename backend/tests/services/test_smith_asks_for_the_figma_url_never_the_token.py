"""Smith may ask for a Figma URL and a variable NAME. Never for the token.

§42 lists the places a raw credential must not come to rest, and `chat history`
is first::

    chat history · Blueprint · generated source · export · application logs

Smith's conversation is persisted, so a token typed into a turn is a token
written to disk in exactly the forbidden place. This repository has already
been burned by it: `FIGMA_TOKEN` is annotated in `.env` as leaked-in-chat and
was still unrotated when this was written.

`services.figma.credentials` settled the shape before Smith reached for it — a
`FigmaCredential` holds a REFERENCE, the name of an environment variable, and
the gateway resolves the secret at the moment of the call. A name is not a
secret, so it can be asked for, stored, and echoed back.

Two properties, and the second is the one that matters when a user ignores the
first: Smith asks for the name, and if a token is handed over anyway it is not
persisted.
"""
import pytest

from services.smith.understand_ask import _PROMPT, _env_name_only
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP
from services.smith_session import SmithSession


def _session(output_dir="/tmp/does-not-exist"):
    s = SmithSession.__new__(SmithSession)
    s.output_dir = output_dir
    return s


# --------------------------------------------------------------- the contract

def test_the_verb_needs_a_url_and_a_variable_name():
    assert REQUIRED_BY_VERB["connect_figma"] == {"figma_url", "token_env"}


def test_the_verb_help_says_never_the_token():
    assert "never the token" in VERB_HELP["connect_figma"].lower()


def test_the_prompt_tells_the_model_to_ask_for_a_name():
    assert "connect_figma" in _PROMPT
    assert "NAME of the environment variable" in _PROMPT


def test_the_prompt_tells_the_model_what_to_do_with_a_pasted_token():
    """The obvious reply to "I need your Figma token" is to paste one, so the
    model is told the shape of that mistake and how to answer it."""
    assert "figd_" in _PROMPT


# ------------------------------------------------------- the persistence guard

@pytest.mark.parametrize("pasted", [
    "figd_abcdefghijklmnopqrstuvwxyz0123456789",
    "  figd_shortish  ",
    "x" * 65,                     # too long to be a variable name
    "not a variable name",        # spaces
    "FIGMA-TOKEN",                # punctuation
])
def test_a_secret_shaped_value_is_never_returned_for_storage(pasted):
    """`_env_name_only` guards the field that reaches `conversation.jsonl`. A
    model that returns the token despite the prompt must not get it written."""
    assert _env_name_only(pasted) == ""


@pytest.mark.parametrize("name", ["FIGMA_TOKEN", "FIGMA_PAT", "MY_TOKEN_2"])
def test_a_real_variable_name_survives(name):
    """The guard must not be so strict that the working case is unusable."""
    assert _env_name_only(name) == name


# ------------------------------------------------------------------- the asks

def test_no_url_asks_for_the_file():
    r = _session()._connect_figma({})
    assert r.status == "asked"
    assert "figma" in r.answer.lower()


def test_no_variable_name_asks_for_the_name_and_warns():
    r = _session()._connect_figma(
        {"figma_url": "https://www.figma.com/design/aBcD1234EfGh/P?node-id=1-2"})
    assert r.status == "asked"
    assert "NAME" in r.answer
    assert "not the token itself" in r.answer


def test_the_ask_never_invites_a_token():
    """The wording is the control here: "paste your token" is the request that
    produces the leak, so no ask may read that way."""
    r = _session()._connect_figma(
        {"figma_url": "https://www.figma.com/design/aBcD1234EfGh/P"})
    lowered = r.answer.lower()
    assert "paste your token" not in lowered
    assert "paste the token" not in lowered


# ------------------------------------------------------------- URL validation

def test_a_url_that_is_not_figma_is_named_as_such():
    """Validated before the Blueprint loads, or a mistyped link is reported as
    whatever fails next — it read "could not read that Figma file:
    FileNotFoundError" for a URL that was simply not a Figma URL."""
    r = _session()._connect_figma(
        {"figma_url": "https://example.com/nope", "token_env": "FIGMA_TOKEN"})
    assert r.status == "needs_user"
    assert "does not look like a Figma URL" in r.answer


def test_a_valid_url_gets_past_validation():
    """A real file key is 10+ characters; the failure here must be the missing
    Blueprint, not the URL."""
    r = _session()._connect_figma({
        "figma_url": "https://www.figma.com/design/aBcD1234EfGh/P?node-id=1-2",
        "token_env": "FIGMA_TOKEN",
    })
    assert "does not look like a Figma URL" not in r.answer


def test_a_turn_reports_rather_than_raising():
    """A chat turn that raises loses the conversation. Every failure path
    returns a TurnResult."""
    r = _session("/nonexistent")._connect_figma({
        "figma_url": "https://www.figma.com/design/aBcD1234EfGh/P",
        "token_env": "FIGMA_TOKEN",
    })
    assert r.status in ("asked", "needs_user")
    assert r.answer
