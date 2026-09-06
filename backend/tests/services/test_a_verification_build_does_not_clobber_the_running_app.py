"""The check must not break the thing it checks, and must say what it found.

`next build` and `next dev` both own `.next`. The preview node's verification
build ran in the directory of the app being served, rewrote its manifests,
and the served app answered 500 with `routes-manifest.json` missing — while
the build itself failed on the dev server's half-written output. It happened
three times on one project before the shape was fixed: the verification
compiles into its own directory, named by an environment variable every
generated Next config reads.

And when a build does fail, the reason recorded was npm's lockfile warning,
because the runner kept `stderr or stdout` and Next writes warnings to one
and errors to the other. The message now starts at the error.
"""
import pathlib

from services.blueprint import assembly
from services.blueprint.assembly import (
    VERIFY_DIST_DIR, BuildFailed, build_message, verify_build,
)

TEMPLATES = pathlib.Path(assembly.__file__).resolve().parents[2] / "templates"


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_the_build_runs_in_its_own_directory(monkeypatch, tmp_path):
    seen = []
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(kw) or _Proc())
    verify_build(tmp_path)
    assert seen and all(kw["env"]["NEXT_DIST_DIR"] == VERIFY_DIST_DIR for kw in seen)
    assert VERIFY_DIST_DIR != ".next"


def test_every_generated_next_config_reads_that_directory():
    for cfg in ("standalone-app/next.config.js", "app-foundation/next.config.ts"):
        text = (TEMPLATES / cfg).read_text()
        assert 'distDir: process.env.NEXT_DIST_DIR || ".next"' in text, cfg


WARNING = ("⚠ Warning: Next.js inferred your workspace root, but it may not be correct.\n"
           "We detected multiple lockfiles and selected the directory of x.\n"
           "To silence this warning, set `outputFileTracingRoot` in your Next.js config.")
ERROR = ("   Creating an optimized production build ...\n"
         "Failed to compile.\n\n"
         "./src/app/(dashboard)/page.tsx\n"
         "Module not found: Can't resolve '@/lib/nope'\n")


def test_the_message_is_the_error_not_the_warning():
    msg = build_message(ERROR, WARNING)
    assert msg.startswith("Failed to compile.")
    assert "Module not found" in msg
    assert "lockfile" not in msg


def test_a_failure_reports_the_compiler_line_first(monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: _Proc(1, ERROR, WARNING) if "build" in cmd else _Proc())
    try:
        verify_build(tmp_path)
    except BuildFailed as exc:
        first = str(exc).splitlines()[1]
        assert first == "Failed to compile."
    else:
        raise AssertionError("a failed build was reported as success")


def test_ansi_is_stripped_from_the_message():
    assert "\x1b" not in build_message("\x1b[31mError: boom\x1b[0m", "")


def test_assembly_leaves_the_dev_servers_manifests_alone(tmp_path):
    """Assembly clears its own stale caches, never the served `.next` whole."""
    import inspect
    src = inspect.getsource(assembly.assemble)
    assert 'out / ".next" / "cache"' in src
    assert "shutil.rmtree(cache" not in src
