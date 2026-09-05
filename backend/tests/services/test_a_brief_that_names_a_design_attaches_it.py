"""An opening brief with a Figma link in it names a design; the router attaches
it the moment the definition has made a Blueprint. Nothing about the token is
held: only its NAME is read."""
from services.smith.figma_connect import find_in


def test_the_link_the_token_name_and_the_scope_are_read():
    found = find_in("Palestine Legislative Council Dashboard\n\nConnect this Figma design as the "
                    "specification: https://www.figma.com/design/m17vMkD0GiMtLog7IH24cV/PLC?node-id=0-1&t=abc "
                    "— the access token is in the environment variable FIGMA_TOKEN.")
    assert found == {"figma_url": "https://www.figma.com/design/m17vMkD0GiMtLog7IH24cV/PLC?node-id=0-1&t=abc",
                     "token_env": "FIGMA_TOKEN", "treat_as": "specification"}


def test_a_bare_link_defaults_to_the_named_token_and_the_specification():
    found = find_in("Build this: https://www.figma.com/file/AbC123xyzAbC123xyzAbCd/Shop")
    assert found["token_env"] == "FIGMA_TOKEN" and found["treat_as"] == "specification"


def test_a_reference_is_read_as_one_and_a_custom_name_is_kept():
    found = find_in("Use https://www.figma.com/design/AbC123xyzAbC123xyzAbCd/Shop as a reference; token in MY_FIGMA_TOKEN")
    assert found["treat_as"] == "reference" and found["token_env"] == "MY_FIGMA_TOKEN"


def test_prose_without_a_link_names_nothing():
    assert find_in("A noticeboard for a community centre in Ramallah") is None
    assert find_in("see https://example.com/design/abc") is None
