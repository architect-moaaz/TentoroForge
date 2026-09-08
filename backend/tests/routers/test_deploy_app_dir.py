"""The deploy ships `<output>/app` for a Blueprint app, not the output root.

A Blueprint app is projected into `<output>/app`; deploying the root failed
vendor refresh with `package.json missing: <output>/package.json`.
"""
from routers.deployments import _deploy_app_dir


def test_prefers_the_app_subdir_when_it_holds_the_app(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}")
    assert _deploy_app_dir(str(tmp_path)) == str(tmp_path / "app")


def test_app_subdir_with_schemas_also_counts(tmp_path):
    (tmp_path / "app" / "src" / "schemas").mkdir(parents=True)
    assert _deploy_app_dir(str(tmp_path)) == str(tmp_path / "app")


def test_legacy_root_app_is_left_at_the_root(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert _deploy_app_dir(str(tmp_path)) == str(tmp_path)


def test_neither_present_returns_the_root_unchanged(tmp_path):
    assert _deploy_app_dir(str(tmp_path)) == str(tmp_path)
