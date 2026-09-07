"""project_assets: an editor-uploaded image must be readable by BOTH previews.

The bug this file exists to prevent is not a crash — it is an image that shows
up in the editor canvas and renders as a broken box in the preview iframe,
because `frontend/src/lib/resolveProject.ts` and
`apps/render-scaffold/src/lib/resolveProject.ts` resolve the same project id to
different directories. See the module docstring in services/project_assets.py.
"""
import pytest

from services.chat_attachments import MAX_BYTES, AttachmentError
from services.project_assets import asset_roots, save_project_image

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _flat(tmp_path):
    """A project projected straight into output/<id> (older layout)."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    return tmp_path


def _blueprint(tmp_path):
    """A Blueprint-projected project: schemas live in output/<id>/app/src/schemas,
    which is exactly the case where the two resolvers disagree."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "app" / "src" / "schemas").mkdir(parents=True)
    return tmp_path


def test_flat_layout_has_one_root(tmp_path):
    assert asset_roots(_flat(tmp_path)) == [tmp_path]


def test_blueprint_layout_probes_the_app_subtree_too(tmp_path):
    roots = asset_roots(_blueprint(tmp_path))
    assert roots == [tmp_path, tmp_path / "app"]


def test_empty_app_dir_is_not_a_root(tmp_path):
    """apps/render-scaffold's resolveProject probes `app/src/schemas`, not `app`
    — an untouched template floor is not where it looks."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "app").mkdir()
    assert asset_roots(tmp_path) == [tmp_path]


def test_bytes_land_under_every_root_a_reader_probes(tmp_path):
    root = _blueprint(tmp_path)
    rec = save_project_image(root, "gh0mlpbp", "logo.png", "image/png", PNG)

    name = rec["file"]
    assert (root / "public" / "figma" / name).read_bytes() == PNG
    assert (root / "app" / "public" / "figma" / name).read_bytes() == PNG


def test_url_is_the_shape_both_asset_routes_serve(tmp_path):
    rec = save_project_image(_flat(tmp_path), "gh0mlpbp", "logo.png", "image/png", PNG)
    assert rec["url"] == f"/api/asset/gh0mlpbp/figma/{rec['file']}"
    assert rec["media_type"] == "image/png"
    assert rec["bytes"] == len(PNG)


def test_same_bytes_reuse_the_same_url(tmp_path):
    """Content-addressed names — dropping one logo on ten nodes stores it once."""
    root = _flat(tmp_path)
    a = save_project_image(root, "p", "logo.png", "image/png", PNG)
    b = save_project_image(root, "p", "renamed-copy.png", "image/png", PNG)
    assert a["url"] == b["url"]


def test_extension_follows_the_media_type_not_the_name(tmp_path):
    """A browser drag can hand us a correct type and a meaningless name; the
    served Content-Type is derived from the extension, so it must follow the
    type we trusted."""
    rec = save_project_image(_flat(tmp_path), "p", "image", "image/webp", PNG)
    assert rec["file"].endswith(".webp")
    assert rec["media_type"] == "image/webp"


def test_image_jpg_alias_is_accepted(tmp_path):
    """Browsers send `image/jpg`, which is not a real media type."""
    rec = save_project_image(_flat(tmp_path), "p", "shot.jpg", "image/jpg", PNG)
    assert rec["media_type"] == "image/jpeg"


@pytest.mark.parametrize("filename,content_type", [
    ("spec.pdf", "application/pdf"),
    ("notes.txt", "text/plain"),
    ("icon.svg", "image/svg+xml"),      # deliberately not in chat_attachments' set
    ("archive.zip", "application/zip"),
])
def test_non_images_are_refused_out_loud(tmp_path, filename, content_type):
    with pytest.raises(AttachmentError) as exc:
        save_project_image(_flat(tmp_path), "p", filename, content_type, PNG)
    assert filename in str(exc.value)


def test_oversized_is_refused_with_the_limit_in_the_message(tmp_path):
    with pytest.raises(AttachmentError) as exc:
        save_project_image(_flat(tmp_path), "p", "big.png", "image/png",
                           b"\x00" * (MAX_BYTES + 1))
    assert "10 MB" in str(exc.value)


def test_empty_upload_is_refused(tmp_path):
    with pytest.raises(AttachmentError):
        save_project_image(_flat(tmp_path), "p", "empty.png", "image/png", b"")
