"""
Git diff snapshot and Gist service for tracking incremental changes.

This module provides:
1. Snapshot mechanism to capture git state before/after agent operations
2. Incremental diff calculation (version2 vs version1)
3. Per-file diff grouping for better readability
4. GitHub Gist creation for sharing diffs
"""

import asyncio
import logging
import tempfile
import os
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class FileDiffInfo:
    """Information about changes in a single file."""

    path: str
    insertions: int = 0
    deletions: int = 0
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False
    diff_content: str = ""


@dataclass
class DiffSnapshot:
    """Snapshot of git diff state at a point in time."""

    timestamp: datetime
    working_path: str
    # Map of file path -> file content hash or diff content
    file_states: Dict[str, str] = field(default_factory=dict)
    # Raw diff output for comparison
    raw_diff: str = ""
    # Stat output
    stat_output: str = ""


# Global storage for snapshots per session
_diff_snapshots: Dict[str, DiffSnapshot] = {}


async def get_git_diff(working_path: str) -> Tuple[str, str]:
    """
    Get git diff output from the working directory.

    Returns:
        Tuple of (stat_output, diff_output)
    """
    try:
        stat_process = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            "--stat",
            cwd=working_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stat_stdout, _ = await stat_process.communicate()
        stat_output = stat_stdout.decode("utf-8", errors="replace").strip()

        diff_process = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            cwd=working_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        diff_stdout, _ = await diff_process.communicate()
        diff_output = diff_stdout.decode("utf-8", errors="replace")

        return stat_output, diff_output

    except Exception as e:
        logger.error(f"Error getting git diff: {e}", exc_info=True)
        return "", ""


async def save_diff_snapshot(
    session_key: str, working_path: str
) -> Optional[DiffSnapshot]:
    """
    Save current git diff state as a snapshot before agent starts.

    Args:
        session_key: Unique key for the session (e.g., channel_id:thread_ts)
        working_path: Git repository path

    Returns:
        The saved snapshot, or None if failed
    """
    try:
        stat_output, diff_output = await get_git_diff(working_path)

        snapshot = DiffSnapshot(
            timestamp=datetime.now(),
            working_path=working_path,
            raw_diff=diff_output,
            stat_output=stat_output,
        )

        # Parse file states from diff
        if diff_output:
            current_file = None
            for line in diff_output.split("\n"):
                if line.startswith("diff --git"):
                    # Extract file path
                    parts = line.split(" b/")
                    if len(parts) >= 2:
                        current_file = parts[1]
                        snapshot.file_states[current_file] = ""
                elif current_file:
                    snapshot.file_states[current_file] += line + "\n"

        _diff_snapshots[session_key] = snapshot
        logger.debug(
            f"Saved diff snapshot for {session_key}: {len(snapshot.file_states)} files"
        )
        return snapshot

    except Exception as e:
        logger.error(f"Error saving diff snapshot: {e}", exc_info=True)
        return None


async def get_incremental_diff(
    session_key: str, working_path: str
) -> Tuple[List[FileDiffInfo], str, str]:
    """
    Calculate incremental diff between current state and saved snapshot.

    Returns:
        Tuple of (file_diffs, incremental_diff_content, full_diff_content)
        - file_diffs: List of per-file change info
        - incremental_diff_content: Only changes made this round
        - full_diff_content: All uncommitted changes (for "apply" action)
    """
    try:
        # Get current diff
        current_stat, current_diff = await get_git_diff(working_path)

        if not current_diff.strip():
            return [], "", ""

        # Get previous snapshot
        previous_snapshot = _diff_snapshots.get(session_key)
        previous_diff = previous_snapshot.raw_diff if previous_snapshot else ""

        # Parse current files
        current_files = _parse_diff_to_files(current_diff)
        previous_files = _parse_diff_to_files(previous_diff) if previous_diff else {}

        # Calculate incremental changes
        incremental_files: List[FileDiffInfo] = []
        incremental_diff_parts: List[str] = []

        for file_path, file_diff in current_files.items():
            prev_file_diff = previous_files.get(file_path, "")

            if file_diff != prev_file_diff:
                # This file was changed in this round
                file_info = _parse_file_diff_info(file_path, file_diff)
                incremental_files.append(file_info)
                incremental_diff_parts.append(file_diff)

        # Check for files that were in previous but not in current (reverted)
        # We don't include these in incremental since they're "undone"

        incremental_diff_content = "\n".join(incremental_diff_parts)

        return incremental_files, incremental_diff_content, current_diff

    except Exception as e:
        logger.error(f"Error calculating incremental diff: {e}", exc_info=True)
        return [], "", ""


def _parse_diff_to_files(diff_output: str) -> Dict[str, str]:
    """Parse diff output into per-file sections."""
    files: Dict[str, str] = {}
    current_file = None
    current_content: List[str] = []

    for line in diff_output.split("\n"):
        if line.startswith("diff --git"):
            # Save previous file
            if current_file:
                files[current_file] = "\n".join(current_content)

            # Start new file
            parts = line.split(" b/")
            current_file = parts[1] if len(parts) >= 2 else None
            current_content = [line]
        elif current_file:
            current_content.append(line)

    # Save last file
    if current_file:
        files[current_file] = "\n".join(current_content)

    return files


def _parse_file_diff_info(file_path: str, diff_content: str) -> FileDiffInfo:
    """Parse diff content for a single file into FileDiffInfo."""
    info = FileDiffInfo(path=file_path, diff_content=diff_content)

    for line in diff_content.split("\n"):
        if line.startswith("new file mode"):
            info.is_new = True
        elif line.startswith("deleted file mode"):
            info.is_deleted = True
        elif line.startswith("Binary files"):
            info.is_binary = True
        elif line.startswith("+") and not line.startswith("+++"):
            info.insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            info.deletions += 1

    return info


def clear_diff_snapshot(session_key: str):
    """Clear saved snapshot for a session."""
    if session_key in _diff_snapshots:
        del _diff_snapshots[session_key]
        logger.debug(f"Cleared diff snapshot for {session_key}")


def get_saved_snapshot(session_key: str) -> Optional[DiffSnapshot]:
    """Get saved snapshot for a session."""
    return _diff_snapshots.get(session_key)


def _sanitize_filename(file_path: str) -> str:
    """Convert file path to safe filename for Gist."""
    return file_path.replace("/", "_").replace("\\", "_") + ".diff"


async def create_diff_gist(
    diff_output: str,
    working_path: str,
    description: Optional[str] = None,
    per_file: bool = True,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Create a secret GitHub Gist with the diff content.

    Args:
        diff_output: Raw git diff output
        working_path: Git repository path
        description: Gist description
        per_file: If True, create separate file for each changed file in the Gist

    Returns:
        Tuple of (gist_url, error_message)
    """
    if not diff_output or not diff_output.strip():
        return None, "No diff content"

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_name = os.path.basename(working_path) if working_path else "unknown"

    if not description:
        description = f"AI changes in {project_name} at {timestamp}"

    temp_dir = None
    temp_files: List[str] = []

    try:
        if per_file:
            files_dict = _parse_diff_to_files(diff_output)
            if not files_dict:
                return None, "No files to diff"

            temp_dir = tempfile.mkdtemp(prefix=f"{project_name}-{timestamp}-")

            for file_path, file_diff in files_dict.items():
                safe_name = _sanitize_filename(file_path)
                temp_path = os.path.join(temp_dir, safe_name)
                with open(temp_path, "w") as f:
                    f.write(file_diff)
                temp_files.append(temp_path)
        else:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".diff",
                prefix=f"{project_name}-{timestamp}-",
                delete=False,
            ) as f:
                f.write(diff_output)
                temp_files.append(f.name)

        cmd = ["gh", "gist", "create"] + temp_files + ["-d", description]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            logger.error(f"Failed to create gist: {error_msg}")
            return None, error_msg

        gist_url = stdout.decode("utf-8", errors="replace").strip()
        logger.info(f"Created gist with {len(temp_files)} file(s): {gist_url}")
        return gist_url, None

    except FileNotFoundError:
        return None, "gh CLI not found. Install with: brew install gh"
    except Exception as e:
        logger.error(f"Error creating gist: {e}", exc_info=True)
        return None, str(e)
    finally:
        for f in temp_files:
            try:
                os.unlink(f)
            except Exception:
                pass
        if temp_dir:
            try:
                os.rmdir(temp_dir)
            except Exception:
                pass


async def create_incremental_diff_gist(
    session_key: str,
    working_path: str,
    description: Optional[str] = None,
) -> Tuple[Optional[str], List[FileDiffInfo], Optional[str]]:
    file_diffs, incremental_diff, _ = await get_incremental_diff(
        session_key, working_path
    )

    if not file_diffs:
        return None, [], None

    gist_url, error = await create_diff_gist(
        incremental_diff, working_path, description, per_file=True
    )

    return gist_url, file_diffs, error


async def create_full_diff_gist(
    working_path: str,
    description: Optional[str] = None,
) -> Tuple[Optional[str], str, Optional[str]]:
    stat_output, diff_output = await get_git_diff(working_path)

    if not diff_output.strip():
        return None, "", None

    gist_url, error = await create_diff_gist(
        diff_output, working_path, description, per_file=True
    )

    return gist_url, stat_output, error
