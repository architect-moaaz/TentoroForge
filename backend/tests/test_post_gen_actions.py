"""Post-build chat flow: on completion offer Seed | Validate-Repair; after seeding
show admin creds + offer Validate-Repair | Do-something-else."""
from services.post_gen_actions import post_build_actions, post_seed_actions, admin_credentials

def test_build_complete_offers_seed_and_validate():
    ids = [a["id"] for a in post_build_actions()]
    assert ids == ["seed", "validate_repair"]

def test_after_seed_offers_validate_and_else():
    ids = [a["id"] for a in post_seed_actions()]
    assert ids == ["validate_repair", "something_else"]

def test_default_admin_credentials():
    c = admin_credentials()
    assert c == {"email": "admin@example.com", "password": "admin1234"}

def test_env_override_wins(tmp_path):
    (tmp_path/".env").write_text('DATABASE_URL=x\nSEED_ADMIN_EMAIL=boss@acme.co\nSEED_ADMIN_PASSWORD="s3cret!"\n', encoding="utf-8")
    c = admin_credentials(tmp_path)
    assert c == {"email": "boss@acme.co", "password": "s3cret!"}

def test_actions_are_chat_renderable():
    for a in post_build_actions() + post_seed_actions():
        assert {"id","label","description"} <= set(a)
