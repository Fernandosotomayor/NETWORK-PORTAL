"""Service to interface with a local Git repository for switch backup change history."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Configure git to trust all directories once at module load time.
# This prevents "dubious ownership" errors inside Docker containers where
# volume-mounted directories are owned by a different user (root vs ubuntu).
try:
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", "*"],
        capture_output=True,
        check=False,
    )
except Exception:
    pass


@dataclass(slots=True)
class FileChange:
    """Represents a change to a switch backup file at a specific commit."""

    commit_hash: str
    author: str
    date: str
    message: str
    filename: str


def run_git_command(cwd: Path, args: list[str]) -> str:
    """Execute a git command in the specified directory and return stdout."""
    try:
        res = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        return res.stdout
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def get_file_history(git_repo_path: Path, filename: str) -> list[FileChange]:
    """Retrieve the commit history for a specific backup configuration file."""
    if not git_repo_path.exists():
        return []

    stdout = run_git_command(
        git_repo_path,
        [
            "log",
            "--follow",
            "--format=%H|%ad|%an|%s",
            "--date=iso-strict",
            "--",
            filename,
        ],
    )

    history: list[FileChange] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", maxsplit=3)
        if len(parts) >= 4:
            history.append(
                FileChange(
                    commit_hash=parts[0],
                    date=parts[1],
                    author=parts[2],
                    message=parts[3],
                    filename=filename,
                )
            )
    return history


def get_file_diff(git_repo_path: Path, filename: str, commit_hash: str) -> str:
    """Get the diff for a configuration file in a specific commit."""
    if not git_repo_path.exists():
        return ""

    # Try diffing with parent commit first
    diff = run_git_command(
        git_repo_path,
        ["diff", f"{commit_hash}~1", commit_hash, "--", filename],
    )
    if not diff:
        # Fallback to git show for the initial commit in the repo
        diff = run_git_command(
            git_repo_path,
            ["show", commit_hash, "--", filename],
        )
    return diff


def get_recent_changes(git_repo_path: Path, limit: int = 50) -> list[FileChange]:
    """Get a global list of recent file modifications in the Git repository."""
    if not git_repo_path.exists():
        return []

    stdout = run_git_command(
        git_repo_path,
        [
            "log",
            "--name-only",
            "--format=%H|%ad|%an|%s",
            "--date=iso-strict",
            "-n",
            str(limit),
        ],
    )

    changes: list[FileChange] = []
    current_commit: list[str] | None = None

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            parts = line.split("|", maxsplit=3)
            if len(parts) >= 4:
                current_commit = parts
        elif current_commit is not None:
            changes.append(
                FileChange(
                    commit_hash=current_commit[0],
                    date=current_commit[1],
                    author=current_commit[2],
                    message=current_commit[3],
                    filename=line,
                )
            )
    return changes


def get_last_global_backup_time(git_repo_path: Path) -> str:
    """Retrieve a user-friendly timestamp of the latest commit in the repository."""
    import datetime
    if not git_repo_path.exists() or not (git_repo_path / ".git").exists():
        return "N/A"
    
    stdout = run_git_command(
        git_repo_path,
        ["log", "-1", "--format=%cd", "--date=iso-strict"],
    )
    val = stdout.strip()
    
    def format_friendly_datetime(dt_obj: datetime.datetime) -> str:
        now = datetime.datetime.now(dt_obj.tzinfo)
        if dt_obj.date() == now.date():
            return f"Hoy {dt_obj.strftime('%I:%M %p')}"
        elif dt_obj.date() == now.date() - datetime.timedelta(days=1):
            return f"Ayer {dt_obj.strftime('%I:%M %p')}"
        else:
            return dt_obj.strftime("%d/%m %I:%M %p")

    if not val:
        try:
            cfg_files = list(git_repo_path.glob("*.cfg"))
            if cfg_files:
                latest_mtime = max(f.stat().st_mtime for f in cfg_files)
                dt = datetime.datetime.fromtimestamp(latest_mtime)
                return format_friendly_datetime(dt)
        except Exception:
            return "N/A"
    
    try:
        dt = datetime.datetime.fromisoformat(val)
        dt_local = dt.astimezone()
        return format_friendly_datetime(dt_local)
    except Exception:
        return val[:16].replace("T", " ")


# ---------------------------------------------------------------------------
# In-memory cache for last commit per file
# ---------------------------------------------------------------------------
_last_commit_cache: dict[str, dict | None] = {}
_cache_populated = False


def populate_last_commit_cache(git_repo_path: Path) -> None:
    """Pre-populate the commit cache for ALL .cfg files in a single git log call.

    Instead of spawning one ``git log`` subprocess per switch (which blocked
    the FastAPI event loop for several seconds), this reads the full commit
    history in one pass and stores the *first* (most recent) commit seen for
    each filename.
    """
    global _last_commit_cache, _cache_populated

    if not git_repo_path.exists() or not (git_repo_path / ".git").exists():
        _cache_populated = True
        return

    stdout = run_git_command(
        git_repo_path,
        [
            "log",
            "--name-only",
            "--format=%H|%ad|%an|%s",
            "--date=iso-strict",
        ],
    )

    if not stdout:
        _cache_populated = True
        return

    current_commit: list[str] | None = None
    seen_files: set[str] = set()

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            parts = line.split("|", maxsplit=3)
            if len(parts) >= 4:
                current_commit = parts
        elif current_commit is not None:
            # Only keep the first (newest) commit per file
            cache_key = f"{git_repo_path}:{line}"
            if cache_key not in seen_files:
                seen_files.add(cache_key)
                _last_commit_cache[cache_key] = {
                    "hash": current_commit[0][:7],
                    "date": current_commit[1],
                    "author": current_commit[2],
                    "message": current_commit[3],
                }

    _cache_populated = True
    LOGGER.info(
        "Populated last-commit cache with %d files in a single git-log pass.",
        len(seen_files),
    )


def clear_last_commit_cache() -> None:
    """Clear the cached commit details so they are re-populated on next access."""
    global _last_commit_cache, _cache_populated
    _last_commit_cache.clear()
    _cache_populated = False
    LOGGER.info("Cleared last commit cache.")


def get_last_commit_for_file(git_repo_path: Path, filename: str) -> dict | None:
    """Retrieve details of the last commit for a specific file.

    On first call the entire commit history is read once and cached.
    Subsequent calls return instantly from the in-memory cache.
    """
    global _cache_populated

    if not _cache_populated:
        populate_last_commit_cache(git_repo_path)

    cache_key = f"{git_repo_path}:{filename}"
    return _last_commit_cache.get(cache_key)

