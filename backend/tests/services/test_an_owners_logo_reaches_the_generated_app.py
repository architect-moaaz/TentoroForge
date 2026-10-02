"""The owner's logo survives the whole way: contract, disk, document, tree.

The phrasebook closed on "colours and type can change; no image can be
supplied", and it was accurate. A logo could be uploaded (`/api/brand/extract/logo`),
was read for its palette, and was then dropped — the colours reached the
application and the mark did not, because there was no field in the Blueprint
for it to reach.

So these are the four joints of the one path, each tested where it can break:

1. the contract declares `designSystem.logo`, and refuses anything else —
   a field written into a section with `additionalProperties: false` that the
   contract does not declare makes every generated application unmodifiable on
   its next save;
2. the file lands beside the Blueprint, content-addressed, and a path that is
   not one we wrote is refused rather than followed;
3. the seam commits it as a version, so `undo` can take it back out;
4. the projection puts the reference in `shell.json` and the bytes under
   `public/`, and the two agree on the path.
"""
import json
import zlib
from pathlib import Path

import pytest

from services import brand_logo
from services.blueprint.projection import (brand_mark, project_brand_logo,
                                           project_shell)
from services.blueprint.service import BlueprintService
from services.smith.brand_logo_change import (BrandLogoChangeError, clear_logo,
                                              set_logo)

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json"


def _png(width: int, height: int) -> bytes:
    """A real PNG of the given size — small enough to inline, real enough that
    PIL reads its header the way it reads an owner's upload."""
    def chunk(tag: bytes, body: bytes) -> bytes:
        return (len(body).to_bytes(4, "big") + tag + body
                + zlib.crc32(tag + body).to_bytes(4, "big"))

    ihdr = (width.to_bytes(4, "big") + height.to_bytes(4, "big")
            + bytes([8, 2, 0, 0, 0]))          # 8-bit truecolour
    raw = b"".join(b"\x00" + b"\x2f\x8a\x55" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 60">'
       b'<rect width="240" height="60" fill="#0a7"/></svg>')


@pytest.fixture
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="APP-1",
                                name="Bright Care", domain="care")
    # `empty_blueprint` leaves `designSystem` out entirely — the section is
    # written by the design agent on the first build. Present and empty here,
    # which is what a built application's document looks like before anyone
    # has asked for a logo.
    s.doc["designSystem"] = {"colors": {"primary": "#0a7"}}
    s.doc["pages"] = [{"id": "PAGE-001", "name": "Home", "route": "/home",
                       "purpose": "where the day starts", "access": "authenticated"}]
    s.doc["navigation"] = {"tree": [{"label": "Home", "page": "PAGE-001"}]}
    s.save()
    return s


# --------------------------------------------------------------------------- #
# 1. the contract
# --------------------------------------------------------------------------- #

def test_the_contract_declares_the_logo():
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    design = schema["properties"]["designSystem"]
    assert design.get("additionalProperties") is False, (
        "if the section stops refusing unknown keys this test proves nothing")
    logo = design["properties"]["logo"]
    assert logo["required"] == ["file"]
    assert set(logo["properties"]) == {"file", "alt", "mediaType", "width", "height"}


def test_a_document_carrying_a_logo_still_validates(svc, tmp_path):
    svc.doc["designSystem"]["logo"] = brand_logo.store(
        tmp_path, "mark.png", "image/png", _png(48, 48))
    svc.validate()                      # the whole point: no refusal here
    svc.save()
    assert BlueprintService.load(output_dir=tmp_path).doc["designSystem"]["logo"]


def test_a_field_the_contract_does_not_declare_is_still_refused(svc, tmp_path):
    """The guarantee the declaration was ordered first to protect."""
    from services.blueprint.service import BlueprintInvalid

    svc.doc["designSystem"]["logotype"] = {"file": "brand/x.png"}
    with pytest.raises(BlueprintInvalid):
        svc.validate()


# --------------------------------------------------------------------------- #
# 2. the file on disk
# --------------------------------------------------------------------------- #

def test_the_mark_lands_beside_the_blueprint_and_is_measured(tmp_path):
    body = brand_logo.store(tmp_path, "logo.png", "image/png", _png(120, 40))
    assert body["mediaType"] == "image/png"
    assert (body["width"], body["height"]) == (120, 40)
    assert (tmp_path / body["file"]).is_file()
    assert body["file"].startswith("brand/")


def test_the_same_mark_twice_is_one_file(tmp_path):
    data = _png(32, 32)
    first = brand_logo.store(tmp_path, "a.png", "image/png", data)
    second = brand_logo.store(tmp_path, "b-renamed.png", "image/png", data)
    assert first["file"] == second["file"]
    assert len(list((tmp_path / "brand").iterdir())) == 1


def test_an_svg_is_accepted_and_read_for_its_ratio(tmp_path):
    """The format most brand marks arrive in, and the one the chat composer
    cannot take — the vision API has no use for it and the browser does."""
    body = brand_logo.store(tmp_path, "wordmark.svg", "image/svg+xml", SVG)
    assert body["mediaType"] == "image/svg+xml"
    assert (body["width"], body["height"]) == (240, 60)


def test_a_pdf_is_refused_where_the_owner_can_see_it(tmp_path):
    with pytest.raises(brand_logo.BrandLogoError):
        brand_logo.store(tmp_path, "brand-guidelines.pdf", "application/pdf", b"%PDF-1.4")


def test_a_stored_path_we_did_not_write_is_not_followed(tmp_path):
    """`file` comes out of a JSON document, and the projection copies whatever
    it names into a tree that gets published."""
    (tmp_path / "secrets.png").write_bytes(_png(8, 8))
    assert brand_logo.path_of(tmp_path, {"file": "../secrets.png"}) is None
    assert brand_logo.path_of(tmp_path, {"file": "/etc/passwd"}) is None
    assert brand_logo.path_of(tmp_path, {"file": "brand/nothere.png"}) is None


# --------------------------------------------------------------------------- #
# 3. the seam
# --------------------------------------------------------------------------- #

def test_setting_the_logo_is_a_version_undo_can_take_back(svc, tmp_path):
    body = brand_logo.store(tmp_path, "logo.png", "image/png", _png(64, 64))
    before = svc.doc["version"]
    out = set_logo(svc, body)
    assert out["applied"] and svc.doc["designSystem"]["logo"]["file"] == body["file"]
    assert svc.doc["version"] == before + 1
    # The diff is what names the change: `affectedArtifacts` holds artifact
    # ids, and `designSystem` is a singleton section with none.
    diff = svc.doc["changeHistory"][-1]["blueprintDiff"]
    assert any(str(op.get("path", "")).endswith("/designSystem/logo") for op in diff), diff

    cleared = clear_logo(svc)
    assert cleared["previous"] == out["logo"]
    assert "logo" not in svc.doc["designSystem"]


def test_the_alt_text_the_owner_gave_is_what_is_recorded(svc, tmp_path):
    body = brand_logo.store(tmp_path, "logo.png", "image/png", _png(64, 64))
    set_logo(svc, body, alt="Bright Care, in green")
    assert svc.doc["designSystem"]["logo"]["alt"] == "Bright Care, in green"


def test_a_logo_the_project_does_not_have_is_refused_not_recorded(svc):
    with pytest.raises(BrandLogoChangeError):
        set_logo(svc, {"file": "brand/0000000000000000.png", "mediaType": "image/png"})
    assert "logo" not in svc.doc["designSystem"]


def test_removing_a_logo_that_was_never_set_says_so(svc):
    with pytest.raises(BrandLogoChangeError):
        clear_logo(svc)


# --------------------------------------------------------------------------- #
# 4. the projection
# --------------------------------------------------------------------------- #

def test_the_rail_names_the_mark_and_the_tree_carries_it(svc, tmp_path):
    app_root = tmp_path / "app"
    body = brand_logo.store(tmp_path, "logo.png", "image/png", _png(160, 40))
    set_logo(svc, body, app_root=str(app_root))

    shell = json.loads((app_root / "src/schemas/shell.json").read_text())
    rail = shell["children"][0]["props"]
    assert rail["logoSrc"] == "/" + body["file"]
    assert rail["logoAlt"] == "Bright Care"          # the app's name, not the digest
    assert rail["logoAspect"] == 4.0

    served = app_root / "public" / body["file"]
    assert served.is_file() and served.read_bytes() == (tmp_path / body["file"]).read_bytes()
    assert rail["logoSrc"] == "/" + str(served.relative_to(app_root / "public"))


def test_an_application_with_no_logo_keeps_the_rail_it_had(svc, tmp_path):
    app_root = tmp_path / "app"
    project_shell(svc.doc, app_root)
    rail = json.loads((app_root / "src/schemas/shell.json").read_text())["children"][0]["props"]
    assert "logoSrc" not in rail and rail["appName"] == "Bright Care"
    # The contract module is still written — the sign-in screen imports it —
    # but nothing is copied into the tree.
    assert project_brand_logo(svc.doc, app_root)["files"] == ["src/contracts/brand.ts"]
    assert "BRAND_LOGO: BrandLogo | null = null" in (
        app_root / "src/contracts/brand.ts").read_text()
    assert not (app_root / "public").exists()


def test_a_document_naming_a_file_the_project_lost_does_not_fail_the_build(svc, tmp_path):
    """Reported, not raised: `_project_frontend` runs this beside the tokens
    and the middleware, and losing them over a missing image would cost the
    whole application rather than one picture."""
    svc.doc["designSystem"]["logo"] = {"file": "brand/" + "a" * 16 + ".png",
                                       "mediaType": "image/png", "alt": ""}
    out = project_brand_logo(svc.doc, tmp_path / "app")
    assert out["files"] == ["src/contracts/brand.ts"]
    assert out["reason"] == "logo file missing"


def test_a_hand_edited_path_never_becomes_a_url(svc):
    svc.doc["designSystem"]["logo"] = {"file": "../../../etc/passwd", "alt": ""}
    assert brand_mark(svc.doc) == {}


def test_a_restyle_does_not_take_the_mark_with_it(svc, tmp_path):
    """`restyle` re-decides the whole `designSystem` through the design agent,
    which knows nothing about a logo and returns a body without one. Singleton
    sections merge (`BlueprintService.upsert`), so the mark survives — pinned
    here because the alternative is an owner's logo vanishing the next time
    they ask for a different green, with nothing in the reply to say it did.
    """
    body = brand_logo.store(tmp_path, "logo.png", "image/png", _png(64, 64))
    set_logo(svc, body)
    svc.upsert("designSystem", {"colors": {"primary": "#116611"},
                                "visualPersonality": "greener"},
               natural_key="designSystem")
    svc.validate()
    assert svc.doc["designSystem"]["logo"] == body
    assert svc.doc["designSystem"]["colors"] == {"primary": "#116611"}


# --------------------------------------------------------------------------- #
# 5. the pages with no shell around them
# --------------------------------------------------------------------------- #

def test_the_pages_with_no_shell_are_given_the_mark_too(svc, tmp_path):
    """Sign-in, sign-up and the error pages render outside the rail — and they
    are the ones an anonymous visitor actually reaches. They cannot read
    `shell.json` (two of them are client components, and an application with no
    navigation tree has no shell file at all), so the mark is projected as a
    module they import."""
    app_root = tmp_path / "app"
    body = brand_logo.store(tmp_path, "logo.png", "image/png", _png(160, 40))
    set_logo(svc, body, alt="Bright Care", app_root=str(app_root))

    module = (app_root / "src/contracts/brand.ts").read_text()
    assert f'"src": "/{body["file"]}"' in module
    assert '"alt": "Bright Care"' in module
    assert '"aspect": 4' in module


def test_the_rail_and_the_sign_in_screen_cannot_disagree(svc, tmp_path):
    """Both are built from `brand_mark(doc)`. Two readers, one answer — the
    failure this forecloses is a logo in the corner of the app and a letter on
    its front door."""
    app_root = tmp_path / "app"
    body = brand_logo.store(tmp_path, "logo.png", "image/png", _png(160, 40))
    set_logo(svc, body, app_root=str(app_root))

    rail = json.loads((app_root / "src/schemas/shell.json").read_text())["children"][0]["props"]
    module = (app_root / "src/contracts/brand.ts").read_text()
    assert f'"src": "{rail["logoSrc"]}"' in module
    assert f'"alt": "{rail["logoAlt"]}"' in module


def test_taking_the_logo_off_empties_the_module_too(svc, tmp_path):
    app_root = tmp_path / "app"
    body = brand_logo.store(tmp_path, "logo.png", "image/png", _png(64, 64))
    set_logo(svc, body, app_root=str(app_root))
    clear_logo(svc, app_root=str(app_root))
    assert "= null;" in (app_root / "src/contracts/brand.ts").read_text()


def test_the_scaffold_ships_the_same_module_as_a_default():
    """`BrandMark.tsx` imports it and every error page renders that, so a tree
    without the module does not compile. The projection writes it on every
    build; this is the floor for a build where the projection never ran."""
    from services.blueprint.assembly import PROJECTED_PATHS, SCAFFOLD_DEFAULTS

    root = Path(__file__).resolve().parents[2] / "templates" / "app-foundation"
    shipped = root / "src" / "contracts" / "brand.ts"
    assert shipped.is_file()
    assert "BRAND_LOGO: BrandLogo | null = null" in shipped.read_text()
    # Without the default listing, `src/contracts` being projection-owned means
    # the copy step skips it and the floor is never laid.
    assert "src/contracts/brand.ts" in SCAFFOLD_DEFAULTS
    assert any("src/contracts".startswith(p) or p == "src/contracts"
               for p in PROJECTED_PATHS)


def test_the_module_and_the_default_declare_one_shape():
    """Two files exporting `BRAND_LOGO` is two chances to describe it
    differently; the importer is typed against whichever one the tree has."""
    import re

    from services.blueprint.projection import _write_brand_module

    root = Path(__file__).resolve().parents[2] / "templates" / "app-foundation"
    shipped = (root / "src/contracts/brand.ts").read_text()

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _write_brand_module({}, tmp)
        projected = (Path(tmp) / "src/contracts/brand.ts").read_text()

    def fields(src: str) -> set[str]:
        block = re.search(r"export type BrandLogo = \{(.*?)\n\};", src, re.S)
        assert block, src
        return set(re.findall(r"^\s*(\w+)\??:", block.group(1), re.M))

    assert fields(shipped) == fields(projected) == {"src", "alt", "aspect"}


def test_every_chrome_less_surface_draws_the_mark():
    """The scaffold's .tsx files have no test harness of their own, so this is
    the only thing holding the four screens an anonymous visitor reaches to
    drawing the owner's mark. Each keeps its OWN fallback — the gradient square
    on sign-in, the big monogram on a 404 — so this checks that the mark is
    reached for, not that the four designs were collapsed into one."""
    tpl = Path(__file__).resolve().parents[2] / "templates"
    surfaces = {
        "app-foundation/src/app/login/page.tsx": "the sign-in screen",
        "app-foundation/src/app/signup/page.tsx": "the sign-up screen",
        "standalone-app/src/components/EdgePageFrame.tsx": "404 / 403 / 500 / maintenance",
        "app-foundation/src/components/PublicPageFrame.tsx": "a public page",
        # EVERY CHROME, NOT THE DEFAULT ONE. `(dashboard)/layout.tsx` picks
        # between eight shells, and only `standard-rail` goes through the
        # library's SideNav. The logo landed there and nowhere else: an
        # application whose design DNA chose a wide rail, an icon rail, a dock,
        # a topbar or persona pills showed the owner's mark on its sign-in
        # screen and an initial in its own shell.
        "app-foundation/src/app/(dashboard)/layout.tsx": "the four other rail chromes",
        "app-foundation/src/app/(dashboard)/PersonaChrome.tsx": "the persona-pills chrome",
        "app-foundation/src/app/(dashboard)/MobileNav.tsx": "every chrome below 768px",
    }
    for rel, what in surfaces.items():
        src = (tpl / rel).read_text(encoding="utf-8")
        assert "BrandMark" in src and "BRAND_LOGO" in src, (
            f"{what} ({rel}) no longer reaches for the owner's mark")
        assert "@/components/BrandMark" in src, rel
