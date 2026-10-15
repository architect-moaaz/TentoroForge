"""The sign-in and sign-up pages are written by the native engineer as a FRAME around the kit's form.

Their words, band and layout are this product's (the web page's); the way in - the session, the account, the
password field - is `SignInForm` / `SignUpForm`, which the screen must place and cannot replace. A screen that
draws its own is refused; with no screen at all, the fixed fallback stays."""
from __future__ import annotations

from services.blueprint import native_engineer as ne
from services.blueprint.native_projection import drawn_auth_files, native_root, project_native

FRAME = '''import { AuthFrame, LanguageSwitch, SignInForm, SwitchAuthLink } from "@/ui";

export default function Screen() {
  return (
    <AuthFrame title="Welcome back" tagline="Every owner, pet and visit, in one calm place." footer={<SwitchAuthLink to="signup" />}>
      <SignInForm />
    </AuthFrame>
  );
}
'''

LOGIN = {"id": "PAGE-009", "name": "Sign In", "route": "/login", "pattern": "auth", "access": "public"}
SIGNUP = {"id": "PAGE-008", "name": "Sign Up", "route": "/signup", "pattern": "auth", "access": "public"}


def doc(rows: list[dict] | None = None) -> dict:
    return {
        "application": {"name": "Paws"}, "mobile": {"native": {"enabled": True}}, "designSystem": {"colors": {"primary": "#6a4c93"}},
        "security": {}, "roles": [], "data": {"entities": []}, "workflows": [], "pages": [LOGIN, SIGNUP],
        "pageCode": [{"page": "PAGE-009", "view": "<h1>Welcome back</h1><p>Every owner, pet and visit, in one calm place.</p>"}],
        "nativeCode": rows or [],
    }


def test_a_drawn_sign_in_replaces_the_fixed_one_and_the_other_keeps_its_fallback(tmp_path):
    d = doc([{"page": "PAGE-009", "screen": FRAME}])
    project_native(d, tmp_path)
    root = native_root(tmp_path)
    assert drawn_auth_files(d) == {"app/login.tsx"}
    assert (root / "app/login.tsx").read_text("utf-8") == 'export { default } from "@/screens/PAGE-009";\n'
    assert (root / "src/screens/PAGE-009.tsx").is_file()
    assert "SignUpForm" in (root / "app/signup.tsx").read_text("utf-8"), "no screen for sign-up: the fallback stays"


def test_a_sign_in_that_goes_gives_the_fallback_back_and_never_an_app_with_no_way_in(tmp_path):
    project_native(doc([{"page": "PAGE-009", "screen": FRAME}]), tmp_path)
    root = native_root(tmp_path)
    project_native(doc(), tmp_path)
    assert "SignInForm" in (root / "app/login.tsx").read_text("utf-8")
    assert not (root / "src/screens/PAGE-009.tsx").exists()


def test_projecting_twice_writes_nothing_the_second_time(tmp_path):
    d = doc([{"page": "PAGE-009", "screen": FRAME}])
    project_native(d, tmp_path)
    assert project_native(d, tmp_path)["files"] == []


def test_the_frame_is_accepted_and_the_form_is_required():
    assert ne._auth_findings(LOGIN, FRAME) == []
    bare = FRAME.replace("<SignInForm />", "")
    assert any("must place `<SignInForm />`" in f for f in ne._auth_findings(LOGIN, bare))
    assert any("<SignUpForm />" in f for f in ne._auth_findings(SIGNUP, FRAME))


def test_a_screen_that_makes_its_own_session_or_password_field_is_refused():
    own = FRAME.replace("<SignInForm />", '<SignInForm /><TextField label="Password" kind="password" value="" onChange={() => {}} />')
    assert any("password field of its own" in f for f in ne._auth_findings(LOGIN, own))
    calls = 'import { useSession } from "@/sdk";\n' + FRAME
    assert any("useSession" in f for f in ne._auth_findings(LOGIN, calls))


def test_any_other_page_is_not_held_to_the_auth_rules():
    assert ne._auth_findings({"id": "PAGE-001", "route": "/jobs", "pattern": "entity_list"}, "export default function S() {}") == []
    assert ne.auth_kind(LOGIN) == "signin" and ne.auth_kind(SIGNUP) == "signup"
    assert ne.auth_kind({"route": "/login", "pattern": "form"}) is None


def test_the_prompt_for_the_sign_in_screen_carries_the_webs_words_and_no_back():
    prompt = ne.user_prompt(doc(), LOGIN)
    assert "sign-in screen" in prompt and "Every owner, pet and visit, in one calm place." in prompt
    assert "has a `back` button" not in prompt and "bottom tabs" not in prompt
    assert "AuthFrame" in ne.system_prompt(doc()) and "SignInForm" in ne.system_prompt(doc())


def test_the_frames_band_is_the_designs_brand_gradient_not_a_flat_colour():
    from pathlib import Path

    kit = Path(__file__).resolve().parents[2] / "templates" / "native"
    auth = (kit / "src/ui/Auth.tsx").read_text("utf-8")
    assert "<GradientBand" in auth and "expo-linear-gradient" in auth
    assert "gradientStart" in (kit / "src/theme.ts").read_text("utf-8"), "the design's own stops, else primary into accent"
    assert '"expo-linear-gradient"' in (kit / "package.json").read_text("utf-8")
    assert "GradientBand" in ne.sdk_guide(), "the writer is told it exists"
