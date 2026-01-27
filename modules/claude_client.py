import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from claude_code_sdk import (
    ClaudeCodeOptions,
    SystemMessage,
    AssistantMessage,
    UserMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from config.v2_compat import ClaudeCompatConfig
from modules.im.formatters import BaseMarkdownFormatter, SlackFormatter


logger = logging.getLogger(__name__)


class ClaudeClient:
    def __init__(
        self,
        config: ClaudeCompatConfig,
        formatter: Optional[BaseMarkdownFormatter] = None,
    ):
        self.config = config
        self.formatter = formatter or SlackFormatter()
        self.options = ClaudeCodeOptions(
            permission_mode=config.permission_mode,  # type: ignore[arg-type]
            cwd=config.cwd,
            system_prompt=config.system_prompt,
        )  # type: ignore[arg-type]

    def format_message(
        self, message, get_relative_path: Optional[Callable[[str], str]] = None
    ) -> str:
        """Format different types of messages according to specified rules"""
        try:
            if isinstance(message, SystemMessage):
                return self._format_system_message(message)
            elif isinstance(message, AssistantMessage):
                return self._format_assistant_message(message, get_relative_path)
            elif isinstance(message, UserMessage):
                return self._format_user_message(message, get_relative_path)
            elif isinstance(message, ResultMessage):
                return self._format_result_message(message)
            else:
                return self.formatter.format_warning(
                    f"Unknown message type: {type(message)}"
                )
        except Exception as e:
            logger.error(f"Error formatting message: {e}")
            return self.formatter.format_error(f"Error formatting message: {str(e)}")

    def _process_content_blocks(
        self, content_blocks, get_relative_path: Optional[Callable[[str], str]] = None
    ) -> list:
        """Process content blocks (TextBlock, ToolUseBlock) and return formatted parts"""
        formatted_parts = []

        for block in content_blocks:
            if isinstance(block, TextBlock):
                # Don't escape here - let the formatter handle it during final formatting
                # This avoids double escaping
                formatted_parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_info = self._format_tool_use_block(block, get_relative_path)
                formatted_parts.append(tool_info)
            elif isinstance(block, ToolResultBlock):
                result_info = self._format_tool_result_block(block)
                formatted_parts.append(result_info)

        return formatted_parts

    def _get_relative_path(self, full_path: str) -> str:
        """Convert absolute path to relative path based on ClaudeCode cwd"""
        # Get ClaudeCode's current working directory
        cwd = self.options.cwd or os.getcwd()

        # Normalize paths for consistent comparison
        cwd = os.path.normpath(cwd)
        full_path = os.path.normpath(full_path)

        try:
            # If the path starts with cwd, make it relative
            if full_path.startswith(cwd + os.sep) or full_path == cwd:
                relative = os.path.relpath(full_path, cwd)
                # Use "./" prefix for current directory files
                if not relative.startswith(".") and relative != ".":
                    relative = "./" + relative
                return relative
            else:
                # If not under cwd, just return the path as is
                return full_path
        except Exception as e:
            # Fallback to original path if any error
            logger.debug("Failed to get relative path for %s: %s", full_path, e)
            return full_path

    def _format_tool_use_block(
        self,
        block: ToolUseBlock,
        get_relative_path: Optional[Callable[[str], str]] = None,
    ) -> str:
        """Format ToolUseBlock using formatter"""
        # Prefer caller-provided get_relative_path (per-session cwd), fallback to self
        rel = get_relative_path if get_relative_path else self._get_relative_path
        return self.formatter.format_tool_use(
            block.name, block.input, get_relative_path=rel
        )

    def _format_tool_result_block(self, block: ToolResultBlock) -> str:
        """Format ToolResultBlock using formatter"""
        is_error = bool(block.is_error) if block.is_error is not None else False
        content = block.content if isinstance(block.content, str) else None
        return self.formatter.format_tool_result(is_error, content)

    def _format_system_message(self, message: SystemMessage) -> str:
        """Format SystemMessage using formatter"""
        cwd = message.data.get("cwd", "Unknown")
        session_id = message.data.get("session_id", None)
        return self.formatter.format_system_message(cwd, message.subtype, session_id)

    def _format_assistant_message(
        self,
        message: AssistantMessage,
        get_relative_path: Optional[Callable[[str], str]] = None,
    ) -> str:
        """Format AssistantMessage using formatter"""
        content_parts = self._process_content_blocks(message.content, get_relative_path)
        return self.formatter.format_assistant_message(content_parts)

    def _format_user_message(
        self,
        message: UserMessage,
        get_relative_path: Optional[Callable[[str], str]] = None,
    ) -> str:
        """Format UserMessage using formatter"""
        content_parts = self._process_content_blocks(message.content, get_relative_path)
        return self.formatter.format_user_message(content_parts)

    def _format_result_message(self, message: ResultMessage) -> str:
        """Format ResultMessage using formatter"""
        return self.formatter.format_result_message(
            message.subtype, message.duration_ms, message.result
        )

    def _is_skip_message(self, message) -> bool:
        """Check if the message should be skipped"""
        if isinstance(message, AssistantMessage):
            if not message.content:
                return True
        elif isinstance(message, UserMessage):
            if not message.content:
                return True
        return False

    @staticmethod
    def _get_project_sessions_dir(working_path: str) -> Optional[Path]:
        """Get the Claude sessions directory for a project path."""
        claude_dir = Path.home() / ".claude" / "projects"
        if not claude_dir.exists():
            return None
        normalized = working_path.replace("/", "-").replace("_", "-")
        if normalized.startswith("-"):
            normalized = normalized[1:]
        project_dir = claude_dir / f"-{normalized}"
        if project_dir.exists():
            return project_dir
        search_pattern = working_path.replace("/", "-").replace("_", "-")
        for d in claude_dir.iterdir():
            if d.is_dir() and search_pattern in d.name:
                return d
        return None

    @staticmethod
    def list_sessions(working_path: str) -> List[Dict[str, Any]]:
        """List Claude Code sessions for a given working directory."""
        sessions_dir = ClaudeClient._get_project_sessions_dir(working_path)
        if not sessions_dir:
            return []
        index_file = sessions_dir / "sessions-index.json"
        if not index_file.exists():
            return []
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries", [])
            result = []
            for entry in entries:
                result.append(
                    {
                        "id": entry.get("sessionId", ""),
                        "title": entry.get("summary", "")
                        or entry.get("firstPrompt", "")[:50],
                        "first_prompt": entry.get("firstPrompt", ""),
                        "message_count": entry.get("messageCount", 0),
                        "created": entry.get("created", ""),
                        "modified": entry.get("modified", ""),
                        "git_branch": entry.get("gitBranch", ""),
                    }
                )
            result.sort(key=lambda x: x.get("modified", ""), reverse=True)
            return result
        except Exception as e:
            logger.error(f"Failed to read Claude sessions index: {e}")
            return []

    @staticmethod
    def get_session(session_id: str, working_path: str) -> Optional[Dict[str, Any]]:
        """Get a specific Claude Code session by ID."""
        sessions = ClaudeClient.list_sessions(working_path)
        for s in sessions:
            if s.get("id") == session_id:
                return s
        return None

    @staticmethod
    def get_session_messages(
        session_id: str, working_path: str
    ) -> List[Dict[str, Any]]:
        """Get messages from a Claude Code session."""
        sessions_dir = ClaudeClient._get_project_sessions_dir(working_path)
        if not sessions_dir:
            return []
        session_file = sessions_dir / f"{session_id}.jsonl"
        if not session_file.exists():
            return []
        messages = []
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            msg = json.loads(line)
                            messages.append(msg)
                        except json.JSONDecodeError:
                            continue
            return messages
        except Exception as e:
            logger.error(f"Failed to read Claude session file: {e}")
            return []
