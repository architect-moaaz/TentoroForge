"""Git operations for project versioning."""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def git_init(output_dir: str) -> None:
    """Initialize a git repository in the output directory."""
    proc = await asyncio.create_subprocess_exec(
        "git", "init",
        cwd=output_dir,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    # Create .gitignore
    gitignore = Path(output_dir) / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("node_modules/\n.next/\n.env\n")


#: Trailer key that records WHICH actor produced a commit. Without it
#: nothing could tell a Smith commit from a visual-editor save, so
#: `patch_history.revert_last_patch` reverting "HEAD" could undo the
#: USER'S save and report it as undoing Smith's own change (register
#: S24-6). Read by :func:`services.patch_history.commit_actor`.
COMMIT_ACTOR_TRAILER = "Forge-Actor"


async def git_commit(
    output_dir: str,
    message: str,
    *,
    actor: str | None = None,
    paths: list[str] | None = None,
) -> str | None:
    """Stage changes and commit. Returns the commit hash or None on failure.

    ``actor`` records who authored the change (``"smith"``, ``"editor"``,
    …) as a ``Forge-Actor:`` trailer, so later passes can tell whose
    commit HEAD is. Omitting it leaves the commit unattributed, which
    readers must treat as "unknown", never as "mine".

    ``paths`` limits staging to the files the caller actually edited.
    Without it this stages the ENTIRE working tree (``git add -A``), so
    any work the user has in progress under ``output_dir`` is swept into
    a commit attributed to Smith (register SX-3). Paired with a revert
    that path, that meant Smith could commit the user's uncommitted work
    and then destroy it on "undo that" — with no copy anywhere, because
    it was never separately committed. Every seam already computes
    ``edited_paths``; pass them.
    """
    if actor:
        message = f"{message.rstrip()}\n\n{COMMIT_ACTOR_TRAILER}: {actor}"

    clean = [p for p in (paths or []) if isinstance(p, str) and p.strip()]
    if clean:
        add_args = ["git", "add", "--", *clean]
    else:
        add_args = ["git", "add", "-A"]
        logger.warning(
            "git_commit staging the WHOLE working tree in %s (no `paths` given) "
            "— any uncommitted user work there will be swept into this commit: %r",
            output_dir, message.splitlines()[0] if message else "",
        )
    proc = await asyncio.create_subprocess_exec(
        *add_args,
        cwd=output_dir,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, add_err = await proc.communicate()
    if proc.returncode != 0:
        logger.error(
            "git_commit: staging failed in %s (%s): %s",
            output_dir, " ".join(add_args), (add_err or b"").decode(errors="replace")[:400],
        )
        return None

    # Check if there are staged changes
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--cached", "--quiet",
        cwd=output_dir,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode == 0:
        # No changes to commit
        return None

    # Commit
    proc = await asyncio.create_subprocess_exec(
        "git", "commit", "-m", message,
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    if proc.returncode != 0:
        return None

    # Get commit hash
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD",
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip() if proc.returncode == 0 else None


async def git_get_head(output_dir: str) -> str | None:
    """Get current HEAD commit hash."""
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD",
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip() if proc.returncode == 0 else None


async def git_log(output_dir: str, limit: int = 20) -> list[dict]:
    """Return recent git log entries."""
    proc = await asyncio.create_subprocess_exec(
        "git", "log", f"--max-count={limit}",
        "--format=%H|%s|%ai",
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return []

    entries = []
    for line in stdout.decode().strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            entries.append({
                "hash": parts[0],
                "message": parts[1],
                "date": parts[2],
            })
    return entries


async def git_diff_files(output_dir: str) -> list[str]:
    """Return list of changed files (staged + unstaged)."""
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--name-only", "HEAD",
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return []
    return [f for f in stdout.decode().strip().split("\n") if f]


async def git_revert(output_dir: str) -> str | None:
    """Revert the last commit. Returns the new HEAD hash or None on failure."""
    proc = await asyncio.create_subprocess_exec(
        "git", "revert", "--no-edit", "HEAD",
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return None

    # Get new HEAD
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD",
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip() if proc.returncode == 0 else None
