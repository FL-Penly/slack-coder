"""Core controller that coordinates between modules and handlers"""

import asyncio
import os
import logging
from typing import Optional, Dict, Any
from modules.im import BaseIMClient, MessageContext, IMFactory
from modules.im.formatters import SlackFormatter
from modules.agent_router import AgentRouter
from modules.agents import AgentService, ClaudeAgent, CodexAgent, OpenCodeAgent
from modules.claude_client import ClaudeClient
from modules.session_manager import SessionManager
from modules.settings_manager import SettingsManager
from core.handlers import (
    CommandHandlers,
    SessionHandler,
    SettingsHandler,
    MessageHandler,
)
from core.update_checker import UpdateChecker
from core.gist_service import (
    create_incremental_diff_gist,
    create_full_diff_gist,
    clear_diff_snapshot,
)

logger = logging.getLogger(__name__)


class Controller:
    """Main controller that coordinates all bot operations"""

    def __init__(self, config):
        """Initialize controller with configuration"""
        self.config = config

        # Session tracking (must be initialized before handlers)
        self.claude_sessions: Dict[str, Any] = {}
        self.receiver_tasks: Dict[str, asyncio.Task] = {}
        self.stored_session_mappings: Dict[str, str] = {}

        self._consolidated_message_ids: Dict[str, str] = {}
        self._consolidated_message_buffers: Dict[str, str] = {}
        self._consolidated_message_locks: Dict[str, asyncio.Lock] = {}
        self._home_selected_channels: Dict[str, str] = {}

        # Initialize core modules
        self._init_modules()

        # Initialize handlers
        self._init_handlers()

        # Initialize agents (depends on handlers/session handler)
        self._init_agents()

        # Setup callbacks
        self._setup_callbacks()

        # Background task for cleanup
        self.cleanup_task: Optional[asyncio.Task] = None

        # Initialize update checker (use default config if not present)
        from config.v2_config import UpdateConfig

        update_config = getattr(config, "update", None) or UpdateConfig()
        self.update_checker = UpdateChecker(self, update_config)

        # Restore session mappings on startup (after handlers are initialized)
        self.session_handler.restore_session_mappings()

    def _init_modules(self):
        """Initialize core modules"""
        # Create IM client with platform-specific formatter
        self.im_client: BaseIMClient = IMFactory.create_client(self.config)

        # Create platform-specific formatter
        formatter = SlackFormatter()

        # Inject formatter into clients
        self.im_client.formatter = formatter
        self.claude_client = ClaudeClient(self.config.claude, formatter)

        # Initialize managers
        self.session_manager = SessionManager()
        self.settings_manager = SettingsManager()

        # Agent routing
        self.agent_router = AgentRouter.from_file(None, platform=self.config.platform)

        # Default backend preference:
        # If OpenCode is enabled, make it the implicit default backend.
        if self.config.opencode:
            self.agent_router.global_default = "opencode"
            platform_route = self.agent_router.platform_routes.get(self.config.platform)
            if platform_route:
                platform_route.default = "opencode"

        # Inject settings_manager into SlackBot if it's Slack platform
        if self.config.platform == "slack":
            # Import here to avoid circular dependency
            from modules.im.slack import SlackBot

            if isinstance(self.im_client, SlackBot):
                self.im_client.set_settings_manager(self.settings_manager)
                self.im_client.set_controller(self)
                logger.info("Injected settings_manager and controller into SlackBot")

    def _init_handlers(self):
        """Initialize all handlers with controller reference"""
        # Initialize session_handler first as other handlers depend on it
        self.session_handler = SessionHandler(self)
        self.command_handler = CommandHandlers(self)
        self.settings_handler = SettingsHandler(self)
        self.message_handler = MessageHandler(self)

        # Set cross-references between handlers
        self.message_handler.set_session_handler(self.session_handler)

    def _init_agents(self):
        self.agent_service = AgentService(self)
        self.agent_service.register(ClaudeAgent(self))
        if self.config.codex:
            try:
                self.agent_service.register(CodexAgent(self, self.config.codex))
            except Exception as e:
                logger.error(f"Failed to initialize Codex agent: {e}")
        if self.config.opencode:
            try:
                self.agent_service.register(OpenCodeAgent(self, self.config.opencode))
            except Exception as e:
                logger.error(f"Failed to initialize OpenCode agent: {e}")

    def _setup_callbacks(self):
        """Setup callback connections between modules"""
        # Create command handlers dict
        command_handlers = {
            "start": self.command_handler.handle_start,
            "clear": self.command_handler.handle_clear,
            "cwd": self.command_handler.handle_cwd,
            "set_cwd": self.command_handler.handle_set_cwd,
            "settings": self.settings_handler.handle_settings,
            "stop": self.command_handler.handle_stop,
            "sessions": self.command_handler.handle_sessions,
            "diff": self.command_handler.handle_diff,
            "help": self.command_handler.handle_help,
        }

        # Register callbacks with the IM client
        self.im_client.register_callbacks(
            on_message=self.message_handler.handle_user_message,
            on_command=command_handlers,
            on_callback_query=self.message_handler.handle_callback_query,
            on_settings_update=self.handle_settings_update,
            on_change_cwd=self.handle_change_cwd_submission,
            on_routing_update=self.handle_routing_update,
            on_routing_modal_update=self.handle_routing_modal_update,
            on_ready=self._on_im_ready,
            on_app_home_opened=self.handle_app_home_opened,
            on_home_setting_change=self.handle_home_setting_change,
            on_home_edit_env=self.handle_home_edit_env,
            on_home_env_save=self.handle_home_env_save,
            on_home_channel_select=self.handle_home_channel_select,
        )

    async def _on_im_ready(self):
        """Called when IM client is connected and ready.

        Used to restore active poll loops that were interrupted by restart.
        """
        logger.info("IM client ready, checking for active polls to restore...")
        opencode_agent = self.agent_service.agents.get("opencode")
        if opencode_agent and hasattr(opencode_agent, "restore_active_polls"):
            try:
                restored = await opencode_agent.restore_active_polls()
                if restored > 0:
                    logger.info(f"Restored {restored} active OpenCode poll(s)")
            except Exception as e:
                logger.error(f"Failed to restore active polls: {e}", exc_info=True)

        # Start update checker and send any pending post-update notification
        try:
            await self.update_checker.check_and_send_post_update_notification()
            self.update_checker.start()
        except Exception as e:
            logger.error(f"Failed to start update checker: {e}", exc_info=True)

    # Utility methods used by handlers

    def get_cwd(self, context: MessageContext) -> str:
        """Get working directory based on context (channel/chat)
        This is the SINGLE source of truth for CWD
        """
        # Get the settings key based on context
        settings_key = self._get_settings_key(context)

        # Get custom CWD from settings
        custom_cwd = self.settings_manager.get_custom_cwd(settings_key)

        # Use custom CWD if available, otherwise use default from config
        if custom_cwd:
            abs_path = os.path.abspath(os.path.expanduser(custom_cwd))
            if os.path.exists(abs_path):
                return abs_path
            # Try to create it
            try:
                os.makedirs(abs_path, exist_ok=True)
                logger.info(f"Created custom CWD: {abs_path}")
                return abs_path
            except OSError as e:
                logger.warning(
                    f"Failed to create custom CWD '{abs_path}': {e}, using default"
                )

        # Fall back to default from config.json
        default_cwd = self.config.claude.cwd
        if default_cwd:
            return os.path.abspath(os.path.expanduser(default_cwd))

        # Last resort: current directory
        return os.getcwd()

    def _get_settings_key(self, context: MessageContext) -> str:
        """Get settings key based on context"""
        # Slack only in V2
        return context.channel_id

    def _get_target_context(self, context: MessageContext) -> MessageContext:
        """Get target context for sending messages"""
        if self.im_client.should_use_thread_for_reply() and context.thread_id:
            return MessageContext(
                user_id=context.user_id,
                channel_id=context.channel_id,
                thread_id=context.thread_id,
                message_id=context.message_id,
                platform_specific=context.platform_specific,
            )
        return context

    def _get_consolidated_message_key(self, context: MessageContext) -> str:
        settings_key = self._get_settings_key(context)
        thread_key = context.thread_id or context.channel_id
        # Include message_id to distinguish different conversation rounds within same thread
        # Each user message triggers a new round with its own consolidated message
        trigger_id = context.message_id or ""
        return f"{settings_key}:{thread_key}:{trigger_id}"

    def _get_consolidated_message_lock(self, key: str) -> asyncio.Lock:
        if key not in self._consolidated_message_locks:
            self._consolidated_message_locks[key] = asyncio.Lock()
        return self._consolidated_message_locks[key]

    async def clear_consolidated_message_id(
        self, context: MessageContext, trigger_message_id: Optional[str] = None
    ) -> None:
        """Clear consolidated message ID so next log message starts fresh.

        Call this after user answers a question to make subsequent log messages
        appear after the user's reply instead of editing the old consolidated message.

        Args:
            context: The message context
            trigger_message_id: If provided, use this instead of context.message_id
                               for the consolidated key (needed when context is from
                               user's answer message, not original request)
        """
        # Build key with the original trigger message_id if provided
        settings_key = self._get_settings_key(context)
        thread_key = context.thread_id or context.channel_id
        msg_id = (
            trigger_message_id if trigger_message_id else (context.message_id or "")
        )
        key = f"{settings_key}:{thread_key}:{msg_id}"

        # Use the same per-key lock as emit_agent_message to avoid race conditions
        lock = self._get_consolidated_message_lock(key)
        async with lock:
            self._consolidated_message_ids.pop(key, None)
            # Also clear the buffer so we don't append to stale content
            self._consolidated_message_buffers.pop(key, None)

    def _get_consolidated_max_bytes(self) -> int:
        # Slack API hard limit is exactly 4000 BYTES (not characters) for chat.update
        # Chinese/emoji characters take 3-4 bytes each in UTF-8
        return 4000

    def _get_consolidated_split_threshold(self) -> int:
        # When accumulated message exceeds this threshold (in bytes), start a new message
        # to avoid Slack edit failures. Use 90% of max to leave some buffer.
        return 3600

    def _get_text_byte_length(self, text: str) -> int:
        """Get UTF-8 byte length of text (Slack counts bytes, not characters)."""
        return len(text.encode("utf-8"))

    def _get_result_max_chars(self) -> int:
        return 30000

    def _build_result_summary(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        prefix = "Result too long; showing a summary.\n\n"
        suffix = "\n\n…(truncated; see result.md for full output)"
        keep = max(0, max_chars - len(prefix) - len(suffix))
        return f"{prefix}{text[:keep]}{suffix}"

    async def _send_diff_gist_notification(
        self, context: MessageContext, target_context: MessageContext
    ):
        try:
            working_path = self.get_cwd(context)
            session_key = (
                f"{context.channel_id}:{context.thread_id or context.message_id}"
            )

            gist_url, file_diffs, error = await create_incremental_diff_gist(
                session_key, working_path
            )

            if error:
                logger.debug(f"Gist creation skipped or failed: {error}")
                return

            if not gist_url or not file_diffs:
                return

            file_lines = []
            total_insertions = 0
            total_deletions = 0

            for f in file_diffs[:5]:
                if f.is_new:
                    icon = "🆕"
                elif f.is_deleted:
                    icon = "🗑️"
                else:
                    icon = "📄"

                stats = f"+{f.insertions}, -{f.deletions}"
                file_lines.append(f"{icon} `{f.path}` ({stats})")
                total_insertions += f.insertions
                total_deletions += f.deletions

            if len(file_diffs) > 5:
                file_lines.append(f"_... 还有 {len(file_diffs) - 5} 个文件_")

            files_text = "\n".join(file_lines)
            stats_summary = f"+{total_insertions}, -{total_deletions}"

            message = (
                f"📝 *本轮对话修改了 {len(file_diffs)} 个文件* ({stats_summary})\n\n"
                f"{files_text}\n\n"
                f"🔗 <{gist_url}|查看本轮 Diff>"
            )

            from modules.im import InlineKeyboard, InlineButton

            keyboard = InlineKeyboard(
                [
                    [
                        InlineButton(
                            "📊 查看全部变更", callback_data="view_all_changes"
                        ),
                    ]
                ]
            )
            await self.im_client.send_message_with_buttons(
                target_context, message, keyboard
            )

            clear_diff_snapshot(session_key)

        except Exception as e:
            logger.warning(f"Failed to send diff gist notification: {e}")

    def _truncate_consolidated(self, text: str, max_bytes: int) -> str:
        """Truncate text to fit within max_bytes (UTF-8 encoded)."""
        if self._get_text_byte_length(text) <= max_bytes:
            return text
        # Reserve space for ellipsis (3 bytes for "…")
        ellipsis = "…"
        ellipsis_bytes = len(ellipsis.encode("utf-8"))  # 3 bytes
        target_bytes = max_bytes - ellipsis_bytes
        # Truncate bytes and decode, handling partial characters
        encoded = text.encode("utf-8")
        truncated = encoded[:target_bytes].decode("utf-8", errors="ignore")
        return truncated.rstrip() + ellipsis

    def resolve_agent_for_context(self, context: MessageContext) -> str:
        """Unified agent resolution with dynamic override support.

        Priority:
        1. channel_routing.agent_backend (from settings.json)
        2. AgentRouter platform default (configured in code)
        3. AgentService.default_agent ("claude")
        """
        settings_key = self._get_settings_key(context)

        # Check dynamic override first
        routing = self.settings_manager.get_channel_routing(settings_key)
        if routing and routing.agent_backend:
            # Verify the agent is registered
            if routing.agent_backend in self.agent_service.agents:
                return routing.agent_backend
            else:
                logger.warning(
                    f"Channel routing specifies '{routing.agent_backend}' but agent is not registered, "
                    f"falling back to static routing"
                )

        # Fall back to static routing
        resolved = self.agent_router.resolve(self.config.platform, settings_key)

        return resolved

    def get_opencode_overrides(
        self, context: MessageContext
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Get OpenCode agent, model, and reasoning effort overrides for this channel.

        Returns:
            Tuple of (opencode_agent, opencode_model, opencode_reasoning_effort)
            or (None, None, None) if no overrides.
        """
        settings_key = self._get_settings_key(context)
        routing = self.settings_manager.get_channel_routing(settings_key)
        if routing:
            return (
                routing.opencode_agent,
                routing.opencode_model,
                routing.opencode_reasoning_effort,
            )
        return None, None, None

    async def emit_agent_message(
        self,
        context: MessageContext,
        message_type: str,
        text: str,
        parse_mode: Optional[str] = "markdown",
    ):
        """Centralized dispatch for agent messages.

        Message Types:
        - Log Messages (system/assistant/toolcall): Consolidated into a single
          editable message per conversation round. Can be hidden by user settings.
        - Result Message: Final output, always sent immediately, not hideable.
        - Notify Message: Notifications, always sent immediately.

        Log Messages are accumulated and edited in-place until they exceed the
        Slack byte limit (4000 bytes UTF-8), then a new message is started.
        """
        if not text or not text.strip():
            return

        canonical_type = self.settings_manager._canonicalize_message_type(
            message_type or ""
        )
        settings_key = self._get_settings_key(context)

        if canonical_type == "notify":
            target_context = self._get_target_context(context)
            await self.im_client.send_message(
                target_context, text, parse_mode=parse_mode
            )
            return

        if canonical_type == "result":
            target_context = self._get_target_context(context)
            if len(text) <= self._get_result_max_chars():
                await self.im_client.send_message(
                    target_context, text, parse_mode=parse_mode
                )
            else:
                summary = self._build_result_summary(text, self._get_result_max_chars())
                await self.im_client.send_message(
                    target_context, summary, parse_mode=parse_mode
                )

                if self.config.platform == "slack" and hasattr(
                    self.im_client, "upload_markdown"
                ):
                    try:
                        await self.im_client.upload_markdown(
                            target_context,
                            title="result.md",
                            content=text,
                            filetype="markdown",
                        )
                    except Exception as err:
                        logger.warning(f"Failed to upload result attachment: {err}")
                        await self.im_client.send_message(
                            target_context,
                            "无法上传附件（缺少 files:write 权限或上传失败）。需要我改成分条发送吗？",
                            parse_mode=parse_mode,
                        )

            await self._send_diff_gist_notification(context, target_context)
            return

        # Log Messages: system/assistant/toolcall - consolidated into editable message
        if canonical_type not in {"system", "assistant", "toolcall"}:
            canonical_type = "assistant"

        if self.settings_manager.is_message_type_hidden(settings_key, canonical_type):
            preview = text if len(text) <= 500 else f"{text[:500]}…"
            logger.info(
                "Skipping %s message for settings %s (hidden). Preview: %s",
                canonical_type,
                settings_key,
                preview,
            )
            return

        consolidated_key = self._get_consolidated_message_key(context)
        lock = self._get_consolidated_message_lock(consolidated_key)

        async with lock:
            chunk = text.strip()
            max_bytes = self._get_consolidated_max_bytes()
            split_threshold = self._get_consolidated_split_threshold()
            existing = self._consolidated_message_buffers.get(consolidated_key, "")
            existing_message_id = self._consolidated_message_ids.get(consolidated_key)

            separator = "\n\n---\n\n" if existing else ""
            updated = f"{existing}{separator}{chunk}" if existing else chunk

            target_context = self._get_target_context(context)
            continuation_notice = "\n\n---\n\n_(continued below...)_"
            continuation_bytes = self._get_text_byte_length(continuation_notice)

            # Case 1: Accumulated message exceeds threshold (in bytes), split off old message
            if (
                existing_message_id
                and self._get_text_byte_length(updated) > split_threshold
            ):
                old_text = existing + continuation_notice
                old_text = self._truncate_consolidated(old_text, max_bytes)

                try:
                    await self.im_client.edit_message(
                        target_context,
                        existing_message_id,
                        text=old_text,
                        parse_mode="markdown",
                    )
                except Exception as err:
                    logger.warning(f"Failed to finalize old Log Message: {err}")

                # Start fresh with just the new chunk
                self._consolidated_message_buffers[consolidated_key] = chunk
                self._consolidated_message_ids.pop(consolidated_key, None)
                updated = chunk
                existing_message_id = None
                logger.info(
                    "Log Message exceeded %d bytes, starting new message",
                    split_threshold,
                )

            # Case 2: Single chunk (including first message) exceeds max_bytes
            # Split into multiple messages to avoid truncation
            while self._get_text_byte_length(updated) > max_bytes:
                # Find split point that fits within threshold (accounting for continuation notice)
                target_bytes = split_threshold - continuation_bytes
                first_part = self._truncate_consolidated(updated, target_bytes)
                first_part = (
                    first_part.rstrip("…") + continuation_notice
                )  # Replace truncation marker

                send_ok = False
                if existing_message_id:
                    try:
                        await self.im_client.edit_message(
                            target_context,
                            existing_message_id,
                            text=first_part,
                            parse_mode="markdown",
                        )
                        send_ok = True
                    except Exception as err:
                        logger.warning(f"Failed to edit oversized Log Message: {err}")
                else:
                    try:
                        await self.im_client.send_message(
                            target_context, first_part, parse_mode="markdown"
                        )
                        send_ok = True
                    except Exception as err:
                        logger.error(f"Failed to send oversized Log Message: {err}")

                if not send_ok:
                    # Failed to send/edit - stop splitting and truncate the remainder
                    logger.warning(
                        "Stopping split loop due to send failure, truncating remainder"
                    )
                    break

                # Continue with remainder (skip the part we already sent)
                # Don't lstrip() - preserve intentional indentation in code blocks
                sent_chars = len(first_part) - len(continuation_notice)
                updated = updated[sent_chars:]
                # Clear both local var and stored ID to avoid editing old message on failure
                existing_message_id = None
                self._consolidated_message_ids.pop(consolidated_key, None)
                logger.info(
                    "Log Message chunk exceeded %d bytes, split and continuing",
                    max_bytes,
                )

            updated = self._truncate_consolidated(updated, max_bytes)
            self._consolidated_message_buffers[consolidated_key] = updated

            if existing_message_id:
                try:
                    ok = await self.im_client.edit_message(
                        target_context,
                        existing_message_id,
                        text=updated,
                        parse_mode="markdown",
                    )
                except Exception as err:
                    logger.warning(f"Failed to edit Log Message: {err}")
                    ok = False
                if ok:
                    return
                self._consolidated_message_ids.pop(consolidated_key, None)

            try:
                new_id = await self.im_client.send_message(
                    target_context, updated, parse_mode="markdown"
                )
                self._consolidated_message_ids[consolidated_key] = new_id
            except Exception as err:
                logger.error(f"Failed to send Log Message: {err}", exc_info=True)

    async def send_processing_message_with_stop_button(
        self,
        context: MessageContext,
        text: str = "⏳ Processing...",
    ) -> Optional[str]:
        from modules.im.base import InlineKeyboard, InlineButton

        target_context = self._get_target_context(context)
        keyboard = InlineKeyboard(
            buttons=[[InlineButton(text="🛑 Stop", callback_data="cmd_stop")]]
        )

        try:
            if hasattr(self.im_client, "send_message_with_buttons"):
                message_id = await self.im_client.send_message_with_buttons(
                    target_context, text, keyboard, parse_mode="markdown"
                )
                return message_id
        except Exception as err:
            logger.warning(f"Failed to send processing message with stop button: {err}")

        return None

    async def remove_stop_button(
        self,
        context: MessageContext,
        message_id: str,
        new_text: Optional[str] = None,
    ) -> bool:
        target_context = self._get_target_context(context)
        try:
            if hasattr(self.im_client, "delete_message"):
                return await self.im_client.delete_message(target_context, message_id)
            elif hasattr(self.im_client, "remove_inline_keyboard"):
                return await self.im_client.remove_inline_keyboard(
                    target_context, message_id, text=new_text, parse_mode="markdown"
                )
        except Exception as err:
            logger.debug(f"Failed to remove stop button: {err}")
        return False

    # Settings update handler (for Slack modal)
    async def handle_settings_update(
        self,
        user_id: str,
        show_message_types: list,
        channel_id: Optional[str] = None,
        require_mention: Optional[bool] = None,
    ):
        """Handle settings update (typically from Slack modal)"""
        try:
            # Determine settings key - for Slack, always use channel_id
            if self.config.platform == "slack":
                settings_key = (
                    channel_id if channel_id else user_id
                )  # fallback to user_id if no channel
            else:
                settings_key = channel_id if channel_id else user_id

            # Update settings
            user_settings = self.settings_manager.get_user_settings(settings_key)
            user_settings.show_message_types = show_message_types

            # Save settings - using the correct method name
            self.settings_manager.update_user_settings(settings_key, user_settings)

            # Save require_mention setting
            self.settings_manager.set_require_mention(settings_key, require_mention)

            logger.info(
                f"Updated settings for {settings_key}: show types = {show_message_types}, "
                f"require_mention = {require_mention}"
            )

            # Create context for sending confirmation (without 'message' field)
            context = MessageContext(
                user_id=user_id,
                channel_id=channel_id if channel_id else user_id,
                platform_specific={},
            )

            # Send confirmation
            await self.im_client.send_message(
                context, "✅ Settings updated successfully!"
            )

        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            # Create context for error message (without 'message' field)
            context = MessageContext(
                user_id=user_id,
                channel_id=channel_id if channel_id else user_id,
                platform_specific={},
            )
            await self.im_client.send_message(
                context, f"❌ Failed to update settings: {str(e)}"
            )

    # Working directory change handler (for Slack modal)
    async def handle_change_cwd_submission(
        self, user_id: str, new_cwd: str, channel_id: Optional[str] = None
    ):
        """Handle working directory change submission (from Slack modal) - reuse command handler logic"""
        try:
            # Create context for messages (without 'message' field which doesn't exist in MessageContext)
            context = MessageContext(
                user_id=user_id,
                channel_id=channel_id if channel_id else user_id,
                platform_specific={},
            )

            # Reuse the same logic from handle_set_cwd command handler
            await self.command_handler.handle_set_cwd(context, new_cwd.strip())

        except Exception as e:
            logger.error(f"Error changing working directory: {e}")
            # Create context for error message (without 'message' field)
            context = MessageContext(
                user_id=user_id,
                channel_id=channel_id if channel_id else user_id,
                platform_specific={},
            )
            await self.im_client.send_message(
                context, f"❌ Failed to change working directory: {str(e)}"
            )

    async def handle_routing_modal_update(
        self,
        user_id: str,
        channel_id: str,
        view: dict,
        action: dict,
    ) -> None:
        """Handle routing modal updates when selections change."""
        try:
            view_id = view.get("id")
            view_hash = view.get("hash")
            if not view_id or not view_hash:
                logger.warning("Routing modal update missing view id/hash")
                return

            resolved_channel_id = channel_id if channel_id else user_id
            context = MessageContext(
                user_id=user_id,
                channel_id=resolved_channel_id,
                platform_specific={},
            )

            settings_key = self._get_settings_key(context)
            current_routing = self.settings_manager.get_channel_routing(settings_key)
            all_backends = list(self.agent_service.agents.keys())
            registered_backends = sorted(
                all_backends, key=lambda x: (x != "opencode", x)
            )
            current_backend = self.resolve_agent_for_context(context)

            values = view.get("state", {}).get("values", {})
            backend_data = values.get("backend_block", {}).get("backend_select", {})
            selected_backend = backend_data.get("selected_option", {}).get("value")
            if not selected_backend:
                selected_backend = current_backend

            def _selected_value(block_id: str, action_id: str) -> Optional[str]:
                data = values.get(block_id, {}).get(action_id, {})
                return data.get("selected_option", {}).get("value")

            def _selected_prefixed_value(
                block_id: str, action_prefix: str
            ) -> Optional[str]:
                block = values.get(block_id, {})
                if not isinstance(block, dict):
                    return None
                for action_id, action_data in block.items():
                    if (
                        isinstance(action_id, str)
                        and action_id.startswith(action_prefix)
                        and isinstance(action_data, dict)
                    ):
                        return action_data.get("selected_option", {}).get("value")
                return None

            oc_agent = _selected_value("opencode_agent_block", "opencode_agent_select")
            oc_model = _selected_value("opencode_model_block", "opencode_model_select")
            oc_reasoning = _selected_prefixed_value(
                "opencode_reasoning_block", "opencode_reasoning_select"
            )

            # For block_actions, the latest selection is carried on the `action` payload.
            action_id = action.get("action_id")
            selected_value = None
            selected_option = action.get("selected_option")
            if isinstance(selected_option, dict):
                selected_value = selected_option.get("value")

            if isinstance(action_id, str) and isinstance(selected_value, str):
                if action_id == "backend_select":
                    selected_backend = selected_value
                elif action_id == "opencode_agent_select":
                    oc_agent = selected_value
                elif action_id == "opencode_model_select":
                    oc_model = selected_value
                elif action_id.startswith("opencode_reasoning_select"):
                    oc_reasoning = selected_value

            if oc_agent == "__default__":
                oc_agent = None
            if oc_model == "__default__":
                oc_model = None
            if oc_reasoning == "__default__":
                oc_reasoning = None

            opencode_agents = []
            opencode_models = {}
            opencode_default_config = {}

            if "opencode" in registered_backends:
                try:
                    opencode_agent = self.agent_service.agents.get("opencode")
                    if opencode_agent and hasattr(opencode_agent, "_get_server"):
                        server = await opencode_agent._get_server()  # type: ignore[attr-defined]
                        await server.ensure_running()
                        cwd = self.get_cwd(context)
                        opencode_agents = await server.get_available_agents(cwd)
                        opencode_models = await server.get_available_models(cwd)
                        opencode_default_config = await server.get_default_config(cwd)
                except Exception as e:
                    logger.warning(f"Failed to fetch OpenCode data: {e}")

            if hasattr(self.im_client, "update_routing_modal"):
                current_env_vars = self._get_opencode_env_vars()
                await self.im_client.update_routing_modal(  # type: ignore[attr-defined]
                    view_id=view_id,
                    view_hash=view_hash,
                    channel_id=resolved_channel_id,
                    registered_backends=registered_backends,
                    current_backend=current_backend,
                    current_routing=current_routing,
                    opencode_agents=opencode_agents,
                    opencode_models=opencode_models,
                    opencode_default_config=opencode_default_config,
                    selected_backend=selected_backend,
                    selected_opencode_agent=oc_agent,
                    selected_opencode_model=oc_model,
                    selected_opencode_reasoning=oc_reasoning,
                    current_env_vars=current_env_vars,
                )
        except Exception as e:
            logger.error(f"Error updating routing modal: {e}", exc_info=True)

    async def handle_routing_update(
        self,
        user_id: str,
        channel_id: str,
        backend: str,
        opencode_agent: Optional[str],
        opencode_model: Optional[str],
        opencode_reasoning_effort: Optional[str] = None,
        require_mention: Optional[bool] = None,
        env_vars: Optional[Dict[str, str]] = None,
        claude_mode: Optional[str] = None,
        claude_model: Optional[str] = None,
        claude_env_vars: Optional[Dict[str, str]] = None,
    ):
        from modules.settings_manager import ChannelRouting

        try:
            routing = ChannelRouting(
                agent_backend=backend,
                opencode_agent=opencode_agent,
                opencode_model=opencode_model,
                opencode_reasoning_effort=opencode_reasoning_effort,
                claude_mode=claude_mode,
                claude_model=claude_model,
                claude_env_vars=claude_env_vars if claude_env_vars else None,
            )

            settings_key = channel_id if channel_id else user_id

            self.settings_manager.set_channel_routing(settings_key, routing)
            self.settings_manager.set_require_mention(settings_key, require_mention)

            env_vars_changed = False
            if env_vars is not None:
                env_vars_changed = await self._update_opencode_env_vars(env_vars)

            parts = [f"Backend: **{backend}**"]
            if backend == "opencode":
                if opencode_agent:
                    parts.append(f"Agent: **{opencode_agent}**")
                if opencode_model:
                    parts.append(f"Model: **{opencode_model}**")
                if opencode_reasoning_effort:
                    parts.append(f"Reasoning Effort: **{opencode_reasoning_effort}**")
                if env_vars:
                    parts.append(f"Env Vars: **{len(env_vars)} configured**")
            elif backend == "claude":
                if claude_model:
                    parts.append(f"Model: **{claude_model}**")
                if claude_mode:
                    parts.append(f"Mode: **{claude_mode}**")
                if claude_env_vars:
                    parts.append(f"Env Vars: **{len(claude_env_vars)} configured**")

            if require_mention is None:
                parts.append("Require @mention: **(Default)**")
            elif require_mention:
                parts.append("Require @mention: **Yes**")
            else:
                parts.append("Require @mention: **No**")

            # Create context for confirmation message
            context = MessageContext(
                user_id=user_id,
                channel_id=channel_id if channel_id else user_id,
                platform_specific={},
            )

            await self.im_client.send_message(
                context,
                f"✅ Agent routing updated!\n" + "\n".join(parts),
                parse_mode="markdown",
            )

            logger.info(
                f"Routing updated for {settings_key}: backend={backend}, "
                f"agent={opencode_agent}, model={opencode_model}, require_mention={require_mention}"
            )

        except Exception as e:
            logger.error(f"Error updating routing: {e}")
            context = MessageContext(
                user_id=user_id,
                channel_id=channel_id if channel_id else user_id,
                platform_specific={},
            )
            await self.im_client.send_message(
                context, f"❌ Failed to update routing: {str(e)}"
            )

    async def _update_opencode_env_vars(self, env_vars: Dict[str, str]) -> bool:
        from config.v2_config import V2Config
        from modules.agents.opencode.server import OpenCodeServerManager

        try:
            config = V2Config.load()
            current_env_vars = config.agents.opencode.env_vars or {}

            if current_env_vars == env_vars:
                return False

            config.agents.opencode.env_vars = env_vars
            config.save()
            logger.info(f"Updated OpenCode env_vars: {list(env_vars.keys())}")

            if OpenCodeServerManager._instance:
                await OpenCodeServerManager._instance.update_env_vars(env_vars)

            return True
        except Exception as e:
            logger.error(f"Failed to update OpenCode env_vars: {e}")
            return False

    def _get_opencode_env_vars(self) -> Dict[str, str]:
        from config.v2_config import V2Config

        try:
            config = V2Config.load()
            return config.agents.opencode.env_vars or {}
        except Exception:
            return {}

    async def handle_app_home_opened(
        self, user_id: str, selected_channel_id: Optional[str] = None
    ):
        try:
            all_backends = list(self.agent_service.agents.keys())
            registered_backends = sorted(
                all_backends, key=lambda x: (x != "opencode", x)
            )

            channels = []
            if hasattr(self.im_client, "get_bot_channels"):
                channels = await self.im_client.get_bot_channels()

            if not selected_channel_id:
                selected_channel_id = self._home_selected_channels.get(user_id)

            if not selected_channel_id and channels:
                selected_channel_id = channels[0]["id"]

            if selected_channel_id:
                self._home_selected_channels[user_id] = selected_channel_id

            if selected_channel_id:
                context = MessageContext(
                    user_id=user_id,
                    channel_id=selected_channel_id,
                    platform_specific={},
                )
            else:
                context = MessageContext(
                    user_id=user_id, channel_id=user_id, platform_specific={}
                )

            current_backend = self.resolve_agent_for_context(context)
            settings_key = self._get_settings_key(context)
            current_routing = self.settings_manager.get_channel_routing(settings_key)

            opencode_agents = []
            opencode_models = {}
            opencode_default_config = {}

            if "opencode" in registered_backends:
                try:
                    opencode_agent = self.agent_service.agents.get("opencode")
                    if opencode_agent and hasattr(opencode_agent, "_get_server"):
                        server = await opencode_agent._get_server()
                        await server.ensure_running()
                        cwd = self.get_cwd(context)
                        opencode_agents = await server.get_available_agents(cwd)
                        opencode_models = await server.get_available_models(cwd)
                        opencode_default_config = await server.get_default_config(cwd)
                except Exception as e:
                    logger.warning(f"Failed to fetch OpenCode data for App Home: {e}")

            current_env_vars = self._get_opencode_env_vars()
            claude_env_vars = (
                current_routing.claude_env_vars if current_routing else None
            )

            if hasattr(self.im_client, "publish_app_home"):
                await self.im_client.publish_app_home(
                    user_id=user_id,
                    registered_backends=registered_backends,
                    current_backend=current_backend,
                    opencode_agents=opencode_agents,
                    opencode_models=opencode_models,
                    opencode_default_config=opencode_default_config,
                    current_routing=current_routing,
                    current_env_vars=current_env_vars,
                    current_claude_env_vars=claude_env_vars,
                    channels=channels,
                    selected_channel_id=selected_channel_id,
                )
        except Exception as e:
            logger.error(f"Error handling app_home_opened: {e}", exc_info=True)

    async def handle_home_setting_change(
        self, user_id: str, action_id: str, value: str
    ):
        from modules.settings_manager import ChannelRouting

        try:
            selected_channel_id = self._home_selected_channels.get(user_id)
            settings_key = selected_channel_id if selected_channel_id else user_id
            current_routing = self.settings_manager.get_channel_routing(settings_key)

            if current_routing is None:
                current_routing = ChannelRouting()

            if value == "__default__":
                value = None

            if action_id == "home_backend_select":
                current_routing.agent_backend = value
            elif action_id == "home_opencode_agent_select":
                current_routing.opencode_agent = value
            elif action_id == "home_opencode_model_select":
                current_routing.opencode_model = value
            elif action_id == "home_opencode_reasoning_select":
                current_routing.opencode_reasoning_effort = value
            elif action_id == "home_claude_mode_select":
                current_routing.claude_mode = value
            elif action_id == "home_claude_model_select":
                current_routing.claude_model = value

            self.settings_manager.set_channel_routing(settings_key, current_routing)
            logger.info(
                f"App Home setting changed: {action_id}={value} for channel {settings_key}"
            )

            await self.handle_app_home_opened(
                user_id, selected_channel_id=selected_channel_id
            )

        except Exception as e:
            logger.error(f"Error handling home setting change: {e}", exc_info=True)

    async def handle_home_channel_select(self, user_id: str, channel_id: str):
        try:
            self._home_selected_channels[user_id] = channel_id
            await self.handle_app_home_opened(user_id, selected_channel_id=channel_id)
        except Exception as e:
            logger.error(f"Error handling home channel select: {e}", exc_info=True)

    async def handle_home_edit_env(self, user_id: str, action_id: str, trigger_id: str):
        """Handle Edit button click for environment variables in App Home."""
        try:
            if action_id == "home_edit_opencode_env":
                env_type = "opencode"
                current_env_vars = self._get_opencode_env_vars()
            elif action_id == "home_edit_claude_env":
                env_type = "claude"
                settings_key = user_id
                current_routing = self.settings_manager.get_channel_routing(
                    settings_key
                )
                current_env_vars = (
                    current_routing.claude_env_vars if current_routing else None
                ) or {}
            else:
                logger.warning(f"Unknown env edit action: {action_id}")
                return

            if hasattr(self.im_client, "open_env_vars_modal"):
                await self.im_client.open_env_vars_modal(
                    trigger_id=trigger_id,
                    user_id=user_id,
                    env_type=env_type,
                    current_env_vars=current_env_vars,
                )
        except Exception as e:
            logger.error(f"Error handling home edit env: {e}", exc_info=True)

    async def handle_home_env_save(
        self, user_id: str, env_type: str, env_vars: Dict[str, str]
    ):
        """Handle saving environment variables from App Home modal."""
        from modules.settings_manager import ChannelRouting

        try:
            if env_type == "opencode":
                await self._update_opencode_env_vars(env_vars)
                logger.info(
                    f"Updated OpenCode env vars from App Home for user {user_id}"
                )
            elif env_type == "claude":
                settings_key = user_id
                current_routing = self.settings_manager.get_channel_routing(
                    settings_key
                )
                if current_routing is None:
                    current_routing = ChannelRouting()
                current_routing.claude_env_vars = env_vars
                self.settings_manager.set_channel_routing(settings_key, current_routing)
                logger.info(f"Updated Claude env vars from App Home for user {user_id}")

            await self.handle_app_home_opened(user_id)

        except Exception as e:
            logger.error(f"Error handling home env save: {e}", exc_info=True)

    def run(self):
        """Run the controller"""
        logger.info(
            f"Starting Claude Proxy Controller with {self.config.platform} platform..."
        )

        # 不再创建额外事件循环，避免与 IM 客户端的内部事件循环冲突
        # 清理职责改为：
        # - 进程退出时做一次同步的 best-effort 取消（不跨循环 await）

        try:
            # Run the IM client (blocking)
            self.im_client.run()
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down...")
        except Exception as e:
            logger.error(f"Error in main run loop: {e}", exc_info=True)
        finally:
            # Best-effort 同步清理，避免跨事件循环 await
            self.cleanup_sync()

    async def periodic_cleanup(self):
        """[Deprecated] Periodic cleanup is disabled in favor of safe on-demand cleanup"""
        logger.info("periodic_cleanup is deprecated and not scheduled.")
        return

    def cleanup_sync(self):
        """Best-effort synchronous cleanup without cross-loop awaits"""
        logger.info("Cleaning up controller resources (sync, best-effort)...")

        # Stop update checker
        try:
            self.update_checker.stop()
        except Exception as e:
            logger.debug(f"Update checker cleanup skipped: {e}")

        # Cancel receiver tasks without awaiting (they may belong to other loops)
        try:
            for session_id, task in list(self.receiver_tasks.items()):
                if not task.done():
                    task.cancel()
                # Remove from registry regardless
                del self.receiver_tasks[session_id]
        except Exception as e:
            logger.debug(f"Receiver tasks cleanup skipped due to: {e}")

        # Do not attempt to await SessionHandler cleanup here to avoid cross-loop issues.
        # Active connections will be closed by process exit; mappings are persisted separately.

        # Attempt to call stop if it's a plain function; skip if coroutine to avoid cross-loop awaits
        try:
            stop_attr = getattr(self.im_client, "stop", None)
            if callable(stop_attr):
                import inspect

                if not inspect.iscoroutinefunction(stop_attr):
                    stop_attr()
        except Exception as e:
            logger.warning("Failed to stop IM client: %s", e)

        # Best-effort async shutdown for IM clients
        try:
            shutdown_attr = getattr(self.im_client, "shutdown", None)
            if callable(shutdown_attr):
                import inspect

                if inspect.iscoroutinefunction(shutdown_attr):
                    try:
                        asyncio.run(shutdown_attr())
                    except RuntimeError:
                        pass
                else:
                    shutdown_attr()
        except Exception as e:
            logger.warning("Failed to shutdown IM client: %s", e)

        # Stop OpenCode server if running
        try:
            from modules.agents.opencode import OpenCodeServerManager

            OpenCodeServerManager.stop_instance_sync()
        except Exception as e:
            logger.debug(f"OpenCode server cleanup skipped: {e}")

        logger.info("Controller cleanup (sync) complete")
