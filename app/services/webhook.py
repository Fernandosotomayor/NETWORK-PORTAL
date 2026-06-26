import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
import urllib.parse
import asyncio
from app.core.config import settings
from parser.main import parse_file_with_metadata
import json
from .oxidized import get_oxidized_nodes
from .git_history import clear_last_commit_cache

LOGGER = logging.getLogger(__name__)

def extract_timestamp(filename: str) -> str:
    # Extracts timestamp in format YYYYMMDDHHMMSS from e.g. CONTABILIDAD_2026-04-16_160404.cfg
    match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{6})", filename)
    if match:
        date_str = match.group(1).replace("-", "")
        time_str = match.group(2)
        return date_str + time_str
    return ""

def run_oxidized_sync() -> dict[str, Any]:
    """Sync backups from the remote repository, copy the latest, and parse them."""
    # Configure git to trust all directories to avoid "dubious ownership" errors inside Docker
    try:
        subprocess.run(["git", "config", "--global", "--add", "safe.directory", "*"], capture_output=True, check=True)
    except Exception:
        LOGGER.exception("Failed to configure git safe directory")

    archive_dir = settings.OXIDIZED_ARCHIVE_DIR
    repo_url = settings.OXIDIZED_REPO_URL
    backups_dir = settings.BACKUPS_GIT_DIR
    output_dir = settings.DATA_DIR
    
    LOGGER.info("Starting Oxidized synchronization task...")

    
    # 1. Ensure target backups dir exists
    backups_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize backups git repository if it doesn't exist
    if not (backups_dir / ".git").exists():
        try:
            LOGGER.info(f"Initializing empty git repository in {backups_dir}")
            subprocess.run(["git", "init", "-b", "main"], cwd=str(backups_dir), capture_output=True, text=True, check=True)
            subprocess.run(["git", "config", "user.name", "Oxidized Sync"], cwd=str(backups_dir), capture_output=True, text=True, check=True)
            subprocess.run(["git", "config", "user.email", "sync@local"], cwd=str(backups_dir), capture_output=True, text=True, check=True)
        except Exception:
            LOGGER.exception("Failed to initialize git repository in backups directory")

    
    # 2. Check/pull remote archive repo
    git_success = False
    try:
        if archive_dir.exists() and (archive_dir / ".git").exists():
            LOGGER.info(f"Running git pull in {archive_dir}")
            subprocess.run(["git", "pull"], cwd=str(archive_dir), capture_output=True, text=True, check=True)
            git_success = True
        else:
            LOGGER.info(f"Cloning {repo_url} into {archive_dir}")
            archive_dir.mkdir(parents=True, exist_ok=True)
            # Use git clone with target directory specified as "." to clone into it
            subprocess.run(["git", "clone", repo_url, "."], cwd=str(archive_dir), capture_output=True, text=True, check=True)
            git_success = True
    except Exception as e:
        LOGGER.exception(f"Git operation failed for main path {archive_dir}. Trying fallback workspace path.")
        fallback_dir = settings.BASE_DIR / "data" / "oxidized-archive"
        try:
            if fallback_dir.exists() and (fallback_dir / ".git").exists():
                LOGGER.info(f"Running git pull in fallback {fallback_dir}")
                subprocess.run(["git", "pull"], cwd=str(fallback_dir), capture_output=True, text=True, check=True)
                archive_dir = fallback_dir
                git_success = True
            else:
                LOGGER.info(f"Cloning {repo_url} into fallback {fallback_dir}")
                fallback_dir.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "clone", repo_url, "."], cwd=str(fallback_dir), capture_output=True, text=True, check=True)
                archive_dir = fallback_dir
                git_success = True
        except Exception as e2:
            LOGGER.exception(f"Fallback Git operation also failed: {e2}")
    
    if not archive_dir.exists():
        LOGGER.error("Failed to acquire latest backups from Git repository.")
        return {"status": "error", "message": "Failed to pull/clone backups"}
    
    # 3. Find latest backup for each switch and copy to backups/
    copied_files: list[Path] = []
    try:
        for path in archive_dir.iterdir():
            if path.is_dir() and not path.name.startswith("."):
                cfg_files = list(path.glob("**/*.cfg"))
                if not cfg_files:
                    continue
                
                latest_file = None
                latest_ts = ""
                
                for f in cfg_files:
                    ts = extract_timestamp(f.name)
                    if ts > latest_ts:
                        latest_ts = ts
                        latest_file = f
                
                if latest_file:
                    dest_file = backups_dir / latest_file.name
                    # Only copy if it doesn't exist or is different/newer
                    if not dest_file.exists() or dest_file.stat().st_mtime < latest_file.stat().st_mtime:
                        shutil.copy2(latest_file, dest_file)
                        copied_files.append(dest_file)
                        LOGGER.info(f"Copied latest backup for {path.name}: {latest_file.name}")
    except Exception:
        LOGGER.exception("Failed copying backup files from archive directory")
        return {"status": "error", "message": "Failed during backup copy phase"}
    
    # 4. Commit changes in the local backups repository if there are any
    if copied_files:
        try:
            # Stage changes
            subprocess.run(["git", "add", "."], cwd=str(backups_dir), capture_output=True, text=True, check=True)
            # Check if there are changes staged
            status_res = subprocess.run(["git", "status", "--porcelain"], cwd=str(backups_dir), capture_output=True, text=True, check=True)
            if status_res.stdout.strip():
                subprocess.run(["git", "commit", "-m", "Automatic: Sync backups from Oxidized"], cwd=str(backups_dir), capture_output=True, text=True, check=True)
                LOGGER.info("Committed new backups in local backups repository.")
        except Exception:
            LOGGER.exception("Failed to commit changes in local backups Git repository")
    
    # 5. Parse updated backups to update normalized_json/
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed_count = 0
    errors_count = 0
    
    cfg_paths = list(backups_dir.glob("*.cfg"))
    for cfg_path in cfg_paths:
        try:
            data = parse_file_with_metadata(cfg_path)
            json_path = output_dir / f"{cfg_path.stem}.json"
            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            parsed_count += 1
        except Exception:
            errors_count += 1
            LOGGER.exception(f"Failed to parse synchronized backup: {cfg_path}")
            
    LOGGER.info(f"Sync complete. Parsed {parsed_count} switches with {errors_count} errors.")
    
    # Delete VLANs cache to force regeneration on next load
    cache_path = settings.BASE_DIR / "data" / "vlans_cache.json"
    if cache_path.exists():
        try:
            cache_path.unlink()
            LOGGER.info("Deleted VLANs cache to trigger update on next load.")
        except Exception:
            LOGGER.exception("Failed to delete VLANs cache file")

    # Clear commit cache since repository has changed
    try:
        clear_last_commit_cache()
    except Exception:
        LOGGER.exception("Failed to clear last commit cache")

    return {
        "status": "success",
        "copied": len(copied_files),
        "parsed": parsed_count,
        "errors": errors_count
    }


def run_ssh_command(cmd: str) -> subprocess.CompletedProcess:
    """Run a shell command on the host VM via SSH."""
    parsed = urllib.parse.urlparse(str(settings.OXIDIZED_URL))
    host = parsed.hostname or "10.40.20.70"
    
    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"ubuntu@{host}",
        cmd
    ]
    LOGGER.info(f"Executing SSH command on {host}: {cmd}")
    res = subprocess.run(ssh_cmd, capture_output=True, text=True, check=True)
    LOGGER.debug(f"SSH output: stdout: {res.stdout.strip()}, stderr: {res.stderr.strip()}")
    return res


_sync_in_progress = False


def is_sync_in_progress() -> bool:
    """Return whether a full synchronization flow is currently running."""
    return _sync_in_progress


async def run_full_oxidized_sync_flow() -> None:
    """
    Executes the full manual sync flow:
    1. Starts the Oxidized container on the VM.
    2. Polls Oxidized nodes status until all switches are finished backing up.
    3. Runs finish_oxidized_publish.sh on the VM (which pushes to git and triggers local sync).
    """
    global _sync_in_progress
    if _sync_in_progress:
        LOGGER.warning("Sync already in progress, ignoring request.")
        return
        
    _sync_in_progress = True
    try:
        LOGGER.info("Starting end-to-end Oxidized sync flow...")
        
        # 1. Start Oxidized container via SSH
        try:
            run_ssh_command("sudo docker compose -f /home/ubuntu/monitoring/docker-compose.oxidized.yml start oxidized")
            LOGGER.info("Successfully started Oxidized container via SSH.")
        except Exception as e:
            LOGGER.error(f"Failed to start Oxidized container via SSH: {str(e)}")
            return

        # 2. Wait/poll Oxidized nodes status
        # Wait 10 seconds initially for the service to start up and load nodes
        await asyncio.sleep(10)
        
        poll_interval = 30
        max_attempts = 90  # 45 minutes max timeout
        
        finished_successfully = False
        
        for attempt in range(1, max_attempts + 1):
            LOGGER.info(f"Polling Oxidized node status (attempt {attempt}/{max_attempts})...")
            try:
                nodes = await get_oxidized_nodes()
                if not nodes:
                    LOGGER.warning("Could not reach Oxidized REST API or nodes list is empty. Retrying...")
                    await asyncio.sleep(poll_interval)
                    continue
                
                # Check how many nodes are still pending (never or fetching status)
                pending_nodes = []
                for node in nodes:
                    status = node.get("status")
                    if status in [None, "never", "fetching", "unknown"]:
                        pending_nodes.append(node.get("name", "Unnamed"))
                
                if not pending_nodes:
                    LOGGER.info("All nodes have finished backup processing!")
                    finished_successfully = True
                    break
                else:
                    LOGGER.info(f"Waiting for {len(pending_nodes)} nodes: {pending_nodes[:5]}...")
            except Exception as e:
                LOGGER.error(f"Error during polling Oxidized nodes: {str(e)}")
                
            await asyncio.sleep(poll_interval)

        if not finished_successfully:
            LOGGER.warning("Oxidized synchronization timed out or failed to complete all nodes. Proceeding to publish.")

        # 3. Publish changes (run finish_oxidized_publish.sh)
        try:
            LOGGER.info("Triggering finish_oxidized_publish.sh on VM via SSH...")
            run_ssh_command("/home/ubuntu/monitoring/finish_oxidized_publish.sh")
            LOGGER.info("Sync flow complete. Host publication script finished.")
        except Exception as e:
            LOGGER.error(f"Failed to run finish_oxidized_publish.sh via SSH: {str(e)}")
    finally:
        _sync_in_progress = False
