"""§5 — an application can be described by showing as well as by telling.

`AnthropicModel` has accepted an image since the montage work; nothing in the
graph ever passed one. So an application described by screenshot was, to every
agent, an application described by silence. These tests are about the route in
and about who is at the end of it — an image costs tokens on every call, and a
node that cannot act on what it shows is paying for a picture it must ignore.
"""
import json

import pytest

from services.blueprint import references
from services.blueprint.executors import build_prompt, image_blocks, make_executor
from services.blueprint.orchestrator import run
from services.blueprint.service import BlueprintService

# A 1x1 PNG — the smallest thing the transport will call an image.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d76360000000020001e221bc330000000049454e44ae426082")


@pytest.fixture
def svc(tmp_path) -> BlueprintService:
    return BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="Recruitment", domain="ATS")


def envelope(**over) -> str:
    base = {
        "proposals": [{
            "section": "requirements",
            "natural_key": "req-1",
            "body": json.dumps({"description": "Post a role."}),
        }],
        "confidence": 0.9,
        "assumptions": [], "issues": [], "change_requests": [],
    }
    base.update(over)
    return json.dumps(base)


class Recorder:
    """A client that can carry images and remembers whether it was given any."""

    enforces_schema = True
    accepts_images = True

    def __init__(self, reply: str = ""):
        self.calls: list[dict] = []
        self.reply = reply or envelope()

    def __call__(self, **kw):
        self.calls.append(kw)
        return self.reply


class Blind(Recorder):
    """A transport that takes (system, user, schema) and nothing else."""

    accepts_images = False

    def __call__(self, *, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        return self.reply


# --- what the application holds --------------------------------------------

def test_references_are_read_in_a_stable_order(tmp_path):
    """The order reaches a prompt. An unstable one is a different prefix every
    run, which costs the cache the montage work existed to win."""
    references.adopt_bytes(tmp_path, "b.png", _PNG, media_type="image/png")
    references.adopt_bytes(tmp_path, "a.png", _PNG, media_type="image/png")
    assert [p.name for p in references.paths(tmp_path)] == ["a.png", "b.png"]


def test_an_application_with_no_references_has_none(tmp_path):
    assert references.paths(tmp_path) == []


def test_adopting_copies_rather_than_points(tmp_path):
    """A Blueprint exported with a path into somebody's upload directory is an
    application that cannot be rebuilt anywhere else (§83)."""
    src = tmp_path / "elsewhere" / "shot.png"
    src.parent.mkdir()
    src.write_bytes(_PNG)
    out = tmp_path / "app"

    adopted = references.adopt(out, [src])
    src.unlink()

    assert [p.name for p in adopted] == ["shot.png"]
    assert references.paths(out)[0].read_bytes() == _PNG


def test_what_is_not_an_image_is_skipped_not_fatal(tmp_path):
    """A user who attached a PDF to a chat has not made a design reference, and
    failing the intake over it would lose the three that were."""
    good = tmp_path / "in" / "shot.png"
    bad = tmp_path / "in" / "spec.pdf"
    good.parent.mkdir()
    good.write_bytes(_PNG)
    bad.write_bytes(b"%PDF-1.4")

    adopted = references.adopt(tmp_path / "app", [bad, good])
    assert [p.name for p in adopted] == ["shot.png"]


def test_bytes_are_stored_under_the_suffix_the_media_type_implies(tmp_path):
    """The attachment store holds id-named blobs with no extension, and the
    transport decides what it accepts from the suffix."""
    stored = references.adopt_bytes(
        tmp_path, "screenshot", _PNG, media_type="image/png")
    assert stored is not None and stored.suffix == ".png"
    assert references.paths(tmp_path) == [stored]


def test_a_name_claiming_png_over_bytes_that_are_not_is_stored_by_type(tmp_path):
    """A `.png` that is really a PDF must not be handed to the transport as an
    image."""
    assert references.adopt_bytes(
        tmp_path, "spec.png", b"%PDF", media_type="application/pdf") is None


def test_an_upload_name_cannot_become_a_path(tmp_path):
    """The name is user input reaching a filesystem path."""
    stored = references.adopt_bytes(
        tmp_path, "../../etc/passwd.png", _PNG, media_type="image/png")
    assert stored is not None
    assert stored.parent == references.directory(tmp_path)
    assert "/" not in stored.name and ".." not in stored.name


def test_clearing_undesignates_everything(tmp_path):
    references.adopt_bytes(tmp_path, "a.png", _PNG, media_type="image/png")
    references.clear(tmp_path)
    assert references.paths(tmp_path) == []


# --- the prefix -------------------------------------------------------------

def test_only_the_last_reference_carries_the_cache_breakpoint(tmp_path):
    """A breakpoint marks a prefix boundary, not a block: everything ahead of
    it is cached by being ahead of it. Anthropic allows four in total."""
    paths = [references.adopt_bytes(tmp_path, f"{n}.png", _PNG,
                                    media_type="image/png")
             for n in ("a", "b", "c")]
    blocks = image_blocks(paths)

    assert [b["type"] for b in blocks] == ["image"] * 3
    assert "cache_control" not in blocks[0] and "cache_control" not in blocks[1]
    assert blocks[2]["cache_control"] == {"type": "ephemeral"}


def test_no_references_is_no_blocks():
    assert image_blocks([]) == []


# --- who is shown them ------------------------------------------------------

def test_the_prompt_says_what_the_images_are(svc, tmp_path):
    """An image is ambiguous about its own status, and the expensive reading —
    a screenshot of the system being replaced taken as a specification of the
    one being built — is the one a model reaches for unprompted."""
    shot = references.adopt_bytes(
        tmp_path, "old-ats.png", _PNG, media_type="image/png")
    system, _user = build_prompt(svc.doc, "requirements", references=[shot])

    assert "old-ats.png" in system
    assert "REFERENCE, not specification" in system
    assert "evidence" in system


def test_a_node_shown_nothing_is_told_nothing(svc):
    system, _ = build_prompt(svc.doc, "requirements", references=[])
    assert "What the user showed you" not in system


def test_the_nodes_that_can_act_on_a_reference_are_shown_it(svc):
    client = Recorder()
    references.adopt_bytes(svc.output_dir, "shot.png", _PNG,
                           media_type="image/png")

    run(svc, make_executor(svc, client), plan=["requirements"])

    assert client.calls, "the node ran"
    shown = [p.name for p in client.calls[0]["images"]]
    assert shown == ["shot.png"]


def test_a_node_that_cannot_act_on_one_is_not_billed_for_it(svc):
    """`page_contracts` composes against a contract, not a picture."""
    client = Recorder(envelope(proposals=[{
        "section": "pages", "natural_key": "PAGE:/roles",
        "body": json.dumps({"name": "Roles", "route": "/roles",
                            "purpose": "Manage roles."}),
    }]))
    references.adopt_bytes(svc.output_dir, "shot.png", _PNG,
                           media_type="image/png")

    run(svc, make_executor(svc, client), plan=["page_contracts"])

    assert client.calls
    assert "images" not in client.calls[0]
    assert "What the user showed you" not in client.calls[0]["system"]


def test_a_transport_that_cannot_carry_an_image_is_never_handed_one(svc):
    """The OpenAI-compatible and Gemini clients take (system, user, schema) and
    would reject the keyword outright."""
    client = Blind()
    references.adopt_bytes(svc.output_dir, "shot.png", _PNG,
                           media_type="image/png")

    report = run(svc, make_executor(svc, client), plan=["requirements"])

    assert report.ok
    assert "images" not in client.calls[0]


def test_design_system_is_not_shown_references_yet(svc):
    """Deliberate, and worth a test so the omission is a decision rather than
    an oversight: its prompt tells it to choose colours from the domain by
    colour theory, and an image without that instruction changed gives it two
    sources of truth and no rule for which wins."""
    assert "design_system" not in references.SEES_REFERENCES
