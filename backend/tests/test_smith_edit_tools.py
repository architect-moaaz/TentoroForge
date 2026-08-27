"""File-tool tests for Smith's Claude-Code-style read/edit/verify.

These cover the sandbox boundary (path safety, extension gate),
edit contract (no-op refused, ambiguous matches refused, exact
replacement), and the verifier's two modes (schema walk + substring
fallback)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith_edit_tools import (
    edit_file,
    read_file,
    verify_promise,
)


REFERRAL_SCHEMA = {
    "root": {
        "type": "Form",
        "children": [
            {"type": "Input", "props": {"name": "fullName",    "label": "Full Name"}},
            {"type": "Input", "props": {"name": "email",       "label": "Email"}},
            {"type": "Input", "props": {"name": "phone",       "label": "Phone"}},
            {"type": "Input", "props": {"name": "password",    "label": "Password"}},
            {"type": "Select", "props": {"name": "role",       "label": "Role"}},
        ],
    },
}


@pytest.fixture()
def app(tmp_path: Path) -> Path:
    """A tiny fake generated-app tree."""
    (tmp_path / "src" / "schemas" / "referrals").mkdir(parents=True)
    (tmp_path / "src" / "schemas" / "referrals" / "new.json").write_text(
        json.dumps(REFERRAL_SCHEMA, indent=2)
    )
    (tmp_path / "README.md").write_text("Vet clinic app.")
    (tmp_path / "package-lock.json").write_text("{}")  # allowed ext, big file class
    return tmp_path


# =========================================================================
# Path safety
# =========================================================================

def test_read_rejects_path_escape(app: Path):
    assert "error" in read_file(str(app), {"path": "../../etc/passwd"})


def test_read_rejects_absolute_path(app: Path):
    assert "error" in read_file(str(app), {"path": "/etc/passwd"})


def test_read_rejects_disallowed_extension(app: Path):
    # A .sqlite file isn't in the allow list.
    (app / "data.sqlite").write_text("BLOB")
    assert "error" in read_file(str(app), {"path": "data.sqlite"})


def test_read_rejects_missing_file(app: Path):
    assert "error" in read_file(str(app), {"path": "src/nonexistent.json"})


def test_read_rejects_directory(app: Path):
    result = read_file(str(app), {"path": "src/schemas"})
    assert "error" in result and "director" in result["error"].lower()


def test_read_returns_content_for_allowed_file(app: Path):
    r = read_file(str(app), {"path": "src/schemas/referrals/new.json"})
    assert "error" not in r
    assert '"password"' in r["content"]
    assert r["lines"] > 5


def test_read_truncates_very_long_files(app: Path):
    (app / "big.md").write_text("line\n" * 5000)
    r = read_file(str(app), {"path": "big.md"})
    assert r["truncated"] is True
    assert r["lines"] == 5000


# =========================================================================
# edit_file — contracts
# =========================================================================

def test_edit_refuses_noop(app: Path):
    r = edit_file(str(app), {
        "path": "src/schemas/referrals/new.json",
        "old_string": '"password"',
        "new_string": '"password"',
    })
    assert "error" in r and "no-op" in r["error"].lower()


def test_edit_refuses_missing_substring(app: Path):
    r = edit_file(str(app), {
        "path": "src/schemas/referrals/new.json",
        "old_string": "this-string-does-not-exist",
        "new_string": "anything",
    })
    assert "error" in r and "not found" in r["error"].lower()


def test_edit_refuses_ambiguous_match(app: Path):
    """Multiple matches → refuse and ask Smith to disambiguate."""
    r = edit_file(str(app), {
        "path": "src/schemas/referrals/new.json",
        "old_string": '"type": "Input"',
        "new_string": '"type": "TextInput"',
    })
    assert "error" in r and "unique" in r["error"].lower()


def test_edit_relabels_password_field(app: Path):
    """A minimal, indent-agnostic edit: Smith reads the file, picks a
    unique substring that appears exactly once (`"Password"`), and
    replaces it with `"Passphrase"`. Exercises the exact-string
    contract end-to-end without depending on JSON layout."""
    path = "src/schemas/referrals/new.json"
    r = edit_file(str(app), {
        "path": path,
        "old_string": '"label": "Password"',
        "new_string": '"label": "Passphrase"',
    })
    assert r["edited"] is True
    disk = (app / path).read_text()
    assert '"Passphrase"' in disk
    assert '"label": "Password"' not in disk
    # File must still parse as JSON.
    json.loads(disk)


def test_edit_delete_is_allowed_when_new_string_is_empty(app: Path):
    r = edit_file(str(app), {
        "path": "README.md",
        "old_string": "Vet clinic app.",
        "new_string": "",
    })
    assert r["edited"] is True
    assert (app / "README.md").read_text() == ""


def test_edit_rejects_path_escape(app: Path):
    assert "error" in edit_file(str(app), {
        "path": "../../etc/passwd",
        "old_string": "x", "new_string": "y",
    })


# =========================================================================
# verify_promise — schema-walk verifier
# =========================================================================

def _write(app: Path, path: str, obj: dict) -> None:
    (app / path).write_text(json.dumps(obj, indent=2))


def test_verify_remove_kept_when_field_absent(app: Path):
    # Author a post-edit fixture that no longer contains "password".
    stripped = {
        "root": {"type": "Form", "children": [
            c for c in REFERRAL_SCHEMA["root"]["children"]
            if c["props"]["name"] != "password"
        ]},
    }
    _write(app, "src/schemas/referrals/new.json", stripped)
    r = verify_promise(str(app), {
        "path": "src/schemas/referrals/new.json",
        "claim": "The password field is removed from the referral form.",
    })
    assert r["kept"] is True


def test_verify_remove_broken_when_field_still_present(app: Path):
    r = verify_promise(str(app), {
        "path": "src/schemas/referrals/new.json",
        "claim": "The password field is removed from the referral form.",
    })
    assert r["kept"] is False
    assert r["failures"]
    ev = r["failures"][0]["evidence"]
    assert "password" in ev.lower() or "Password" in ev


def test_verify_add_kept_when_new_field_present(app: Path):
    added = {
        "root": {"type": "Form", "children": [
            *REFERRAL_SCHEMA["root"]["children"],
            {"type": "Select", "props": {"name": "status", "label": "Status"}},
        ]},
    }
    _write(app, "src/schemas/referrals/new.json", added)
    r = verify_promise(str(app), {
        "path": "src/schemas/referrals/new.json",
        "claim": "Add a status dropdown to the form.",
    })
    assert r["kept"] is True


def test_verify_add_broken_when_field_absent(app: Path):
    r = verify_promise(str(app), {
        "path": "src/schemas/referrals/new.json",
        "claim": "Add a nonexistent gizmo field.",
    })
    assert r["kept"] is False


def test_verify_passes_on_vague_claim(app: Path):
    """Same false-negative bias as the coherence gate — a vague claim
    can't be enforced and therefore isn't evidence of failure."""
    r = verify_promise(str(app), {
        "path": "src/schemas/referrals/new.json",
        "claim": "Applied the fix.",
    })
    assert r["kept"] is True


def test_verify_non_json_falls_back_to_substring(app: Path):
    (app / "src" / "app.tsx").write_text(
        "export const Foo = () => <input name='password' />;"
    )
    r = verify_promise(str(app), {
        "path": "src/app.tsx",
        "claim": "Remove password field.",
    })
    assert r["kept"] is False


def test_verify_rejects_bad_paths(app: Path):
    assert "error" in verify_promise(str(app), {
        "path": "../secret.txt", "claim": "remove x",
    })
    assert "error" in verify_promise(str(app), {
        "path": "src/nope.json", "claim": "remove x",
    })
