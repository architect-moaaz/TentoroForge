"""Coherence check between a Smith propose_fix `explanation` and its
actual RFC-6902 `patch`.

The classic Smith failure this catches: he tells the user "I'll remove
the password field" and then his patch actually reorders an unrelated
Switch or renames a Textarea. The `explanation` field and the JSON patch
are two independent LLM outputs, and up to now nothing verified they
agree. This module reads a strong verb+noun phrase out of the
explanation, then checks that each op in the patch actually names or
touches that noun in the schema tree — otherwise the applier rejects
the fix and re-asks Smith.

We're not trying to parse arbitrary English; we look for a small,
high-signal set of imperative patterns Smith actually uses:
`remove X`, `add X`, `rename X to Y`, `replace X with Y`, `hide X`.
When the explanation has no strong phrase, we return no incoherence
(false-negative bias — a vague explanation is not evidence of
fabrication).
"""
from __future__ import annotations

import pytest

from services.patch_coherence import check_patch_coherence, check_promise_kept, _extract_phrases


# --------------------------------------------------------------------------- #
# Fixture — the exact vet-clinic referrals/new.json before Smith's bogus fix
# --------------------------------------------------------------------------- #

REFERRAL_FORM_PRE = {
    "root": {
        "type": "Form",
        "children": [
            {"type": "Input",    "props": {"name": "referringOwnerId", "label": "Referring Owner"}},
            {"type": "Input",    "props": {"name": "fullName",         "label": "Full Name"}},
            {"type": "Input",    "props": {"name": "email",            "label": "Email"}},
            {"type": "Input",    "props": {"name": "phone",            "label": "Phone"}},
            {"type": "Input",    "props": {"name": "password",         "label": "Password"}},
            {"type": "Select",   "props": {"name": "role",             "label": "Role"}},
            {"type": "Textarea", "props": {"name": "notes",            "label": "Notes"}},
            {"type": "Switch",   "props": {"name": "isActive",         "label": "Is Active"}},
        ],
    },
}


# =========================================================================
# CORE FAILURE MODE — Smith's password/isActive drift
# =========================================================================

def test_flags_remove_when_target_isnt_the_removed_field():
    """Explanation says 'remove password' but patch removes/moves isActive
    — the exact bug from output/2t5rkgso/src/schemas/referrals/new.json."""
    patch = [
        # what Smith actually did: reorder the isActive Switch
        {"op": "remove", "path": "/root/children/7"},  # removes isActive
        {"op": "add",    "path": "/root/children/5",   # re-adds it earlier
         "value": {"type": "Switch",
                   "props": {"name": "isActive", "label": "Is Active"}}},
    ]
    incoherences = check_patch_coherence(
        explanation="I'll remove the password field from the New Referral form.",
        patch=patch,
        pre_schema=REFERRAL_FORM_PRE,
    )
    assert incoherences, "Should have flagged the mismatch"
    assert any("password" in i["expected"].lower() for i in incoherences)
    assert any("isActive" in i["actual"] or "Is Active" in i["actual"] for i in incoherences)


def test_passes_when_remove_actually_removes_the_named_field():
    """Explanation says 'remove password' and patch does exactly that."""
    patch = [{"op": "remove", "path": "/root/children/4"}]  # password Input
    incoherences = check_patch_coherence(
        explanation="Remove the password field from the New Referral form.",
        patch=patch,
        pre_schema=REFERRAL_FORM_PRE,
    )
    assert incoherences == []


# =========================================================================
# add / rename / replace verbs
# =========================================================================

def test_flags_add_when_target_doesnt_name_expected_noun():
    """'Add a status dropdown' but the added node is a random Textarea."""
    patch = [{"op": "add", "path": "/root/children/-",
              "value": {"type": "Textarea",
                        "props": {"name": "comments", "label": "Comments"}}}]
    incoherences = check_patch_coherence(
        explanation="Add a status dropdown to the form.",
        patch=patch,
        pre_schema=REFERRAL_FORM_PRE,
    )
    assert incoherences


def test_passes_when_add_matches_target_name():
    patch = [{"op": "add", "path": "/root/children/-",
              "value": {"type": "Select",
                        "props": {"name": "status", "label": "Status"}}}]
    incoherences = check_patch_coherence(
        explanation="Add a status dropdown to the form.",
        patch=patch,
        pre_schema=REFERRAL_FORM_PRE,
    )
    assert incoherences == []


def test_passes_when_add_matches_target_type_alias():
    """'Add a dropdown' — the type is `Select`, but 'dropdown' should
    map to Select through a well-known synonym set."""
    patch = [{"op": "add", "path": "/root/children/-",
              "value": {"type": "Select",
                        "props": {"name": "priority", "label": "Priority"}}}]
    incoherences = check_patch_coherence(
        explanation="Add a priority dropdown to the form.",
        patch=patch,
        pre_schema=REFERRAL_FORM_PRE,
    )
    assert incoherences == []


def test_flags_rename_when_target_isnt_the_renamed_field():
    """'Rename email to workEmail' but the replaced node's name was
    'phone' → clearly wrong."""
    patch = [{"op": "replace", "path": "/root/children/3/props/name",
              "value": "workEmail"}]
    incoherences = check_patch_coherence(
        explanation="Rename email to workEmail.",
        patch=patch,
        pre_schema=REFERRAL_FORM_PRE,
    )
    assert incoherences


def test_passes_when_rename_touches_the_named_field():
    patch = [{"op": "replace", "path": "/root/children/2/props/name",
              "value": "workEmail"}]
    incoherences = check_patch_coherence(
        explanation="Rename email to workEmail.",
        patch=patch,
        pre_schema=REFERRAL_FORM_PRE,
    )
    assert incoherences == []


# =========================================================================
# Robustness — no-strong-verb explanations pass through (false-negative bias)
# =========================================================================

def test_passes_when_explanation_has_no_strong_verb():
    """Vague / meta-level explanations aren't evidence of fabrication;
    the coherence checker should NOT reject them."""
    patch = [{"op": "remove", "path": "/root/children/4"}]  # password
    for vague in [
        "I applied the fix.",
        "Fixed the form.",
        "Cleaned up the schema.",
        "",
        "This should work now.",
    ]:
        assert check_patch_coherence(
            explanation=vague,
            patch=patch,
            pre_schema=REFERRAL_FORM_PRE,
        ) == [], f"vague explanation should not flag: {vague!r}"


def test_flags_empty_patch_against_strong_explanation():
    """An empty patch paired with an explanation that promised change is
    a broken promise — the exact loophole that let Smith's 05778df
    commit (only .env touched, schema untouched) through the first
    coherence gate."""
    incoherences = check_patch_coherence(
        explanation="Remove the password field from the New Referral form.",
        patch=[],
        pre_schema=REFERRAL_FORM_PRE,
    )
    assert incoherences
    assert any(i["kind"] == "remove" and "password" in i["expected"] for i in incoherences)
    assert all("empty patch" in i["actual"] for i in incoherences)


def test_empty_patch_still_passes_when_explanation_is_vague():
    """Vague explanation + empty patch → no promise, no flag."""
    assert check_patch_coherence(
        explanation="Applied the fix.",
        patch=[],
        pre_schema=REFERRAL_FORM_PRE,
    ) == []


def test_passes_when_pre_schema_is_missing():
    """Applier calls this before touching disk. If for some reason we
    can't resolve the pre-image, degrade to no-flag rather than
    blocking a legitimate fix."""
    incoherences = check_patch_coherence(
        explanation="Remove the password field.",
        patch=[{"op": "remove", "path": "/anywhere"}],
        pre_schema=None,
    )
    assert incoherences == []


# =========================================================================
# Multi-op patches — each strong verb is checked independently
# =========================================================================

def test_multi_op_all_coherent():
    """A single explanation covering both a remove AND an add is
    coherent when the patch actually does both against the named
    targets."""
    patch = [
        {"op": "remove", "path": "/root/children/4"},  # password
        {"op": "add",    "path": "/root/children/-",
         "value": {"type": "Select",
                   "props": {"name": "status", "label": "Status"}}},
    ]
    incoherences = check_patch_coherence(
        explanation="Remove the password field and add a status dropdown.",
        patch=patch,
        pre_schema=REFERRAL_FORM_PRE,
    )
    assert incoherences == []


def test_multi_op_one_incoherent():
    """The remove-half matches; the add-half references the wrong noun."""
    patch = [
        {"op": "remove", "path": "/root/children/4"},  # password ✓
        {"op": "add",    "path": "/root/children/-",
         "value": {"type": "Input",       # ✗ not a "dropdown"
                   "props": {"name": "extra", "label": "Extra"}}},
    ]
    incoherences = check_patch_coherence(
        explanation="Remove the password field and add a status dropdown.",
        patch=patch,
        pre_schema=REFERRAL_FORM_PRE,
    )
    assert incoherences
    # Only the add-half is flagged.
    assert all("add" in i["kind"] for i in incoherences)


# =========================================================================
# Salient-identifier extraction — case + separator insensitive
# =========================================================================

# =========================================================================
# check_promise_kept — post-apply "did the diff actually happen?" gate
# =========================================================================

def test_promise_kept_flags_when_pre_equals_post_with_strong_verb():
    """The 05778df bug: patch was a no-op (replace with same value or
    an add-then-remove) → pre == post. Explanation promised removal →
    the promise wasn't kept → flag."""
    gaps = check_promise_kept(
        explanation="Remove the password field from the New Referral form.",
        pre_schema=REFERRAL_FORM_PRE,
        post_schema=REFERRAL_FORM_PRE,
    )
    assert gaps
    assert all("no diff" in g["actual"] for g in gaps)


def test_promise_kept_passes_when_something_actually_changed():
    post = {
        "root": {"type": "Form", "children": [
            c for i, c in enumerate(REFERRAL_FORM_PRE["root"]["children"]) if i != 4
        ]},
    }
    assert check_promise_kept(
        explanation="Remove the password field.",
        pre_schema=REFERRAL_FORM_PRE,
        post_schema=post,
    ) == []


def test_promise_kept_passes_on_vague_explanation():
    """Even if the file didn't change, a vague explanation isn't a
    broken promise — same false-negative bias as the pre-apply check."""
    assert check_promise_kept(
        explanation="Applied the fix.",
        pre_schema=REFERRAL_FORM_PRE,
        post_schema=REFERRAL_FORM_PRE,
    ) == []


def test_matches_across_case_and_separator_variants():
    """'Password' vs 'password' vs 'PasswordInput' vs 'password_input'
    are all the same identifier for coherence purposes."""
    # The removed field's name is "password_hash" in this variant;
    # explanation says "password" — substring match wins.
    schema = {
        "root": {"type": "Form", "children": [
            {"type": "Input", "props": {"name": "password_hash", "label": "Password Hash"}},
        ]},
    }
    patch = [{"op": "remove", "path": "/root/children/0"}]
    incoherences = check_patch_coherence(
        explanation="Remove the Password field.",
        patch=patch,
        pre_schema=schema,
    )
    assert incoherences == []


# =========================================================================
# "changed X to Y" — regression coverage for Smith's "Done!" lie about
# converting a Select to FileUpload (July-17). The label was capitalized
# but type stayed Select; verify_promise passed because no phrase named
# FileUpload was extracted (past-tense verb + `to <target>` idiom both
# missed). These tests lock the class.
# =========================================================================

def test_past_tense_replace_verb_is_captured():
    """`changed` / `converted` / `switched` past-tense forms must produce
    phrases — previously only present-tense `change` was recognized so
    Smith's self-reports slipped past extraction unread."""
    p = _extract_phrases("The field has been changed from Select to FileUpload")
    kinds = {k for k, _ in p}
    assert "replace" in kinds or "add" in kinds, (
        f"past-tense 'changed' produced no replace/add phrase: {p}"
    )


def test_from_to_target_is_extracted_as_add():
    """The idiom "verb ... to <TARGET>" must yield ('add', TARGET) so
    verify_promise checks the TARGET actually appears in the file."""
    p = _extract_phrases("changed from Select to FileUpload")
    assert ("add", "fileupload") in p


def test_smith_cv_lie_would_be_caught():
    """The exact Smith self-report string from the July-17 incident.
    Extraction must yield an ('add', 'fileupload') phrase so
    verify_promise fails when the file has no FileUpload node."""
    claim = (
        "The Latest CV Attachment field on the Add Candidate page has "
        "been changed from a dropdown Select to a FileUpload component"
    )
    p = _extract_phrases(claim)
    assert ("add", "fileupload") in p


def test_from_to_variants_all_extract():
    for verb in ("changed", "converted", "switched", "swapped",
                 "replaced", "updated"):
        claim = f"the field was {verb} to FileUpload"
        p = _extract_phrases(claim)
        assert ("add", "fileupload") in p, f"missed target on verb={verb!r}: {p}"


def test_generic_to_word_not_falsely_captured():
    """The extractor must not fire for trivially-following words like
    `the`, `a`, `an`, `be` after `to` — that would flood verify_promise
    with meaningless promises."""
    claim = "please update the field to the new name"
    p = _extract_phrases(claim)
    # Neither 'the' nor 'new' should slip in as a target.
    targets = [n for k, n in p if k == "add"]
    assert "the" not in targets
