"""Coherence check between Smith's propose_fix `explanation` and its
RFC-6902 `patch`.

Smith emits BOTH a natural-language explanation ("I'll remove the
password field") AND a JSON-Patch to apply. Up to now nothing verified
that the patch actually does what the explanation claims. The failure
mode was direct: he'd say "remove password" while patching an unrelated
Switch — the applier trusted the patch verbatim, wrote the file, and
Smith self-reported "Done."

This module reads high-signal imperative phrases out of the
explanation and checks each patch op against the schema tree. If a
strong verb+noun phrase names a thing the patch never touches, we flag
it. The applier is expected to REJECT any patch with incoherences and
re-ask Smith.

Bias is toward false-negatives — a vague explanation ("I applied the
fix") is not evidence of fabrication and passes through. We only flag
when we're confident the two outputs disagree.
"""
from __future__ import annotations

import re
from typing import Any


# --------------------------------------------------------------------------- #
# Verb → phrases the checker recognises. Kept small on purpose: additional
# aliases are cheap here, and false positives cost a rejected fix (annoying)
# while false negatives let the drift bug slip through (dangerous).
# --------------------------------------------------------------------------- #

# The verb lists include both imperative present ("change") AND past
# tense ("changed") because Smith writes claims in both modes: propose_fix
# explanations use imperative ("change the field to FileUpload"), but
# self-report "answer" strings use past tense ("changed the field from
# Select to FileUpload"). Missing the past-tense forms let a bogus
# "changed to FileUpload" claim slip through verify_promise entirely.
_REMOVE_VERBS = ("remove", "removed", "delete", "deleted", "drop", "dropped",
                 "hide", "hid", "hidden", "strip out", "stripped out",
                 "take out", "took out", "taken out", "get rid of", "got rid of")
_ADD_VERBS = ("add", "added", "insert", "inserted", "append", "appended")
_RENAME_VERBS = ("rename", "renamed", "call", "called", "relabel", "relabeled",
                 "relabelled")
_REPLACE_VERBS = ("replace", "replaced", "swap", "swapped", "change", "changed",
                  "convert", "converted", "switch", "switched", "update", "updated")

# A phrase like "add a status dropdown" — "dropdown" is a UI concept
# that maps to Select. Same idea for a few others. Matching honours
# these aliases in both directions (explanation → component + vice
# versa).
_TYPE_SYNONYMS = {
    "dropdown":   {"select"},
    "select":     {"dropdown"},
    "textbox":    {"input", "text"},
    "input":      {"textbox", "text", "field"},
    "textarea":   {"multiline", "paragraph"},
    "checkbox":   {"switch", "toggle", "boolean"},
    "switch":     {"checkbox", "toggle", "boolean"},
    "toggle":     {"switch", "checkbox", "boolean"},
    "date":       {"datepicker", "calendar"},
    "datepicker": {"date"},
    "button":     {"btn", "cta"},
    "number":     {"numberinput", "numeric"},
    "form":       {"submit"},
    "table":      {"grid", "list"},
    "chart":      {"graph"},
}

# Stopwords in imperative phrases — noise between the verb and the
# real noun ("the", "a", "field", "from", "form", …). Extending this
# is safe: we only strip these when we can't already find the target.
_PHRASE_STOP = {
    "the", "a", "an", "some", "any", "this", "that", "these", "those",
    "please", "kindly",
    "field", "fields", "prop", "props", "property", "properties",
    "column", "columns", "input", "inputs",
    "from", "on", "of", "in", "to", "with", "at",
    "form", "page", "screen", "component", "modal",
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def check_patch_coherence(
    *,
    explanation: str,
    patch: list[dict] | None,
    pre_schema: dict | None,
) -> list[dict]:
    """Return a list of incoherences between the natural-language
    explanation and the RFC-6902 patch.

    Each incoherence is::

        {"kind": "remove"|"add"|"rename"|"replace",
         "expected": <noun the explanation named>,
         "actual":   <what the patch touched>,
         "op_idx":   <position in the patch list>}

    Empty list = the patch and the explanation agree (or the
    explanation was too vague for us to draw a conclusion; we don't
    reject in that case).
    """
    if not isinstance(explanation, str) or not explanation.strip():
        return []
    if not isinstance(pre_schema, dict):
        return []

    phrases = _extract_phrases(explanation)
    if not phrases:
        return []  # vague explanation — no promise to enforce

    # Empty-patch guard: an explanation with a strong verb+noun phrase
    # ("remove password") paired with `patch=[]` is a broken promise —
    # the applier would write nothing and Smith would still self-report
    # "Done." Flag every phrase so the applier's remaining[] carries a
    # concrete "expected X, patch touched (nothing)" line per promise.
    if not isinstance(patch, list) or not patch:
        return [
            {"kind": kind, "expected": noun,
             "actual": "(empty patch — no ops emitted)", "op_idx": -1}
            for kind, noun in phrases
        ]

    incoherences: list[dict] = []
    for kind, expected_noun in phrases:
        matched = False
        for op in patch:
            if not isinstance(op, dict):
                continue
            actual = _op_target_identifiers(op, pre_schema, phrase_kind=kind)
            if _phrase_matches_any(expected_noun, actual) and \
               _op_kind_matches(op.get("op"), kind):
                matched = True
                break
        if not matched:
            incoherences.append({
                "kind": kind,
                "expected": expected_noun,
                "actual": _summarise_patch_targets(patch, pre_schema),
                "op_idx": -1,
            })
    return incoherences


# --------------------------------------------------------------------------- #
# Phrase extraction from the explanation
# --------------------------------------------------------------------------- #

def _extract_phrases(text: str) -> list[tuple[str, str]]:
    """Return a list of (kind, noun) pairs. `kind` is one of `remove`,
    `add`, `rename`, `replace` (mirrors the RFC-6902 op kinds we care
    about). `noun` is the salient noun the verb targeted, normalised.

    Handles both active-voice imperatives ("remove the password field")
    and passive-voice statements ("the password field is removed",
    "password will be removed"). Passive forms appear in Smith's
    "will remove password" explanations and in claim strings passed
    to :func:`services.smith_edit_tools.verify_promise`."""
    out: list[tuple[str, str]] = []
    lower = " " + text.lower() + " "

    # Active-voice imperatives (Smith's propose_fix explanation form).
    for verb in _REMOVE_VERBS:
        for noun in _nouns_after(lower, verb):
            out.append(("remove", noun))
    for verb in _ADD_VERBS:
        for noun in _nouns_after(lower, verb):
            out.append(("add", noun))
    for verb in _RENAME_VERBS:
        for noun in _nouns_after(lower, verb):
            out.append(("rename", noun))
    for verb in _REPLACE_VERBS:
        for noun in _nouns_after(lower, verb):
            out.append(("replace", noun))

    # Passive-voice statements — "the password field is removed",
    # "a status column has been added". Nouns come BEFORE the verb;
    # scan for verb participles and pull the preceding noun-phrase.
    out.extend(_passive_phrases(lower, ("removed", "deleted", "dropped", "hidden"), "remove"))
    out.extend(_passive_phrases(lower, ("added", "inserted", "appended"), "add"))
    out.extend(_passive_phrases(lower, ("renamed", "relabeled"), "rename"))
    out.extend(_passive_phrases(lower, ("replaced", "swapped"), "replace"))

    # "changed from X to Y" — capture the TARGET (Y) as an `add` promise so
    # verify_promise checks Y actually appears in the file. Without this,
    # a claim like "changed from Select to FileUpload" produced no phrase
    # at all (verbs+nouns skipped over `to`), letting Smith's promise slip
    # through unverified. Any `add`-flavored verb triggers it too so
    # "converted to FileUpload" / "switched to FileUpload" also count.
    out.extend(_from_to_targets(lower))
    return out


_FROM_TO_VERBS = ("change", "changed", "convert", "converted", "swap", "swapped",
                  "replace", "replaced", "switch", "switched", "update", "updated",
                  "make", "made", "turn", "turned")


def _from_to_targets(text: str) -> list[tuple[str, str]]:
    """Extract the TARGET noun from a "verb ... to <NOUN>" idiom.
    Returns each target as ``("add", noun)`` — the strongest promise
    verify_promise can hold ("this component MUST appear in the file")."""
    out: list[tuple[str, str]] = []
    verbs_alt = "|".join(re.escape(v) for v in _FROM_TO_VERBS)
    # "verb [anything short] to a/an? <NOUN>"
    # Non-greedy on the middle so "changed X to Y" stops at the first `to`.
    pattern = re.compile(
        r"\b(?:" + verbs_alt + r")\b[^.,;!?]{0,80}?\bto\s+(?:an?\s+)?"
        r"([A-Za-z][A-Za-z0-9_\-]{1,40})",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        target = m.group(1).strip()
        # Skip common connective words that would slip through as false targets.
        if target.lower() in {"the", "a", "an", "be", "have", "do", "make", "get"}:
            continue
        out.append(("add", target.lower()))
    return out


def _passive_phrases(text: str, participles: tuple[str, ...], kind: str) -> list[tuple[str, str]]:
    """Extract (kind, noun) for passive constructions.

    Matches: ``<noun-phrase> (is|are|was|were|will be|has been|have been) <participle>``.
    The noun-phrase is captured up to ~3 words back from the auxiliary
    verb and reduced to its head (same stopword-strip as the active
    branch)."""
    out: list[tuple[str, str]] = []
    for part in participles:
        # Bare `be` was previously accepted as an auxiliary, but that let
        # "... will be removed" match with noun="will" + aux="be" instead
        # of noun="[phrase]" + aux="will be". The bogus noun then never
        # matched the patch and the coherence gate rejected an obviously
        # correct fix. Removed — all real passives use is/are/was/were/
        # will be/has been/have been; a lone "be" isn't grammatical passive
        # anyway ("field be removed" is not English).
        pattern = re.compile(
            r"([a-z0-9_\- ]{2,60}?)\s+(?:is|are|was|were|will\s+be|has\s+been|have\s+been)\s+"
            + re.escape(part) + r"\b",
            re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            phrase = m.group(1).strip()
            noun = _phrase_head(phrase)
            if noun:
                out.append((kind, noun))
    return out


def _nouns_after(text: str, verb: str) -> list[str]:
    """Every noun-phrase (up to ~3 words) that follows the verb.
    Handles multi-word phrases like 'password field', 'status
    dropdown', 'is active switch'."""
    pattern = re.compile(
        r"\b" + re.escape(verb) + r"\b\s+([a-z0-9_ \-]+?)(?=[.,;!?]|(?:\s+(?:and|from|to|with|on|of|in|for)\b)|$)",
        re.IGNORECASE,
    )
    out: list[str] = []
    for m in pattern.finditer(text):
        phrase = m.group(1).strip()
        noun = _phrase_head(phrase)
        if noun:
            out.append(noun)
    return out


def _phrase_head(phrase: str) -> str:
    """Reduce a noun-phrase like 'the password field' to its salient
    noun ('password'). We drop stopwords and take the first
    non-stopword token — Smith consistently puts the important noun
    first. When the phrase ends with 'field'/'input'/'column' etc. and
    only one non-stopword remains, that noun is the head."""
    tokens = [t for t in re.split(r"[\s]+", phrase.strip()) if t]
    non_stop = [t for t in tokens if t not in _PHRASE_STOP]
    if not non_stop:
        return ""
    return non_stop[0]


# --------------------------------------------------------------------------- #
# Op → identifiers touched
# --------------------------------------------------------------------------- #

def _op_target_identifiers(
    op: dict, pre_schema: dict, *, phrase_kind: str = "any",
) -> list[str]:
    """Salient identifiers (name / label / id / type) touched by the op.

    Which "side" of the op we return depends on the explanation's verb:

    * ``add``  → the identifiers on the newly-added value.
    * ``remove`` → the identifiers of the pre-image node being removed.
    * ``rename`` → the PRE-image target only (the thing being renamed);
      the replacement value is intentionally excluded so
      ``rename email to workEmail`` cannot coherently target a
      ``phone`` node just because the new name contains "email".
    * ``replace`` / ``any`` → both sides, so a full-value swap can
      match either the noun being replaced or its replacement.
    """
    ids: list[str] = []
    op_kind = str(op.get("op") or "").lower()
    path = op.get("path")

    if op_kind == "add":
        ids.extend(_extract_ids(op.get("value")))
    elif op_kind in ("remove", "move", "copy"):
        ids.extend(_extract_ids(_resolve_path(pre_schema, path)))
    elif op_kind == "replace":
        ids.extend(_extract_ids(_resolve_path(pre_schema, path)))
        if phrase_kind != "rename":
            ids.extend(_extract_ids(op.get("value")))
    return ids


def _extract_ids(node: Any) -> list[str]:
    """The salient identifier strings under a schema node. Recurses
    one level into `props`. Empty list on non-object inputs."""
    if not isinstance(node, dict):
        # Bare-value replace target (e.g. `.../props/name = "workEmail"`)
        # gets treated as its own identifier.
        return [str(node)] if isinstance(node, str) else []
    out: list[str] = []
    for key in ("name", "label", "id", "type"):
        v = node.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    props = node.get("props")
    if isinstance(props, dict):
        for key in ("name", "label", "id"):
            v = props.get(key)
            if isinstance(v, str) and v:
                out.append(v)
    return out


def _resolve_path(root: dict, path: Any) -> Any:
    """RFC-6901 pointer resolution. Returns None on any resolution
    failure — the coherence check degrades to no-flag rather than
    blocking a valid patch."""
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    parts = path.split("/")[1:]
    cur: Any = root
    for p in parts:
        p = p.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            try:
                cur = cur[int(p)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            if p not in cur:
                return None
            cur = cur[p]
        else:
            return None
    return cur


def _summarise_patch_targets(patch: list[dict], pre_schema: dict) -> str:
    """A short comma-separated summary of what the patch actually
    touched — used only as the `actual` field in an incoherence
    report so the caller can log a meaningful "expected X, patch
    touched Y" line."""
    seen: list[str] = []
    for op in patch:
        if not isinstance(op, dict):
            continue
        for ident in _op_target_identifiers(op, pre_schema, phrase_kind="any"):
            if ident not in seen:
                seen.append(ident)
    return ", ".join(seen[:6]) or "(no identifiable targets)"


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _phrase_matches_any(expected: str, actual_ids: list[str]) -> bool:
    """True when the noun from the explanation resolves against ANY
    identifier the patch op touched. Match is substring on
    normalised strings, extended by the type-synonym table."""
    if not expected or not actual_ids:
        return False
    e = _norm(expected)
    if not e:
        return False
    synonyms = {_norm(s) for s in _TYPE_SYNONYMS.get(expected.lower(), set())}
    for ident in actual_ids:
        a = _norm(ident)
        if not a:
            continue
        # Bidirectional substring — "password" matches "password_hash",
        # and vice versa "email" matches "workEmail".
        if e in a or a in e:
            return True
        for syn in synonyms:
            if syn and (syn in a or a in syn):
                return True
    return False


def check_promise_kept(
    *,
    explanation: str,
    pre_schema: dict | None,
    post_schema: dict | None,
) -> list[dict]:
    """Post-apply gate — did the patch actually change anything the
    explanation promised to change?

    A patch can be structurally valid, pass the pre-apply coherence
    check (because its ops target the right nodes on paper), and STILL
    leave the file byte-identical — e.g. a replace-with-same-value or
    an add-then-remove pair. When the explanation had strong verb+noun
    phrases and the pre/post schemas are identical, the promise is
    broken and the applier should reject → rollback.

    Empty list = the file changed OR the explanation was too vague to
    enforce (false-negative bias, same rule as check_patch_coherence).
    """
    if not isinstance(explanation, str) or not explanation.strip():
        return []
    phrases = _extract_phrases(explanation)
    if not phrases:
        return []
    if pre_schema != post_schema:
        return []  # something changed — the promise may have been kept
    return [
        {"kind": kind, "expected": noun,
         "actual": "(patch produced no diff — the file is unchanged)",
         "op_idx": -1}
        for kind, noun in phrases
    ]


def _op_kind_matches(op_kind: str | None, phrase_kind: str) -> bool:
    """Loose alignment between the RFC-6902 op verb and the
    explanation's verb. We accept `remove` + `remove`, `add` + `add`,
    and treat `replace` as a rename when the target is a scalar
    `name`/`label`/`id` field."""
    if not op_kind:
        return False
    o = op_kind.lower()
    if phrase_kind == "remove": return o == "remove"
    if phrase_kind == "add":    return o == "add"
    if phrase_kind == "replace": return o in ("replace", "move")
    if phrase_kind == "rename":  return o in ("replace", "move")
    return False
