"""Two defaults every generated app inherits from the platform's templates.

E-commerce (forge-v3, 2026-10-09): with no account-type choice offered, the
sign-up route took the role from the request, so anyone could post
`accountType: "Merchant"` and sign up as the merchant; and the shared form
called `onDone` whether the workflow succeeded or not, so the checkout said
"Order confirmed" over a failed order and TStyle's forms shut and lost what
was typed when a save was refused. The safe thing is the default now.
"""
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src"


def test_sign_up_takes_a_role_only_from_the_choice_the_app_offers():
    src = (_SRC / "app" / "api" / "auth" / "signup" / "route.ts").read_text(encoding="utf-8")
    assert ("const role = (ACCOUNT_TYPE_VALUES.length ? data.accountType : undefined) "
            "|| SIGNUP_ROLE || undefined;") in src
    assert "const role = data.accountType || SIGNUP_ROLE" not in src
    # The assembly step still finds the literal it fills with the app's choice.
    assert "const ACCOUNT_TYPES: { value: string }[] = [];" in src


def test_a_form_says_done_only_when_the_workflow_succeeded():
    src = (_SRC / "sdk" / "client.tsx").read_text(encoding="utf-8")
    assert "if (out.ok) onDone?.(out);\n    else onRefused?.(out);" in src
    assert "onRefused?: (result: RunResult) => void;" in src


def test_the_page_writer_is_told_the_forms_two_outcomes():
    import inspect

    from services.blueprint import ui_engineer
    src = inspect.getsource(ui_engineer)
    assert "onRefused?={(r) =>" in src and "success only" in src
