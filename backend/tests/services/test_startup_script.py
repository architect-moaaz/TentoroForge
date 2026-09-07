"""start.sh generator: collision-proof DB port + DATABASE_URL available to all
CLI steps (drizzle-kit, tsx seed, next). Guards the two standalone-run bugs."""
import subprocess
import tempfile
from pathlib import Path

from services.runtime_injector import _generate_startup_script


def _script(tmp_path) -> str:
    _generate_startup_script(Path(tmp_path))
    return (Path(tmp_path) / "start.sh").read_text(encoding="utf-8")


def test_generated_start_sh_is_valid_bash(tmp_path):
    _generate_startup_script(tmp_path)
    p = tmp_path / "start.sh"
    assert p.stat().st_mode & 0o111  # executable
    r = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_picks_free_port_and_exports_database_url(tmp_path):
    s = _script(tmp_path)
    assert "is_free()" in s and "seq 5432 5600" in s          # free-port scan
    assert 'export DATABASE_URL=' in s                         # all CLI steps see it
    assert "export DB_PORT" in s


def test_writes_env_for_cli_tools_and_syncs_env_local(tmp_path):
    s = _script(tmp_path)
    # .env is auto-loaded by docker compose + drizzle-kit (which ignore .env.local)
    assert "> .env\n" in s
    assert "printf 'DATABASE_URL=%s" in s and ".env.local" in s


def test_does_not_swallow_docker_errors_and_renders_colours(tmp_path):
    s = _script(tmp_path)
    assert "up -d 2>/dev/null" not in s        # errors must surface
    assert "printf '%b" in s                    # colours render (not literal \\033)
