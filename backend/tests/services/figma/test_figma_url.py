"""§41 — what the user actually pastes."""
import pytest

from services.figma.url import parse, normalise_node_id


def test_design_url_with_node():
    t = parse("https://www.figma.com/design/AbcDef123456/Recruitment?node-id=1-234")
    assert t.file_key == "AbcDef123456"
    assert t.node_id == "1:234"
    assert not t.is_whole_file


def test_older_file_url_and_encoded_node():
    t = parse("https://figma.com/file/AbcDef123456/Old?node-id=1%3A234&t=xyz")
    assert (t.file_key, t.node_id) == ("AbcDef123456", "1:234")


def test_whole_file_url_is_valid_not_a_failure():
    """The legacy parser returned None here, which read downstream as
    'Figma is unavailable' rather than 'the user linked the whole file'."""
    t = parse("https://www.figma.com/design/AbcDef123456/Recruitment")
    assert t is not None
    assert t.file_key == "AbcDef123456"
    assert t.node_id is None
    assert t.is_whole_file


def test_branch_url_extracts_the_branch_not_the_parent():
    t = parse(
        "https://figma.com/design/ParentKey12345/branch/BranchKey9876/Rec?node-id=2-2"
    )
    assert t.file_key == "BranchKey9876"
    assert t.parent_file_key == "ParentKey12345"


def test_prototype_url():
    t = parse("https://www.figma.com/proto/AbcDef123456/Flow?node-id=9-9")
    assert (t.file_key, t.node_id) == ("AbcDef123456", "9:9")


def test_scheme_less_paste():
    assert parse("figma.com/design/AbcDef123456/X?node-id=1-2").file_key == "AbcDef123456"


@pytest.mark.parametrize("text", [
    "", "   ", "not a url", "https://example.com/design/AbcDef123456/X",
    "https://figma.com/settings", None,
])
def test_non_figma_input_returns_none(text):
    assert parse(text) is None


def test_describe_is_human_readable():
    assert "the whole file" in parse("figma.com/design/AbcDef123456/X").describe()
    assert "node 1:2" in parse("figma.com/design/AbcDef123456/X?node-id=1-2").describe()


def test_normalise_node_id():
    assert normalise_node_id("1-234") == "1:234"
    assert normalise_node_id("1%3A234") == "1:234"
    assert normalise_node_id(" 1:234 ") == "1:234"
