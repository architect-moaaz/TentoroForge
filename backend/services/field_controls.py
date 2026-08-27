"""Single deterministic authority for a form field's CONTROL type.

`resolve_control` is the ONE function that decides which UI control a form field
renders and the control-specific props it carries. The control type is a pure
DERIVATION from the registry column (SQL type, FK target, declared/harvested enum
values) plus an optional semantic hint the registry cannot derive (currency vs
count, email vs plain string) — it is NEVER authored by the LLM.

Both the deterministic form builder (`deterministic_pages._input_for`) and the
post-generation re-typing pass (`semantic_field_types`) call this so they can never
drift. It returns only the control TYPE and control-specific props (optionsFrom,
options, min/step/prefix, input type, …). The caller owns `name`/`label`/validators.

Pure, deterministic, never raises.
"""
from __future__ import annotations

import re

from services.semantic_field_types import (
    _NUMERIC_TYPES,
    _DATE_TYPES,
    _TEXT_TYPES,
    _is_money,
    _is_bool_name,
    _name_tokens,
    _NAME_MONEY_RE,
    _NAME_QTY_RE,
    _NAME_DATE_RE,
    _NAME_TEXT_RE,
    _NAME_FILE_RE,
    _is_password_name,
)

# Semantic hints that mean "this column holds an uploaded document/file/image",
# stored as a text/varchar URL. Any of these -> FileUpload.
_FILE_SEMANTICS = {"file", "upload", "document", "attachment"}

# Integer vs decimal split inside _NUMERIC_TYPES: an integer gets a unit stepper
# (step 1); a decimal/float/money type allows fractional cents (step 0.01).
_INTEGER_TYPES = {
    "integer", "int", "int2", "int4", "int8", "bigint", "smallint",
    "serial", "bigserial",
}

# SQL types a numeric-flavoured semantic hint (currency/percent) is compatible with.
# The hint is judgment the registry can't derive, but it must not fight a real column
# type — a `currency` hint on a varchar column is a mistake and is ignored.
_TEXTUAL_TYPES = {"varchar", "char", "text", "string", ""}


def _fk_slug(col: str) -> str:
    """Kebab-case, pluralised slug for an FK column / target entity — matches
    `deterministic_pages._fk_slug` exactly (roomId -> rooms, Room -> rooms).
    Replicated (not imported) to keep this module free of a circular import with
    the deterministic builder that calls it."""
    stem = re.sub(r"(_id|Id)$", "", col or "")
    stem = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", stem).lower().replace("_", "-")
    return stem + ("" if stem.endswith("s") else "s")


def _is_fk_name(name: str) -> bool:
    """A column name reads as a foreign key when it ends in `Id`/`_id` (but the bare
    primary key `id` does not)."""
    n = name or ""
    if n.lower() == "id":
        return False
    return n.endswith("Id") or n.endswith("_id")


def _norm_type(sql_type: str) -> str:
    return str(sql_type or "").strip().lower()


def _numeric_compatible(t: str) -> bool:
    return t in _NUMERIC_TYPES or t == ""


def _textual_compatible(t: str) -> bool:
    # Textual hints (email/phone/url/multiline/color/rating) must not override a real
    # numeric/date/boolean column; they apply on string-ish or unknown columns.
    return t in _TEXTUAL_TYPES or t in _TEXT_TYPES


def _semantic_control(semantic_type: str, t: str) -> tuple[str, dict] | None:
    """Control for a semantic hint, or None when the hint is empty or incompatible
    with the real SQL type `t`."""
    s = str(semantic_type or "").strip().lower()
    if not s:
        return None
    if s == "currency":
        if not _numeric_compatible(t):
            return None
        # Spec B3: right-align + tabular-nums so amounts line up in a column
        # and feel like a real currency input, not a bare NumberInput.
        return "NumberInput", {"min": 0, "step": 0.01, "prefix": "$",
                                "showSteppers": False, "align": "right",
                                "tabularNums": True}
    if s == "percent":
        if not _numeric_compatible(t):
            return None
        return "NumberInput", {"min": 0, "max": 100, "step": 0.01, "suffix": "%",
                                "align": "right", "tabularNums": True}
    if s == "email":
        return ("Input", {"type": "email"}) if _textual_compatible(t) else None
    if s == "phone":
        return ("Input", {"type": "tel"}) if _textual_compatible(t) else None
    if s == "url":
        return ("Input", {"type": "url"}) if _textual_compatible(t) else None
    if s in ("multiline", "richtext"):
        return ("Textarea", {}) if _textual_compatible(t) else None
    if s == "color":
        return ("ColorPicker", {}) if _textual_compatible(t) else None
    if s == "rating":
        # A rating is a small integer OR a plain/unknown column — never a date/bool.
        if t in _NUMERIC_TYPES or _textual_compatible(t):
            return "Rating", {}
        return None
    if s in _FILE_SEMANTICS:
        # A document/file/image column, stored as a text/varchar URL.
        return "FileUpload", {}
    if s in ("city", "place", "location", "address", "plaintext", "text"):
        # A place/name column — the LLM's plan is explicitly telling us this is
        # a text value, not a date/number/boolean. Force a plain Input so a
        # name like "Based At" can't trip the DatePicker heuristic on step 5.
        # Only applies when the underlying SQL type IS textual/unknown, per
        # `_textual_compatible` — never overrides a real numeric/date column.
        return ("Input", {}) if _textual_compatible(t) else None
    return None


def resolve_control(
    *,
    name: str,
    sql_type: str = "",
    not_null: bool = False,
    fk_target: str | None = None,
    options: list[str] | None = None,
    semantic_type: str | None = None,
) -> tuple[str, dict]:
    """The single authority for a form field's control type + control props.

    Priority (highest first):
      1. FK        -> Select bound to the target's rows via `optionsFrom`.
      2. enum      -> Select over the declared/harvested literal values.
      3. semantic  -> the hint's control, but ONLY when compatible with `sql_type`.
      4. SQL type  -> Switch / DatePicker / NumberInput / Textarea from the real type.
      5. name      -> anchored money/qty/date/bool/long-text heuristics (text/unknown
                      columns only — a real SQL type already won at step 4).
      6. default   -> plain Input.

    `not_null` is accepted for signature symmetry with the field model but does not
    affect the CONTROL type (it drives `validators.required`, owned by the caller).

    Returns (control, props). Props never include name/label/validators.
    """
    t = _norm_type(sql_type)

    # 0. First-class money — a plan `type: "money"` (or explicit `semantic_type:
    #    "money"`) is authoritative. Slice 2 of the banking-app work: banking
    #    columns need a MoneyInput that carries the currency chip alongside the
    #    amount, not a bare NumberInput with a `$` prefix (which throws away the
    #    currency half and silently defaults to USD in the UI). The DB half —
    #    the sibling `<field>_currency` column — is emitted by the schema builder.
    #    Runs FIRST so a plan's declared money type beats every downstream heuristic.
    _sem = str(semantic_type or "").strip().lower()
    if t == "money" or t == "currency" or _sem in ("money", "currency"):
        return "MoneyInput", {}

    # 1. Foreign key -> relational Select. `optionsFrom` MUST be the object form
    #    {source, value, label}; the renderer's expandOptionsFrom rejects a string.
    if fk_target or _is_fk_name(name):
        source = _fk_slug(fk_target) if fk_target else _fk_slug(name)
        return "Select", {"optionsFrom": {"source": source, "value": "id", "label": "name"}}

    # 2. Declared / harvested enum -> Select over the real values.
    vals = [str(v) for v in (options or []) if v not in (None, "")]
    if vals:
        return "Select", {"options": [{"value": v, "label": v} for v in vals]}

    # 2b. Document / file / image column. Stored as a text/varchar URL (or storage
    #     key/path), so it MUST be caught here — before the text→Textarea return and
    #     the varchar name-heuristic block below, both of which would swallow it into a
    #     Textarea/Input. Fires on an explicit file/upload/document/attachment semantic
    #     hint OR a document-noun column name, regardless of sql_type. It is not an FK
    #     (`*Id`) and not an enum, so those higher-priority steps already declined it.
    if str(semantic_type or "").strip().lower() in _FILE_SEMANTICS \
            or _NAME_FILE_RE.search(_name_tokens(name)):
        return "FileUpload", {}

    # 3. Semantic hint (judgment the registry can't derive) — compatible hints only.
    hinted = _semantic_control(semantic_type or "", t)
    if hinted is not None:
        return hinted

    # 4. Real SQL column type wins over any name heuristic.
    if t == "boolean" or t == "bool":
        return "Switch", {}
    if t in _DATE_TYPES:
        return "DatePicker", {}
    if t in _NUMERIC_TYPES:
        if _is_money(name, t):
            return "NumberInput", {"min": 0, "step": 0.01, "prefix": "$",
                                    "showSteppers": False, "align": "right",
                                    "tabularNums": True}
        if t in _INTEGER_TYPES:
            return "NumberInput", {"min": 0, "step": 1}
        return "NumberInput", {"min": 0, "step": 0.01}
    if t in _TEXT_TYPES:
        # Postgres `text` is a short-string type as often as a long-form one
        # (name/email/password/title are routinely `text` in Drizzle). Fall
        # through to the NAME heuristics below so we only pick Textarea for
        # genuinely long-form column names (description/notes/bio/…).
        # Passwords are text-typed but must render masked.
        if _is_password_name(name):
            return "Input", {"type": "password"}
        toks = _name_tokens(name)
        if _NAME_TEXT_RE.search(toks):
            return "Textarea", {}
        return "Input", {}

    # 5. Name fallback — ONLY for varchar/char/unknown columns, anchored to whole
    #    word tokens so mid-word substrings ("stAGE", "candiDATE") can't fire.
    if t in ("varchar", "char", "string", ""):
        toks = _name_tokens(name)
        if _NAME_MONEY_RE.search(toks):
            return "NumberInput", {"min": 0, "step": 0.01, "prefix": "$", "showSteppers": False}
        if _NAME_QTY_RE.search(toks):
            return "NumberInput", {"min": 0, "step": 1}
        if _NAME_DATE_RE.search(toks):
            return "DatePicker", {}
        if _is_bool_name(name):
            return "Switch", {}
        if _NAME_TEXT_RE.search(toks):
            return "Textarea", {}

    # 6. Default.
    return "Input", {}
