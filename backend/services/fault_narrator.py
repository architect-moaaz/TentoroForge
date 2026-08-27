"""SV-STRICT-3 — fault narrator.

Renders a :class:`FaultClassification` (with its :class:`Interaction`
context) into a chat-ready English sentence.

Design principles
-----------------
* Pure — ``(fault, interaction) → str``. No I/O.
* Signature-keyed templates. One template per known signature; fallback
  uses the classifier's own ``hypothesis`` text.
* Never leak signature names or fault-signature jargon into user text.
* Every template names the specific component (label + route) so the
  user can find what's broken.
* Aggregation: :func:`narrate_report` groups per-W-slot for the UI.

The narrator is deliberately templated (not LLM) so the same fault
always reads the same way — the chat feels like the system knows what
it's saying instead of paraphrasing every time.
"""
from __future__ import annotations

from typing import Any, Iterable

from services.fault_classifier import FaultClassification, FaultSignature
from services.interaction_extractor import (
    ButtonInteraction,
    DetailInteraction,
    FormInteraction,
    Interaction,
    ListInteraction,
    RouteInteraction,
)


# ── Templates ────────────────────────────────────────────────────────────
#
# Signature → (template_function). Every template takes (interaction) and
# returns a single, punctuated English sentence. Missing signatures fall
# through to :func:`_fallback`.


def _button_label(i: Interaction) -> str:
    return getattr(i, "label", "(button)")


def _route(i: Interaction) -> str:
    return getattr(i, "route", "(unknown route)")


def _btn_dead_click(i: Interaction) -> str:
    return (f"The '{_button_label(i)}' button on {_route(i)} doesn't do "
            f"anything when clicked — no action is declared for it.")


def _btn_workflow_missing(i: Interaction) -> str:
    target = getattr(getattr(i, "action", None), "workflow_target", None) or "(unknown)"
    return (f"The '{_button_label(i)}' button tries to start the "
            f"{target} workflow, but no request was fired when it was clicked.")


def _btn_nav_target_missing(i: Interaction) -> str:
    target = getattr(getattr(i, "action", None), "navigate_target", None) or "(unknown)"
    return (f"The '{_button_label(i)}' button navigates to {target}, "
            f"but that page doesn't exist.")


def _btn_compute_wrong(i: Interaction) -> str:
    return (f"The '{_button_label(i)}' button computed a value that "
            f"doesn't match the declared formula.")


def _form_submit_500(i: Interaction) -> str:
    target = ""
    submit = getattr(i, "submit", None)
    if submit is not None:
        target = (getattr(submit, "workflow_target", None)
                  or getattr(submit, "dataSource_target", None) or "")
    tail = f" ({target})" if target else ""
    return (f"The '{_button_label(i) if isinstance(i, ButtonInteraction) else _form_label(i)}' "
            f"form on {_route(i)} crashed on submit — the server returned "
            f"a 5xx error{tail}.")


def _form_submit_500_fk(i: Interaction) -> str:
    return (f"The '{_form_label(i)}' form on {_route(i)} failed on submit "
            f"because a referenced record doesn't exist "
            f"(foreign-key violation).")


def _form_submit_400(i: Interaction) -> str:
    return (f"The '{_form_label(i)}' form on {_route(i)} was rejected on "
            f"submit — the fields the form sent don't match what the "
            f"server expected.")


def _form_no_submit_action(i: Interaction) -> str:
    return (f"The '{_form_label(i)}' form on {_route(i)} has no declared "
            f"place to send its data on submit.")


def _list_empty(i: Interaction) -> str:
    ds = getattr(i, "dataSource", "")
    return (f"The table on {_route(i)} came back empty even though data "
            f"was expected (source: {ds}).")


def _list_ds_unresolved(i: Interaction) -> str:
    ds = getattr(i, "dataSource", "")
    return (f"The table on {_route(i)} is bound to '{ds}', but no matching "
            f"data source is registered for the page.")


def _dashboard_blank(i: Interaction) -> str:
    return (f"The dashboard at {_route(i)} rendered blank — no widgets "
            f"produced visible content.")


def _detail_binding(i: Interaction) -> str:
    return (f"The detail page at {_route(i)} loaded, but the record's "
            f"fields didn't populate — a data binding is unresolved.")


def _console_react_31(i: Interaction) -> str:
    return (f"The page at {_route(i)} logged a React #31 error — a value "
            f"is being rendered as text where React expected a component "
            f"(often an unresolved binding placeholder).")


def _console_hydration(i: Interaction) -> str:
    return (f"The page at {_route(i)} produced a hydration mismatch — the "
            f"server-rendered HTML differs from what React expected on "
            f"the client.")


def _route_404(i: Interaction) -> str:
    return f"The page at {_route(i)} is missing — no route responds there."


def _route_401(i: Interaction) -> str:
    return (f"The page at {_route(i)} rejected the verifier's session — "
            f"users who should be signed in can't reach it.")


def _ssr_500(i: Interaction) -> str:
    return (f"The page at {_route(i)} crashed on the server — the render "
            f"threw before HTML could be returned.")


def _ssr_500_unknown_table(i: Interaction) -> str:
    return (f"The page at {_route(i)} tried to query a database table "
            f"that doesn't exist — likely a name mismatch between the "
            f"schema and the code that queries it.")


def _ssr_500_enoent(i: Interaction) -> str:
    return (f"The page at {_route(i)} tried to read a config file at "
            f"runtime that wasn't shipped with the build.")


def _ssr_500_module_not_found(i: Interaction) -> str:
    return (f"The page at {_route(i)} tried to import a module that "
            f"isn't installed.")


def _timeout(i: Interaction) -> str:
    return (f"The verifier gave up waiting for the interaction on "
            f"{_route(i)} to complete.")


def _promise_not_delivered(i: Interaction) -> str:
    # Synthetic interaction encodes the persona in the route:
    #   promise://<persona_id>/<job_id>
    # and the human-readable job label in `.label`. Reconstruct a natural
    # sentence rather than showing the internal URL.
    job = getattr(i, "label", None) or "this"
    persona = _persona_from_synthetic_route(_route(i))
    who = persona.title() if persona else "A persona"
    return (f"{who} said they wanted to “{job}”, but nothing in "
            f"the generated app supports it — no page, form, or "
            f"workflow was created for this job.")


def _persona_from_synthetic_route(route: str) -> str:
    # "promise://member/cancel-booking" -> "member"
    if not route or "://" not in route:
        return ""
    after = route.split("://", 1)[1]
    head = after.split("/", 1)[0]
    return head.replace("-", " ").replace("_", " ")


def _form_label(i: Interaction) -> str:
    # FormInteraction has no direct label; use its selector suffix or "the".
    if hasattr(i, "selector"):
        sel = getattr(i, "selector") or ""
        # extract trailing '<x>' out of "[data-testid='form-x']"
        if "form-" in sel:
            return sel.split("form-", 1)[1].rstrip("']").replace("-", " ").title()
    return "Form"


_TEMPLATES = {
    FaultSignature.BUTTON_NO_ACTION_DECLARED: _btn_dead_click,
    FaultSignature.BUTTON_WORKFLOW_MISSING: _btn_workflow_missing,
    FaultSignature.BUTTON_NAV_TARGET_MISSING: _btn_nav_target_missing,
    FaultSignature.BUTTON_COMPUTE_WRONG_VALUE: _btn_compute_wrong,

    FaultSignature.FORM_SUBMIT_500_GENERIC: _form_submit_500,
    FaultSignature.FORM_SUBMIT_500_FK: _form_submit_500_fk,
    FaultSignature.FORM_SUBMIT_400: _form_submit_400,
    FaultSignature.FORM_NO_SUBMIT_ACTION: _form_no_submit_action,

    FaultSignature.LIST_EMPTY: _list_empty,
    FaultSignature.LIST_DATASOURCE_UNRESOLVED: _list_ds_unresolved,
    FaultSignature.DASHBOARD_BLANK: _dashboard_blank,
    FaultSignature.DETAIL_BINDING_UNRESOLVED: _detail_binding,

    FaultSignature.CONSOLE_REACT_31: _console_react_31,
    FaultSignature.CONSOLE_HYDRATION_MISMATCH: _console_hydration,

    FaultSignature.ROUTE_404_MISSING_SCHEMA: _route_404,
    FaultSignature.ROUTE_401_UNEXPECTED: _route_401,

    FaultSignature.SSR_500_GENERIC: _ssr_500,
    FaultSignature.SSR_500_UNKNOWN_TABLE: _ssr_500_unknown_table,
    FaultSignature.SSR_500_ENOENT_JSON: _ssr_500_enoent,
    FaultSignature.SSR_500_MODULE_NOT_FOUND: _ssr_500_module_not_found,

    FaultSignature.TIMEOUT: _timeout,

    FaultSignature.PROMISE_NOT_DELIVERED: _promise_not_delivered,
}


def _fallback(fault: FaultClassification, i: Interaction) -> str:
    # Never let a jargon signature name reach the user; instead lean on
    # the classifier's own natural-language hypothesis.
    route = _route(i)
    return (f"Something on {route} isn't working correctly: "
            f"{fault.hypothesis.rstrip('.')}.")


# ── Public entry points ──────────────────────────────────────────────────


def narrate(fault: FaultClassification, interaction: Interaction) -> str:
    """One English sentence for one fault. Never raises."""
    tpl = _TEMPLATES.get(fault.signature)
    if tpl is None:
        return _fallback(fault, interaction)
    try:
        return tpl(interaction)
    except Exception:  # noqa: BLE001 — never crash the reporter
        return _fallback(fault, interaction)


def narrate_report(
    pairs: Iterable[tuple[FaultClassification, Interaction]],
) -> dict[str, Any]:
    """Aggregate narrator output for the verify summary card.

    Returns::

        {
          "narratives": [
            {"text": "...", "priority": "...", "signature": "...",
             "w_slot": "...", "component_id": "...", "route": "..."},
            ...
          ],
          "by_w_slot": {
            "when": [<narrative ...>],
            "how":  [<narrative ...>],
            ...
          },
        }

    Downstream (verify_summary + Chat) renders the ``by_w_slot`` groups
    as sections and stamps a severity chip from ``priority``.
    """
    narratives: list[dict[str, Any]] = []
    by_slot: dict[str, list[dict[str, Any]]] = {}

    for fault, interaction in pairs:
        item = {
            "text": narrate(fault, interaction),
            "priority": fault.priority,
            "signature": fault.signature,
            "w_slot": fault.w_slot,
            "component_id": getattr(interaction, "id", ""),
            "route": _route(interaction),
        }
        narratives.append(item)
        by_slot.setdefault(fault.w_slot, []).append(item)

    return {"narratives": narratives, "by_w_slot": by_slot}
