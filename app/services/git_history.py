"""Service to interface with a local Git repository for switch backup change history."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


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
        return format_friendly_datetime(dt)
    except Exception:
        return val[:16].replace("T", " ")


_last_commit_cache: dict[str, dict | None] = {}


def clear_last_commit_cache() -> None:
    """Clear the cached commit details."""
    global _last_commit_cache
    _last_commit_cache.clear()
    LOGGER.info("Cleared last commit cache.")


def get_last_commit_for_file(git_repo_path: Path, filename: str) -> dict | None:
    """Retrieve details of the last commit for a specific file."""
    cache_key = f"{git_repo_path}:{filename}"
    if cache_key in _last_commit_cache:
        return _last_commit_cache[cache_key]

    if not git_repo_path.exists() or not (git_repo_path / ".git").exists():
        return None
    
    try:
        stdout = run_git_command(
            git_repo_path,
            [
                "log",
                "-1",
                "--format=%H|%ad|%an|%s",
                "--date=iso-strict",
                "--",
                filename,
            ],
        )
        val = stdout.strip()
        if not val:
            res = None
        else:
            parts = val.split("|", maxsplit=3)
            if len(parts) >= 4:
                res = {
                    "hash": parts[0][:7],
                    "date": parts[1],
                    "author": parts[2],
                    "message": parts[3],
                }
            else:
                res = None
    except Exception:
        LOGGER.exception(f"Failed to get last commit for {filename}")
        res = None

    _last_commit_cache[cache_key] = res
    return res

