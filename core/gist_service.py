"""
Git diff and Gist service for sharing code changes.
"""

import asyncio
import logging
import tempfile
import os
from typing import Optional, Tuple, Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


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


def _parse_diff_to_files(diff_output: str) -> Dict[str, str]:
    files: Dict[str, str] = {}
    current_file = None
    current_content: List[str] = []

    for line in diff_output.split("\n"):
        if line.startswith("diff --git"):
            if current_file:
                files[current_file] = "\n".join(current_content)

            parts = line.split(" b/")
            current_file = parts[1] if len(parts) >= 2 else None
            current_content = [line]
        elif current_file:
            current_content.append(line)

    if current_file:
        files[current_file] = "\n".join(current_content)

    return files


def _sanitize_filename(file_path: str) -> str:
    return file_path.replace("/", "_").replace("\\", "_") + ".diff"


async def create_diff_gist(
    diff_output: str,
    working_path: str,
    description: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    if not diff_output or not diff_output.strip():
        return None, "No diff content"

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_name = os.path.basename(working_path) if working_path else "unknown"

    if not description:
        description = f"Changes in {project_name} at {timestamp}"

    temp_dir = None
    temp_files: List[str] = []

    try:
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
        return None, "gh CLI not found"
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


async def create_full_diff_gist(
    working_path: str,
    description: Optional[str] = None,
) -> Tuple[Optional[str], str, Optional[str]]:
    stat_output, diff_output = await get_git_diff(working_path)

    if not diff_output.strip():
        return None, "", None

    gist_url, error = await create_diff_gist(diff_output, working_path, description)

    return gist_url, stat_output, error
