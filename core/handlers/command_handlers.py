"""Command handlers for bot commands like /start, /clear, /cwd, etc."""

import asyncio
import os
import logging
from typing import Optional
from modules.agents import AgentRequest, get_agent_display_name
from modules.im import MessageContext, InlineKeyboard, InlineButton

logger = logging.getLogger(__name__)


class CommandHandlers:
    """Handles all bot command operations"""

    def __init__(self, controller):
        """Initialize with reference to main controller"""
        self.controller = controller
        self.config = controller.config
        self.im_client = controller.im_client
        self.session_manager = controller.session_manager
        self.settings_manager = controller.settings_manager

    def _get_channel_context(self, context: MessageContext) -> MessageContext:
        """Get context for channel messages (no thread)"""
        # For Slack: send command responses directly to channel, not in thread
        if self.config.platform == "slack":
            return MessageContext(
                user_id=context.user_id,
                channel_id=context.channel_id,
                thread_id=None,  # No thread for command responses
                platform_specific=context.platform_specific,
            )
        # For other platforms, keep original context
        return context

    async def handle_start(self, context: MessageContext, args: str = ""):
        """Handle /start command with interactive buttons"""
        platform_name = self.config.platform.capitalize()

        # Get user and channel info
        try:
            user_info = await self.im_client.get_user_info(context.user_id)
        except Exception as e:
            logger.warning(f"Failed to get user info: {e}")
            user_info = {"id": context.user_id}

        try:
            channel_info = await self.im_client.get_channel_info(context.channel_id)
        except Exception as e:
            logger.warning(f"Failed to get channel info: {e}")
            channel_info = {
                "id": context.channel_id,
                "name": (
                    "Direct Message"
                    if context.channel_id.startswith("D")
                    else context.channel_id
                ),
            }

        agent_name = self.controller.resolve_agent_for_context(context)
        default_agent = getattr(self.controller.agent_service, "default_agent", None)
        agent_display_name = get_agent_display_name(
            agent_name, fallback=default_agent or "Unknown"
        )

        # For non-Slack platforms, use traditional text message
        if self.config.platform != "slack":
            formatter = self.im_client.formatter

            # Build welcome message using formatter to handle escaping properly
            lines = [
                formatter.format_bold("Welcome to Slack Coder!"),
                "",
                f"Platform: {formatter.format_text(platform_name)}",
                f"Agent: {formatter.format_text(agent_display_name)}",
                f"User ID: {formatter.format_code_inline(context.user_id)}",
                f"Channel/Chat ID: {formatter.format_code_inline(context.channel_id)}",
                "",
                formatter.format_bold("Commands:"),
                formatter.format_text("@Slack Coder /start - Show this message"),
                formatter.format_text(
                    "@Slack Coder /clear - Reset session and start fresh"
                ),
                formatter.format_text(
                    "@Slack Coder /cwd - Show current working directory"
                ),
                formatter.format_text(
                    "@Slack Coder /set_cwd <path> - Set working directory"
                ),
                formatter.format_text(
                    "@Slack Coder /settings - Personalization settings"
                ),
                formatter.format_text(
                    f"@Slack Coder /stop - Interrupt {agent_display_name} execution"
                ),
                "",
                formatter.format_bold("How it works:"),
                formatter.format_text(
                    f"• Send any message and it's immediately sent to {agent_display_name}"
                ),
                formatter.format_text(
                    "• Each chat maintains its own conversation context"
                ),
                formatter.format_text("• Use /clear to reset the conversation"),
            ]

            message_text = formatter.format_message(*lines)
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(channel_context, message_text)
            return

        # For Slack, create interactive buttons using Block Kit
        user_name = user_info.get("real_name") or user_info.get("name") or "User"

        buttons = [
            [
                InlineButton(text="📋 恢复会话", callback_data="cmd_resume"),
                InlineButton(text="📂 切换目录", callback_data="cmd_change_cwd"),
            ],
            [
                InlineButton(text="🤖 Agent 设置", callback_data="cmd_routing"),
                InlineButton(text="⚙️ 设置", callback_data="cmd_settings"),
            ],
        ]

        keyboard = InlineKeyboard(buttons=buttons)

        welcome_text = f"""🎉 **欢迎使用 Slack Coder！**

👋 你好 **{user_name}**！
🔧 平台：**{platform_name}**
🤖 Agent：**{agent_display_name}**
📍 频道：**{channel_info.get("name", "Unknown")}**

**快捷操作：**
使用下方按钮管理 {agent_display_name} 会话，或直接发消息开始对话！"""

        # Send command response to channel (not in thread)
        channel_context = self._get_channel_context(context)
        await self.im_client.send_message_with_buttons(
            channel_context, welcome_text, keyboard
        )

    async def handle_clear(self, context: MessageContext, args: str = ""):
        """Handle clear command - clears all sessions across configured agents"""
        try:
            # Get the correct settings key (channel_id for Slack, not user_id)
            settings_key = self.controller._get_settings_key(context)

            cleared = await self.controller.agent_service.clear_sessions(settings_key)
            if not cleared:
                full_response = (
                    "📋 No active sessions to clear.\n🔄 Session state has been reset."
                )
            else:
                details = "\n".join(
                    f"• {agent} → {count} session(s)"
                    for agent, count in cleared.items()
                )
                full_response = (
                    "✅ Cleared active sessions for:\n"
                    f"{details}\n🔄 All sessions reset."
                )

            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(channel_context, full_response)
            logger.info(f"Sent clear response to user {context.user_id}")

        except Exception as e:
            logger.error(f"Error clearing session: {e}", exc_info=True)
            try:
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(
                    channel_context, f"❌ Error clearing session: {str(e)}"
                )
            except Exception as send_error:
                logger.error(
                    f"Failed to send error message: {send_error}", exc_info=True
                )

    async def handle_cwd(self, context: MessageContext, args: str = ""):
        """Handle cwd command - show current working directory"""
        try:
            # Get CWD based on context (channel/chat)
            absolute_path = self.controller.get_cwd(context)

            # Build response using formatter to avoid escaping issues
            formatter = self.im_client.formatter

            # Format path properly with code block
            path_line = f"📁 Current Working Directory:\n{formatter.format_code_inline(absolute_path)}"

            # Build status lines
            status_lines = []
            if os.path.exists(absolute_path):
                status_lines.append("✅ Directory exists")
            else:
                status_lines.append("⚠️ Directory does not exist")

            status_lines.append("💡 This is where Agent will execute commands")

            # Combine all parts
            response_text = path_line + "\n" + "\n".join(status_lines)

            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(channel_context, response_text)
        except Exception as e:
            logger.error(f"Error getting cwd: {e}")
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(
                channel_context, f"Error getting working directory: {str(e)}"
            )

    async def handle_set_cwd(self, context: MessageContext, args: str):
        """Handle set_cwd command - change working directory"""
        try:
            if not args:
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(
                    channel_context, "Usage: /set_cwd <path>"
                )
                return

            new_path = args.strip()

            # Expand user path and get absolute path
            expanded_path = os.path.expanduser(new_path)
            absolute_path = os.path.abspath(expanded_path)

            # Check if directory exists
            if not os.path.exists(absolute_path):
                # Try to create it
                try:
                    os.makedirs(absolute_path, exist_ok=True)
                    logger.info(f"Created directory: {absolute_path}")
                except Exception as e:
                    channel_context = self._get_channel_context(context)
                    await self.im_client.send_message(
                        channel_context, f"❌ Cannot create directory: {str(e)}"
                    )
                    return

            if not os.path.isdir(absolute_path):
                formatter = self.im_client.formatter
                error_text = f"❌ Path exists but is not a directory: {formatter.format_code_inline(absolute_path)}"
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, error_text)
                return

            # Save to user settings
            settings_key = self.controller._get_settings_key(context)
            self.settings_manager.set_custom_cwd(settings_key, absolute_path)

            logger.info(f"User {context.user_id} changed cwd to: {absolute_path}")

            formatter = self.im_client.formatter
            response_text = (
                f"✅ Working directory changed to:\n"
                f"{formatter.format_code_inline(absolute_path)}"
            )
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(channel_context, response_text)

        except Exception as e:
            logger.error(f"Error setting cwd: {e}")
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(
                channel_context, f"❌ Error setting working directory: {str(e)}"
            )

    async def handle_change_cwd_modal(self, context: MessageContext):
        """Handle Change Work Dir button - open modal for Slack"""
        if self.config.platform != "slack":
            # For non-Slack platforms, just send instructions
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(
                channel_context,
                "📂 To change working directory, use:\n`/set_cwd <path>`\n\nExample:\n`/set_cwd ~/projects/myapp`",
            )
            return

        # For Slack, open a modal dialog
        trigger_id = (
            context.platform_specific.get("trigger_id")
            if context.platform_specific
            else None
        )

        if trigger_id and hasattr(self.im_client, "open_change_cwd_modal"):
            try:
                # Get current CWD based on context
                current_cwd = self.controller.get_cwd(context)

                await self.im_client.open_change_cwd_modal(
                    trigger_id, current_cwd, context.channel_id
                )
            except Exception as e:
                logger.error(f"Error opening change CWD modal: {e}")
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(
                    channel_context,
                    "❌ Failed to open directory change dialog. Please try again.",
                )
        else:
            # No trigger_id, show instructions
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(
                channel_context,
                "📂 Click the 'Change Work Dir' button in the @Vibe Remote /start menu to change working directory.",
            )

    async def handle_stop(self, context: MessageContext, args: str = ""):
        """Handle /stop command - send interrupt message to the active agent"""
        try:
            session_handler = self.controller.session_handler
            base_session_id, working_path, composite_key = (
                session_handler.get_session_info(context)
            )
            settings_key = self.controller._get_settings_key(context)
            agent_name = self.controller.resolve_agent_for_context(context)
            request = AgentRequest(
                context=context,
                message="stop",
                working_path=working_path,
                base_session_id=base_session_id,
                composite_session_id=composite_key,
                settings_key=settings_key,
            )

            handled = await self.controller.agent_service.handle_stop(
                agent_name, request
            )
            if not handled:
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(
                    channel_context, "ℹ️ No active session to stop for this channel."
                )

        except Exception as e:
            logger.error(f"Error sending stop command: {e}", exc_info=True)
            # For errors, still use original context to maintain thread consistency
            await self.im_client.send_message(
                context,  # Use original context
                f"❌ Error sending stop command: {str(e)}",
            )

    async def handle_sessions(self, context: MessageContext, args: str = ""):
        try:
            channel_context = self._get_channel_context(context)
            working_path = self.controller.get_cwd(context)

            opencode_agent = self.controller.agent_service.agents.get("opencode")
            if not opencode_agent:
                await self.im_client.send_message(
                    channel_context, "❌ OpenCode agent is not enabled."
                )
                return

            server = await opencode_agent._get_server()
            await server.ensure_running()
            sessions = await server.list_sessions(working_path)

            if not sessions:
                await self.im_client.send_message(
                    channel_context,
                    f"📋 No OpenCode sessions found for:\n`{working_path}`\n\n"
                    "💡 Start a new conversation to create a session.",
                )
                return

            lines = [
                f"📋 **OpenCode Sessions** ({len(sessions)} found)",
                f"📁 Directory: `{working_path}`",
                "",
            ]

            max_display = 10
            for i, session in enumerate(sessions[:max_display], 1):
                session_id = session.get("id", "unknown")
                title = session.get("title", "")
                time_info = session.get("time", {})
                created_ts = time_info.get("created", 0)
                updated_ts = time_info.get("updated", 0)

                if title.startswith("vibe-remote:"):
                    title = ""

                from datetime import datetime

                if updated_ts:
                    updated_str = datetime.fromtimestamp(updated_ts / 1000).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                elif created_ts:
                    updated_str = datetime.fromtimestamp(created_ts / 1000).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                else:
                    updated_str = ""

                lines.append(f"**{i}.** `{session_id}`")
                if title:
                    lines.append(f"   📝 {title}")
                if updated_str:
                    lines.append(f"   🕐 {updated_str}")
                lines.append("")

            if len(sessions) > max_display:
                lines.append(f"_...and {len(sessions) - max_display} more sessions_")

            lines.append("")
            lines.append("💡 **To resume a session**, use:")
            lines.append("`/resume <session_id> your message`")

            await self.im_client.send_message(
                channel_context, "\n".join(lines), parse_mode="markdown"
            )

        except Exception as e:
            logger.error(f"Error listing sessions: {e}", exc_info=True)
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(
                channel_context, f"❌ Error listing sessions: {str(e)}"
            )

    async def handle_diff(self, context: MessageContext, args: str = ""):
        try:
            trigger_id = (
                context.platform_specific.get("trigger_id")
                if context.platform_specific
                else None
            )
            channel_context = self._get_channel_context(context)
            working_path = self.controller.get_cwd(context)

            if not os.path.isdir(os.path.join(working_path, ".git")):
                await self.im_client.send_message(
                    channel_context,
                    f"❌ 不是 Git 仓库：`{working_path}`",
                )
                return

            process = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                "--stat",
                cwd=working_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stat_stdout, stat_stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stat_stderr.decode("utf-8", errors="replace").strip()
                await self.im_client.send_message(
                    channel_context, f"❌ Git diff 失败：{error_msg}"
                )
                return

            stat_output = stat_stdout.decode("utf-8", errors="replace").strip()

            process = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                cwd=working_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            diff_stdout, _ = await process.communicate()
            diff_output = diff_stdout.decode("utf-8", errors="replace")

            if trigger_id and hasattr(self.im_client, "open_diff_modal"):
                await self.im_client.open_diff_modal(
                    trigger_id,
                    stat_output,
                    diff_output,
                    working_path,
                    context.channel_id,
                )
            else:
                if not stat_output:
                    await self.im_client.send_message(
                        channel_context, f"✅ 没有未提交的更改\n📁 `{working_path}`"
                    )
                else:
                    await self.im_client.send_message(
                        channel_context,
                        f"📊 **Git 变更**\n📁 `{working_path}`\n```\n{stat_output}\n```",
                        parse_mode="markdown",
                    )

        except Exception as e:
            logger.error(f"Error generating diff: {e}", exc_info=True)
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(
                channel_context, f"❌ 获取 Git 变更失败：{str(e)}"
            )

    async def handle_help(self, context: MessageContext, args: str = ""):
        """Handle /help command - show available commands"""
        channel_context = self._get_channel_context(context)

        help_text = """📚 **Vibe Remote 使用说明**

**快速开始**
• 输入 `/vibe-start` 打开控制面板
• 直接 @Vibe Remote 发消息即可与 AI 对话

**控制面板功能**
• 📋 恢复会话 - 选择并恢复历史对话
• 🛑 停止执行 - 中断当前 AI 任务
• 📁 当前目录 / 📂 切换目录 - 管理工作目录
• 📊 Git 变更 - 查看代码改动
• 🔄 清除会话 - 重置所有会话
• 🤖 Agent 设置 - 切换 AI 模型

**使用技巧**
• 每个 Slack 线程 = 独立的对话会话
• 可同时开多个线程并行处理任务
• 在线程中输入 `stop` 可快速停止
"""

        await self.im_client.send_message(
            channel_context, help_text, parse_mode="markdown"
        )

    async def handle_resume_modal(self, context: MessageContext):
        """Show session list in a modal"""
        try:
            trigger_id = (
                context.platform_specific.get("trigger_id")
                if context.platform_specific
                else None
            )

            if not trigger_id:
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(
                    channel_context, "❌ 无法打开弹窗，请重试"
                )
                return

            working_path = self.controller.get_cwd(context)
            agent_name = self.controller.resolve_agent_for_context(context)
            sessions = []

            if agent_name == "claude":
                from modules.claude_client import ClaudeClient

                sessions = ClaudeClient.list_sessions(working_path)
            elif agent_name == "opencode":
                opencode_agent = self.controller.agent_service.agents.get("opencode")
                if opencode_agent:
                    server = await opencode_agent._get_server()
                    await server.ensure_running()
                    sessions = await server.list_sessions(working_path)

            if not sessions:
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(
                    channel_context, f"📭 当前目录没有找到 {agent_name} 的历史会话"
                )
                return

            if hasattr(self.im_client, "open_sessions_modal"):
                await self.im_client.open_sessions_modal(
                    trigger_id, sessions, working_path, context.channel_id, agent_name
                )

        except Exception as e:
            logger.error(f"Error showing sessions modal: {e}", exc_info=True)
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(
                channel_context, f"❌ 获取会话列表失败：{str(e)}"
            )

    async def handle_resume_session(
        self, context: MessageContext, session_id: str, agent_name: str = "opencode"
    ):
        """Resume a specific session - show history and bind thread"""
        try:
            channel_context = self._get_channel_context(context)
            working_path = self.controller.get_cwd(context)

            if agent_name == "claude":
                await self._resume_claude_session(
                    context, channel_context, session_id, working_path
                )
            else:
                await self._resume_opencode_session(
                    context, channel_context, session_id, working_path
                )

        except Exception as e:
            logger.error(f"Error resuming session: {e}", exc_info=True)
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(
                channel_context, f"❌ 恢复会话失败：{str(e)}"
            )

    async def _resume_opencode_session(
        self,
        context: MessageContext,
        channel_context: MessageContext,
        session_id: str,
        working_path: str,
    ):
        opencode_agent = self.controller.agent_service.agents.get("opencode")
        if not opencode_agent:
            await self.im_client.send_message(
                channel_context, "❌ OpenCode agent 未启用"
            )
            return

        server = await opencode_agent._get_server()
        await server.ensure_running()

        target_session = await server.get_session(session_id, working_path)
        if not target_session:
            await self.im_client.send_message(
                channel_context, f"❌ 会话不存在：`{session_id}`"
            )
            return

        title = target_session.get("title", "")
        if title.startswith("vibe-remote:"):
            title = ""
        display_name = title if title else session_id[:12]

        messages = await server.list_messages(session_id, working_path)
        history_lines = self._format_opencode_history(messages, display_name)

        message_ts = await self.im_client.send_message(
            channel_context,
            "\n".join(history_lines),
            parse_mode="markdown",
        )

        if message_ts:
            settings_key = self.controller._get_settings_key(context)
            base_session_id = f"slack_{message_ts}"
            self.settings_manager.set_agent_session_mapping(
                settings_key,
                "opencode",
                base_session_id,
                session_id,
            )
            self.settings_manager.mark_thread_active(
                context.user_id, context.channel_id, message_ts
            )
            logger.info(f"Bound thread {message_ts} to OpenCode session {session_id}")

    async def _resume_claude_session(
        self,
        context: MessageContext,
        channel_context: MessageContext,
        session_id: str,
        working_path: str,
    ):
        from modules.claude_client import ClaudeClient

        target_session = ClaudeClient.get_session(session_id, working_path)
        if not target_session:
            await self.im_client.send_message(
                channel_context, f"❌ 会话不存在：`{session_id}`"
            )
            return

        display_name = target_session.get("title", "") or session_id[:12]
        messages = ClaudeClient.get_session_messages(session_id, working_path)
        history_lines = self._format_claude_history(messages, display_name)

        message_ts = await self.im_client.send_message(
            channel_context,
            "\n".join(history_lines),
            parse_mode="markdown",
        )

        if message_ts:
            settings_key = self.controller._get_settings_key(context)
            base_session_id = f"slack_{message_ts}"
            self.settings_manager.set_session_mapping(
                settings_key,
                base_session_id,
                session_id,
            )
            self.settings_manager.mark_thread_active(
                context.user_id, context.channel_id, message_ts
            )
            logger.info(f"Bound thread {message_ts} to Claude session {session_id}")

    def _format_opencode_history(self, messages: list, display_name: str) -> list:
        history_lines = [f"📋 **恢复会话：{display_name}**\n"]
        msg_count = 0
        for msg in messages[-10:]:
            info = msg.get("info", {})
            role = info.get("role", "")
            parts = msg.get("parts", [])
            content = ""
            for part in parts:
                if part.get("type") == "text":
                    content = part.get("text", "")
                    break
            if content and role in ("user", "assistant"):
                role_icon = "👤" if role == "user" else "🤖"
                content_preview = content.replace("\n", " ")[:100]
                if len(content) > 100:
                    content_preview += "..."
                history_lines.append(f"{role_icon} {content_preview}")
                msg_count += 1
        if msg_count == 0:
            history_lines.append("_(暂无历史消息)_")
        history_lines.append("\n---\n💬 **在下方回复继续对话**")
        return history_lines

    def _format_claude_history(self, messages: list, display_name: str) -> list:
        history_lines = [f"📋 **恢复会话：{display_name}**\n"]
        msg_count = 0
        for msg in messages[-10:]:
            msg_type = msg.get("type", "")
            if msg_type == "human":
                content = msg.get("message", {}).get("content", "")
                if content:
                    content_preview = content.replace("\n", " ")[:100]
                    if len(content) > 100:
                        content_preview += "..."
                    history_lines.append(f"👤 {content_preview}")
                    msg_count += 1
            elif msg_type == "assistant":
                content_blocks = msg.get("message", {}).get("content", [])
                text_content = ""
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_content = block.get("text", "")
                        break
                if text_content:
                    content_preview = text_content.replace("\n", " ")[:100]
                    if len(text_content) > 100:
                        content_preview += "..."
                    history_lines.append(f"🤖 {content_preview}")
                    msg_count += 1
        if msg_count == 0:
            history_lines.append("_(暂无历史消息)_")
        history_lines.append("\n---\n💬 **在下方回复继续对话**")
        return history_lines
