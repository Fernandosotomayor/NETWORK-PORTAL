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
