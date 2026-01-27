import asyncio
import logging
import tempfile
import os
from typing import Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


async def create_diff_gist(
    diff_output: str,
    working_path: str,
    description: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Create a secret GitHub Gist with the diff content.

    Returns:
        Tuple of (gist_url, error_message)
    """
    if not diff_output or not diff_output.strip():
        return None, "No diff content"

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_name = os.path.basename(working_path) if working_path else "unknown"

    if not description:
        description = f"AI changes in {project_name} at {timestamp}"

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".diff",
            prefix=f"{project_name}-{timestamp}-",
            delete=False,
        ) as f:
            f.write(diff_output)
            diff_file = f.name

        try:
            process = await asyncio.create_subprocess_exec(
                "gh",
                "gist",
                "create",
                diff_file,
                "-d",
                description,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                logger.error(f"Failed to create gist: {error_msg}")
                return None, error_msg

            gist_url = stdout.decode("utf-8", errors="replace").strip()
            logger.info(f"Created gist: {gist_url}")
            return gist_url, None

        finally:
            try:
                os.unlink(diff_file)
            except Exception:
                pass

    except FileNotFoundError:
        return None, "gh CLI not found. Install with: brew install gh"
    except Exception as e:
        logger.error(f"Error creating gist: {e}", exc_info=True)
        return None, str(e)


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


async def check_and_create_diff_gist(
    working_path: str,
    description: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Check for git changes and create a gist if there are any.

    Returns:
        Tuple of (gist_url, stat_summary, error_message)
    """
    stat_output, diff_output = await get_git_diff(working_path)

    if not stat_output:
        return None, None, None

    gist_url, error = await create_diff_gist(diff_output, working_path, description)

    return gist_url, stat_output, error
