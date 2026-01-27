import asyncio
import asyncio
import hashlib
import logging
import time
from typing import Dict, Any, Optional, Callable, List
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.errors import SlackApiError
from markdown_to_mrkdwn import SlackMarkdownConverter

from .base import BaseIMClient, MessageContext, InlineKeyboard, InlineButton
from config.v2_config import SlackConfig
from .formatters import SlackFormatter

logger = logging.getLogger(__name__)

_UNSET = object()


class SlackBot(BaseIMClient):
    """Slack implementation of the IM client"""

    def __init__(self, config: SlackConfig):
        super().__init__(config)
        self.config = config
        self.web_client: Optional[AsyncWebClient] = None
        self.socket_client: Optional[SocketModeClient] = None

        # Initialize Slack formatter
        self.formatter = SlackFormatter()

        # Initialize markdown to mrkdwn converter
        self.markdown_converter = SlackMarkdownConverter()

        # Note: Thread handling now uses user's message timestamp directly

        # Store callback handlers
        self.command_handlers: Dict[str, Callable] = {}

        # Store trigger IDs for modal interactions
        self.trigger_ids: Dict[str, str] = {}

        # Settings manager for thread tracking (will be injected later)
        self.settings_manager = None
        # Controller reference for update button handling (will be injected later)
        self._controller = None
        self._recent_event_ids: Dict[str, float] = {}
        self._stop_event: Optional[asyncio.Event] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._on_ready: Optional[Callable] = None

    def set_settings_manager(self, settings_manager):
        """Set the settings manager for thread tracking"""
        self.settings_manager = settings_manager

    def set_controller(self, controller):
        """Set the controller reference for handling update button clicks"""
        self._controller = controller

    def _is_duplicate_event(self, event_id: Optional[str]) -> bool:
        """Deduplicate Slack events using event_id with a short TTL."""
        if not event_id:
            return False
        now = time.time()
        expiry = now - 30  # retain for 30s
        for key in list(self._recent_event_ids.keys()):
            if self._recent_event_ids[key] < expiry:
                del self._recent_event_ids[key]
        if event_id in self._recent_event_ids:
            logger.debug(f"Ignoring duplicate Slack event_id {event_id}")
            return True
        self._recent_event_ids[event_id] = now
        return False

    def get_default_parse_mode(self) -> str:
        """Get the default parse mode for Slack"""
        return "markdown"

    def should_use_thread_for_reply(self) -> bool:
        """Slack uses threads for replies"""
        return True

    def _ensure_clients(self):
        """Ensure web and socket clients are initialized"""
        if self.web_client is None:
            self.web_client = AsyncWebClient(token=self.config.bot_token)

        if self.socket_client is None and self.config.app_token:
            self.socket_client = SocketModeClient(
                app_token=self.config.app_token, web_client=self.web_client
            )

    def _convert_markdown_to_slack_mrkdwn(self, text: str) -> str:
        """Convert standard markdown to Slack mrkdwn format using third-party library

        Uses markdown-to-mrkdwn library for comprehensive conversion including:
        - Bold: ** to *
        - Italic: * to _
        - Strikethrough: ~~ to ~
        - Code blocks: ``` preserved
        - Inline code: ` preserved
        - Links: [text](url) to <url|text>
        - Headers, lists, quotes, and more
        """
        try:
            # Use the third-party converter for comprehensive markdown to mrkdwn conversion
            converted_text = self.markdown_converter.convert(text)
            return converted_text
        except Exception as e:
            logger.warning(
                f"Error converting markdown to mrkdwn: {e}, using original text"
            )
            # Fallback to original text if conversion fails
            return text

    async def send_message(
        self,
        context: MessageContext,
        text: str,
        parse_mode: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> str:
        """Send a message to Slack"""
        self._ensure_clients()
        try:
            if not text:
                raise ValueError("Slack send_message requires non-empty text")
            # Convert markdown to Slack mrkdwn if needed
            if parse_mode == "markdown":
                text = self._convert_markdown_to_slack_mrkdwn(text)

            # Prepare message kwargs
            kwargs = {"channel": context.channel_id, "text": text}

            # Handle thread replies
            if context.thread_id:
                kwargs["thread_ts"] = context.thread_id
                # Optionally broadcast to channel
                if context.platform_specific and context.platform_specific.get(
                    "reply_broadcast"
                ):
                    kwargs["reply_broadcast"] = True
            elif reply_to:
                # If reply_to is specified, use it as thread timestamp
                kwargs["thread_ts"] = reply_to

            # Handle formatting
            if parse_mode == "markdown":
                kwargs["mrkdwn"] = True

            # Workaround: ensure multi-line content is preserved. Slack sometimes collapses
            # rich_text rendering for bot messages; sending with blocks+mrkdwn forces line breaks.
            if "\n" in text and "blocks" not in kwargs and len(text) <= 3000:
                kwargs["blocks"] = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn"
                            if parse_mode == "markdown"
                            else "plain_text",
                            "text": text,
                        },
                    }
                ]

            # Send message
            response = await self.web_client.chat_postMessage(**kwargs)

            # Mark thread as active if we sent a message to a thread
            if self.settings_manager and (context.thread_id or reply_to):
                thread_ts = context.thread_id or reply_to
                self.settings_manager.mark_thread_active(
                    context.user_id, context.channel_id, thread_ts
                )
                logger.debug(f"Marked thread {thread_ts} as active after bot message")

            return response["ts"]

        except SlackApiError as e:
            logger.error(f"Error sending Slack message: {e}")
            raise

    async def upload_markdown(
        self,
        context: MessageContext,
        title: str,
        content: str,
        filetype: str = "markdown",
    ) -> str:
        self._ensure_clients()
        data = content or ""
        result = await self.web_client.files_upload_v2(
            channel=context.channel_id,
            thread_ts=context.thread_id,
            filename=title,
            title=title,
            content=data,
        )
        file_id = result.get("file", {}).get("id")
        if not file_id:
            file_id = result.get("files", [{}])[0].get("id")
        return file_id or ""

    async def add_reaction(
        self, context: MessageContext, message_id: str, emoji: str
    ) -> bool:
        """Add a reaction emoji to a Slack message."""
        self._ensure_clients()

        name = (emoji or "").strip()
        if name.startswith(":") and name.endswith(":") and len(name) > 2:
            name = name[1:-1]
        if name in ["👀", "eyes", "eye"]:
            name = "eyes"

        if not name:
            return False

        try:
            await self.web_client.reactions_add(
                channel=context.channel_id,
                timestamp=message_id,
                name=name,
            )
            return True
        except SlackApiError as err:
            try:
                if (
                    getattr(err, "response", None)
                    and err.response.get("error") == "already_reacted"
                ):
                    return True
            except Exception:
                pass

            error_code = None
            needed = None
            try:
                if getattr(err, "response", None):
                    error_code = err.response.get("error")
                    needed = err.response.get("needed")
            except Exception:
                pass

            # NOTE: reaction failures were previously DEBUG-only; surface at INFO/WARN for operability.
            if error_code in ["missing_scope", "not_in_channel", "channel_not_found"]:
                logger.warning(
                    f"Slack reaction add failed: error={error_code}, needed={needed}"
                )
            else:
                logger.info(f"Slack reaction add failed: {err}")
            return False
        except Exception as err:
            logger.debug(f"Failed to add Slack reaction: {err}")
            return False

    async def remove_reaction(
        self, context: MessageContext, message_id: str, emoji: str
    ) -> bool:
        """Remove a reaction emoji from a Slack message."""
        self._ensure_clients()

        name = (emoji or "").strip()
        if name.startswith(":") and name.endswith(":") and len(name) > 2:
            name = name[1:-1]
        if name in ["👀", "eyes", "eye"]:
            name = "eyes"

        if not name:
            return False

        try:
            await self.web_client.reactions_remove(
                channel=context.channel_id,
                timestamp=message_id,
                name=name,
            )
            return True
        except SlackApiError as err:
            logger.debug(f"Failed to remove Slack reaction: {err}")
            return False
        except Exception as err:
            logger.debug(f"Failed to remove Slack reaction: {err}")
            return False

    async def send_message_with_buttons(
        self,
        context: MessageContext,
        text: str,
        keyboard: InlineKeyboard,
        parse_mode: Optional[str] = None,
    ) -> str:
        """Send a message with interactive buttons"""
        self._ensure_clients()
        try:
            # Default to markdown for Slack if not specified
            if not parse_mode:
                parse_mode = "markdown"

            # Convert markdown to Slack mrkdwn if needed
            if parse_mode == "markdown":
                text = self._convert_markdown_to_slack_mrkdwn(text)

            # Convert our generic keyboard to Slack blocks
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn" if parse_mode == "markdown" else "plain_text",
                        "text": text,
                        "verbatim": True,
                    },
                }
            ]

            # Add action blocks for buttons
            for row_idx, row in enumerate(keyboard.buttons):
                elements = []
                for button in row:
                    elements.append(
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": button.text},
                            "action_id": button.callback_data,
                            "value": button.callback_data,
                        }
                    )

                blocks.append(
                    {
                        "type": "actions",
                        "block_id": f"actions_{row_idx}",
                        "elements": elements,
                    }
                )

            # Prepare message kwargs
            kwargs = {
                "channel": context.channel_id,
                "blocks": blocks,
                "text": text,  # Fallback text
            }

            # Handle thread replies
            if context.thread_id:
                kwargs["thread_ts"] = context.thread_id

            response = await self.web_client.chat_postMessage(**kwargs)

            # Mark thread as active if we sent a message to a thread
            if self.settings_manager and context.thread_id:
                self.settings_manager.mark_thread_active(
                    context.user_id, context.channel_id, context.thread_id
                )
                logger.debug(
                    f"Marked thread {context.thread_id} as active after bot message with buttons"
                )

            return response["ts"]

        except SlackApiError as e:
            logger.error(f"Error sending Slack message with buttons: {e}")
            raise

    async def edit_message(
        self,
        context: MessageContext,
        message_id: str,
        text: Optional[str] = None,
        keyboard: Optional[InlineKeyboard] = None,
        parse_mode: Optional[str] = None,
    ) -> bool:
        """Edit an existing Slack message"""
        self._ensure_clients()
        try:
            if text and parse_mode == "markdown":
                text = self._convert_markdown_to_slack_mrkdwn(text)

            kwargs = {"channel": context.channel_id, "ts": message_id}

            if text is not None:
                kwargs["text"] = text

            if keyboard:
                # Convert keyboard to blocks (similar to send_message_with_buttons)
                blocks = []
                if text:
                    blocks.append(
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn"
                                if parse_mode == "markdown"
                                else "plain_text",
                                "text": text,
                            },
                        }
                    )

                for row_idx, row in enumerate(keyboard.buttons):
                    elements = []
                    for button in row:
                        elements.append(
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": button.text},
                                "action_id": button.callback_data,
                                "value": button.callback_data,
                            }
                        )

                    blocks.append(
                        {
                            "type": "actions",
                            "block_id": f"actions_{row_idx}",
                            "elements": elements,
                        }
                    )

                kwargs["blocks"] = blocks

            await self.web_client.chat_update(**kwargs)
            return True

        except SlackApiError as e:
            logger.error(f"Error editing Slack message: {e}")
            return False

    async def remove_inline_keyboard(
        self,
        context: MessageContext,
        message_id: str,
        text: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> bool:
        """Remove interactive buttons from a Slack message."""
        self._ensure_clients()
        try:
            blocks = []
            fallback_text = text
            if fallback_text is not None and parse_mode == "markdown":
                fallback_text = self._convert_markdown_to_slack_mrkdwn(fallback_text)

            if fallback_text:
                blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn"
                            if parse_mode == "markdown"
                            else "plain_text",
                            "text": fallback_text,
                        },
                    }
                ]

            kwargs = {"channel": context.channel_id, "ts": message_id, "blocks": blocks}
            if fallback_text is not None:
                kwargs["text"] = fallback_text
            await self.web_client.chat_update(**kwargs)
            return True
        except SlackApiError as e:
            logger.error(f"Error removing Slack buttons: {e}")
            return False

    async def delete_message(
        self,
        context: MessageContext,
        message_id: str,
    ) -> bool:
        self._ensure_clients()
        try:
            await self.web_client.chat_delete(
                channel=context.channel_id,
                ts=message_id,
            )
            return True
        except SlackApiError as e:
            logger.debug(f"Failed to delete message: {e}")
            return False

    async def answer_callback(
        self, callback_id: str, text: Optional[str] = None, show_alert: bool = False
    ) -> bool:
        """Answer a Slack interactive callback"""
        # Slack does not have a direct equivalent to answer_callback_query
        # Instead, we typically update the message or send an ephemeral message
        # This will be handled in the event processing
        return True

    def register_handlers(self):
        """Register Slack event handlers"""
        if not self.socket_client:
            logger.warning(
                "Socket mode client not configured, skipping handler registration"
            )
            return

        # Register socket mode request handler
        self.socket_client.socket_mode_request_listeners.append(
            self._handle_socket_mode_request
        )

    async def _handle_socket_mode_request(
        self, client: SocketModeClient, req: SocketModeRequest
    ):
        """Handle incoming Socket Mode requests"""
        try:
            if req.type == "events_api":
                # Handle Events API events
                await self._handle_event(req.payload)
                # Acknowledge after handling events
                response = SocketModeResponse(envelope_id=req.envelope_id)
                await client.send_socket_mode_response(response)
            elif req.type == "interactive":
                payload_type = req.payload.get("type", "")
                if payload_type == "block_suggestion":
                    options_response = await self._handle_block_suggestion(req.payload)
                    response = SocketModeResponse(
                        envelope_id=req.envelope_id, payload=options_response
                    )
                    await client.send_socket_mode_response(response)
                else:
                    response = SocketModeResponse(envelope_id=req.envelope_id)
                    await client.send_socket_mode_response(response)
                    await self._handle_interactive(req.payload)
            else:
                # Unknown request type, still acknowledge
                response = SocketModeResponse(envelope_id=req.envelope_id)
                await client.send_socket_mode_response(response)

        except Exception as e:
            logger.error(f"Error handling socket mode request: {e}")
            # Still acknowledge even on error (if not already acknowledged)
            try:
                response = SocketModeResponse(envelope_id=req.envelope_id)
                await client.send_socket_mode_response(response)
            except Exception:
                pass  # Already acknowledged or connection issue

    async def _handle_event(self, payload: Dict[str, Any]):
        """Handle Events API events"""
        event = payload.get("event", {})
        event_type = event.get("type")
        event_id = payload.get("event_id")
        if self._is_duplicate_event(event_id):
            return

        if event_type == "message":
            # Ignore bot messages
            if event.get("bot_id"):
                return

            # Ignore message subtypes (edited, deleted, joins, etc.)
            # We only process plain user messages without subtype
            event_subtype = event.get("subtype")
            if event_subtype:
                logger.debug(f"Ignoring Slack message with subtype: {event_subtype}")
                return

            channel_id = event.get("channel")

            # Check if this message contains a bot mention
            # If it does, skip processing as it will be handled by app_mention event
            text = (event.get("text") or "").strip()
            import re

            if re.search(r"<@[\w]+>", text):
                logger.info(f"Skipping message event with bot mention: '{text}'")
                return

            # Ignore messages without user or without actual text
            user_id = event.get("user")
            if not user_id:
                logger.debug("Ignoring Slack message without user id")
                return
            if not text:
                logger.debug("Ignoring Slack message with empty text")
                return

            # Check if we require mention in channels (not DMs)
            # For threads: only respond if the bot is active in that thread
            is_thread_reply = event.get("thread_ts") is not None

            # Resolve effective require_mention: per-channel override or global default
            effective_require_mention = self.config.require_mention
            if self.settings_manager:
                effective_require_mention = self.settings_manager.get_require_mention(
                    channel_id, global_default=self.config.require_mention
                )

            if effective_require_mention and not channel_id.startswith("D"):
                # In channel main thread: require mention (silently ignore)
                if not is_thread_reply:
                    logger.debug(f"Ignoring non-mention message in channel: '{text}'")
                    return

                # In thread: check if bot is active in this thread
                if is_thread_reply:
                    thread_ts = event.get("thread_ts")
                    # If we have settings_manager, check if thread is active
                    if self.settings_manager:
                        if not self.settings_manager.is_thread_active(
                            user_id, channel_id, thread_ts
                        ):
                            logger.debug(
                                f"Ignoring message in inactive thread {thread_ts}: '{text}'"
                            )
                            return
                    else:
                        # Without settings_manager, fall back to ignoring non-mention in threads
                        logger.debug(
                            f"No settings_manager, ignoring thread message: '{text}'"
                        )
                        return

            # Only check channel authorization for messages we're actually going to process
            if not await self._is_authorized_channel(channel_id):
                logger.info(f"Unauthorized message from channel: {channel_id}")
                await self._send_unauthorized_message(channel_id)
                return

            # Extract context
            # For Slack: if no thread_ts, use the message's own ts as thread_id (start of thread)
            thread_id = event.get("thread_ts") or event.get("ts")

            context = MessageContext(
                user_id=user_id,
                channel_id=channel_id,
                thread_id=thread_id,  # Always have a thread_id
                message_id=event.get("ts"),
                platform_specific={"team_id": payload.get("team_id"), "event": event},
            )

            if text == "/":
                logger.info("Slash-only message, showing command selector")
                await self.send_command_selector(context)
                return

            if text.startswith("/"):
                parts = text.split(maxsplit=1)
                command = parts[0][1:]
                args = parts[1] if len(parts) > 1 else ""

                if command in self.on_command_callbacks:
                    handler = self.on_command_callbacks[command]
                    await handler(context, args)
                    return

            if self.on_message_callback:
                logger.info(
                    f"Processing message event: channel={channel_id}, thread={thread_id}, ts={event.get('ts')}, text='{text[:50]}...'"
                )
                await self.on_message_callback(context, text)

        elif event_type == "app_mention":
            # Handle @mentions
            channel_id = event.get("channel")

            # Check if channel is authorized based on whitelist
            if not await self._is_authorized_channel(channel_id):
                logger.info(f"Unauthorized mention from channel: {channel_id}")
                await self._send_unauthorized_message(channel_id)
                return

            # For Slack: if no thread_ts, use the message's own ts as thread_id (start of thread)
            thread_id = event.get("thread_ts") or event.get("ts")

            context = MessageContext(
                user_id=event.get("user"),
                channel_id=channel_id,
                thread_id=thread_id,  # Always have a thread_id
                message_id=event.get("ts"),
                platform_specific={"team_id": payload.get("team_id"), "event": event},
            )

            # Mark thread as active when bot is @mentioned
            if self.settings_manager and thread_id:
                self.settings_manager.mark_thread_active(
                    event.get("user"), channel_id, thread_id
                )
                logger.info(f"Marked thread {thread_id} as active due to @mention")

            # Remove the mention from the text
            text = event.get("text", "")
            import re

            text = re.sub(r"<@[\w]+>", "", text).strip()

            logger.info(
                f"App mention processed: original='{event.get('text')}', cleaned='{text}'"
            )

            if not text:
                if "start" in self.on_command_callbacks:
                    logger.info("Empty @mention, showing welcome message")
                    await self.on_command_callbacks["start"](context, "")
                    return

            if text == "/":
                logger.info("Slash-only message, showing command selector")
                await self.send_command_selector(context)
                return

            if text.startswith("/"):
                parts = text.split(maxsplit=1)
                command = parts[0][1:]
                args = parts[1] if len(parts) > 1 else ""

                logger.info(
                    f"Command detected: '{command}', available: {list(self.on_command_callbacks.keys())}"
                )

                if command in self.on_command_callbacks:
                    logger.info(f"Executing command handler for: {command}")
                    handler = self.on_command_callbacks[command]
                    await handler(context, args)
                    return
                else:
                    logger.warning(f"Command '{command}' not found in callbacks")

            logger.info(f"Handling as regular message: '{text}'")
            if self.on_message_callback:
                await self.on_message_callback(context, text)

        elif event_type == "app_home_opened":
            user_id = event.get("user")
            tab = event.get("tab")
            if tab == "home" and hasattr(self, "_on_app_home_opened"):
                await self._on_app_home_opened(user_id)

    async def _handle_interactive(self, payload: Dict[str, Any]):
        """Handle interactive components (buttons, modal submissions, etc.)"""
        if payload.get("type") == "block_actions":
            # Handle button clicks / select changes
            user = payload.get("user", {})
            actions = payload.get("actions", [])
            view = payload.get("view", {})

            # Check for update button click (handled before channel authorization)
            for action in actions:
                if action.get("action_id") == "vibe_update_now":
                    from core.update_checker import handle_update_button_click

                    if hasattr(self, "_controller") and self._controller:
                        await handle_update_button_click(self._controller, payload)
                    return

            # In Slack modals, `channel` is often missing. We store the originating
            # channel_id in `view.private_metadata` when opening the modal.
            channel_id = (
                payload.get("channel", {}).get("id")
                or payload.get("container", {}).get("channel_id")
                or (view.get("private_metadata") if isinstance(view, dict) else None)
            )

            # Check if channel is authorized for interactive components
            if not await self._is_authorized_channel(channel_id):
                logger.info(
                    f"Unauthorized interactive action from channel: {channel_id}"
                )
                try:
                    await self._send_unauthorized_message(channel_id)
                except Exception as e:
                    logger.debug(
                        "Failed to send unauthorized message to channel %s: %s",
                        channel_id,
                        e,
                    )
                return

            view = payload.get("view", {})
            for action in actions:
                action_type = action.get("type")
                if action_type == "button":
                    callback_data = action.get("action_id")

                    if callback_data in {
                        "home_edit_opencode_env",
                        "home_edit_claude_env",
                    }:
                        trigger_id = payload.get("trigger_id")
                        if trigger_id and hasattr(self, "_on_home_edit_env"):
                            await self._on_home_edit_env(
                                user.get("id"), callback_data, trigger_id
                            )
                        continue

                    if self.on_callback_query_callback:
                        thread_id = (
                            payload.get("container", {}).get("thread_ts")
                            or payload.get("message", {}).get("thread_ts")
                            or payload.get("message", {}).get("ts")
                        )
                        # Create a context for the callback
                        context = MessageContext(
                            user_id=user.get("id"),
                            channel_id=channel_id,
                            thread_id=thread_id,
                            message_id=payload.get("message", {}).get("ts"),
                            platform_specific={
                                "trigger_id": payload.get("trigger_id"),
                                "response_url": payload.get("response_url"),
                                "action": action,
                                "payload": payload,
                            },
                        )

                        await self.on_callback_query_callback(context, callback_data)
                elif action_type in {"static_select", "external_select"}:
                    action_id = action.get("action_id")
                    if action_id == "session_select":
                        selected_session_id = action.get("selected_option", {}).get(
                            "value"
                        )
                        if selected_session_id and self.on_callback_query_callback:
                            private_metadata = view.get("private_metadata", "")
                            channel_from_view = None
                            agent_name = "opencode"
                            try:
                                import json

                                meta = json.loads(private_metadata)
                                channel_from_view = meta.get("channel_id")
                                agent_name = meta.get("agent_name", "opencode")
                            except (json.JSONDecodeError, TypeError):
                                channel_from_view = private_metadata
                            context = MessageContext(
                                user_id=user.get("id"),
                                channel_id=channel_from_view or channel_id,
                                platform_specific={
                                    "trigger_id": payload.get("trigger_id"),
                                    "payload": payload,
                                },
                            )
                            await self.on_callback_query_callback(
                                context,
                                f"resume_session:{agent_name}:{selected_session_id}",
                            )
                    elif action_id in {
                        "backend_select",
                        "opencode_agent_select",
                        "opencode_model_select",
                    }:
                        if hasattr(self, "_on_routing_modal_update"):
                            channel_from_view = view.get("private_metadata")
                            await self._on_routing_modal_update(
                                user.get("id"),
                                channel_from_view or channel_id,
                                view,
                                action,
                            )
                    elif action_id == "home_channel_select":
                        if hasattr(self, "_on_home_channel_select"):
                            selected_option = action.get("selected_option", {})
                            selected_channel_id = selected_option.get("value")
                            await self._on_home_channel_select(
                                user.get("id"),
                                selected_channel_id,
                            )
                    elif action_id in {
                        "home_backend_select",
                        "home_opencode_agent_select",
                        "home_opencode_model_select",
                        "home_opencode_reasoning_select",
                        "home_claude_mode_select",
                        "home_claude_model_select",
                    }:
                        if hasattr(self, "_on_home_setting_change"):
                            selected_option = action.get("selected_option", {})
                            selected_value = selected_option.get("value")
                            await self._on_home_setting_change(
                                user.get("id"),
                                action_id,
                                selected_value,
                            )
                    elif action_id == "slash_command_select":
                        selected_option = action.get("selected_option", {})
                        selected_command = selected_option.get("value")
                        if selected_command and self.on_callback_query_callback:
                            thread_id = (
                                payload.get("container", {}).get("thread_ts")
                                or payload.get("message", {}).get("thread_ts")
                                or payload.get("message", {}).get("ts")
                            )
                            context = MessageContext(
                                user_id=user.get("id"),
                                channel_id=channel_id,
                                thread_id=thread_id,
                                message_id=payload.get("message", {}).get("ts"),
                                platform_specific={
                                    "trigger_id": payload.get("trigger_id"),
                                    "response_url": payload.get("response_url"),
                                    "payload": payload,
                                },
                            )
                            await self.on_callback_query_callback(
                                context, f"exec_slash_command:{selected_command}"
                            )

        elif payload.get("type") == "view_submission":
            # Handle modal submissions asynchronously to avoid Slack timeouts
            asyncio.create_task(self._handle_view_submission(payload))
            return

    async def _handle_view_submission(self, payload: Dict[str, Any]):
        """Handle modal dialog submissions"""
        view = payload.get("view", {})
        callback_id = view.get("callback_id")

        if callback_id == "settings_modal":
            # Handle settings modal submission
            user_id = payload.get("user", {}).get("id")
            values = view.get("state", {}).get("values", {})

            # Extract selected show message types
            show_types_data = values.get("show_message_types", {}).get(
                "show_types_select", {}
            )
            selected_options = show_types_data.get("selected_options", [])

            # Get the values from selected options
            show_types = [opt.get("value") for opt in selected_options]

            # Extract require_mention setting
            require_mention_data = values.get("require_mention_block", {}).get(
                "require_mention_select", {}
            )
            require_mention_value = require_mention_data.get("selected_option", {}).get(
                "value"
            )
            # Convert to Optional[bool]: "__default__" -> None, "true" -> True, "false" -> False
            if require_mention_value == "__default__":
                require_mention = None
            elif require_mention_value == "true":
                require_mention = True
            elif require_mention_value == "false":
                require_mention = False
            else:
                require_mention = None

            # Get channel_id from the view's private_metadata if available
            channel_id = view.get("private_metadata")

            # Update settings - need access to settings manager
            if hasattr(self, "_on_settings_update"):
                await self._on_settings_update(
                    user_id, show_types, channel_id, require_mention
                )

        elif callback_id == "change_cwd_modal":
            # Handle change CWD modal submission
            user_id = payload.get("user", {}).get("id")
            values = view.get("state", {}).get("values", {})

            # Extract new CWD path
            new_cwd_data = values.get("new_cwd_block", {}).get("new_cwd_input", {})
            new_cwd = new_cwd_data.get("value", "")

            # Get channel_id from private_metadata
            channel_id = view.get("private_metadata")

            # Update CWD - need access to controller or settings manager
            if hasattr(self, "_on_change_cwd"):
                await self._on_change_cwd(user_id, new_cwd, channel_id)

            # Send success message to the user (via DM or channel)
            # We need to find the right channel to send the message
            # For now, we'll rely on the controller to handle this

        elif callback_id == "opencode_question_modal":
            user_id = payload.get("user", {}).get("id")
            values = view.get("state", {}).get("values", {})
            metadata_raw = view.get("private_metadata")

            try:
                import json

                metadata = json.loads(metadata_raw) if metadata_raw else {}
            except Exception:
                metadata = {}

            channel_id = metadata.get("channel_id")
            thread_id = metadata.get("thread_id")

            answers = []
            q_count = int(metadata.get("question_count") or 1)
            for idx in range(q_count):
                block_id = f"q{idx}"
                action_id = "select"
                data = values.get(block_id, {}).get(action_id, {})
                selected_options = data.get("selected_options")
                if isinstance(selected_options, list):
                    answers.append(
                        [
                            opt.get("value")
                            for opt in selected_options
                            if opt.get("value")
                        ]
                    )
                else:
                    selected = data.get("selected_option")
                    if selected and selected.get("value") is not None:
                        answers.append([str(selected.get("value"))])
                    else:
                        answers.append([])

            if self.on_callback_query_callback:
                context = MessageContext(
                    user_id=user_id,
                    channel_id=str(channel_id) if channel_id else "",
                    thread_id=str(thread_id) if thread_id else None,
                    platform_specific={"payload": payload},
                )
                await self.on_callback_query_callback(
                    context,
                    "opencode_question:modal:" + json.dumps({"answers": answers}),
                )

        elif callback_id == "routing_modal":
            # Handle routing modal submission
            user_id = payload.get("user", {}).get("id")
            values = view.get("state", {}).get("values", {})
            channel_id = view.get("private_metadata")

            # Extract backend
            backend_data = values.get("backend_block", {}).get("backend_select", {})
            backend = backend_data.get("selected_option", {}).get("value")

            # Extract OpenCode agent (optional)
            oc_agent_data = values.get("opencode_agent_block", {}).get(
                "opencode_agent_select", {}
            )
            oc_agent = oc_agent_data.get("selected_option", {}).get("value")
            if oc_agent == "__default__":
                oc_agent = None

            # Extract OpenCode model (optional)
            oc_model_data = values.get("opencode_model_block", {}).get(
                "opencode_model_select", {}
            )
            oc_model = oc_model_data.get("selected_option", {}).get("value")
            if oc_model == "__default__":
                oc_model = None

            # Extract OpenCode reasoning effort (optional)
            oc_reasoning = None
            reasoning_block = values.get("opencode_reasoning_block", {})
            if isinstance(reasoning_block, dict):
                for action_id, action_data in reasoning_block.items():
                    if (
                        isinstance(action_id, str)
                        and action_id.startswith("opencode_reasoning_select")
                        and isinstance(action_data, dict)
                    ):
                        oc_reasoning = action_data.get("selected_option", {}).get(
                            "value"
                        )
                        break
            if oc_reasoning == "__default__":
                oc_reasoning = None

            # Extract require_mention (optional)
            require_mention_data = values.get("require_mention_block", {}).get(
                "require_mention_select", {}
            )
            require_mention_value = require_mention_data.get("selected_option", {}).get(
                "value"
            )
            # Convert to Optional[bool]: "__default__" -> None, "true" -> True, "false" -> False
            if require_mention_value == "__default__":
                require_mention = None
            elif require_mention_value == "true":
                require_mention = True
            elif require_mention_value == "false":
                require_mention = False
            else:
                require_mention = None

            env_vars_data = values.get("opencode_env_vars_block", {}).get(
                "opencode_env_vars_input", {}
            )
            env_vars_text = env_vars_data.get("value", "") or ""
            env_vars: Dict[str, str] = {}
            for line in env_vars_text.strip().split("\n"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key:
                    env_vars[key] = value

            claude_model_data = values.get("claude_model_block", {}).get(
                "claude_model_select", {}
            )
            claude_model = claude_model_data.get("selected_option", {}).get("value")

            claude_mode_data = values.get("claude_mode_block", {}).get(
                "claude_mode_select", {}
            )
            claude_mode = claude_mode_data.get("selected_option", {}).get("value")
            if claude_mode == "__default__":
                claude_mode = None

            claude_env_vars_data = values.get("claude_env_vars_block", {}).get(
                "claude_env_vars_input", {}
            )
            claude_env_vars_text = claude_env_vars_data.get("value", "") or ""
            claude_env_vars: Dict[str, str] = {}
            for line in claude_env_vars_text.strip().split("\n"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key:
                    claude_env_vars[key] = value

            if hasattr(self, "_on_routing_update"):
                await self._on_routing_update(
                    user_id,
                    channel_id,
                    backend,
                    oc_agent,
                    oc_model,
                    oc_reasoning,
                    require_mention,
                    env_vars,
                    claude_mode,
                    claude_model,
                    claude_env_vars,
                )

        elif callback_id in {"home_env_modal_opencode", "home_env_modal_claude"}:
            user_id = payload.get("user", {}).get("id")
            values = view.get("state", {}).get("values", {})

            env_vars_data = values.get("env_vars_block", {}).get("env_vars_input", {})
            env_vars_text = env_vars_data.get("value", "") or ""
            env_vars: Dict[str, str] = {}
            for line in env_vars_text.strip().split("\n"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key:
                    env_vars[key] = value

            env_type = (
                "opencode" if callback_id == "home_env_modal_opencode" else "claude"
            )
            if hasattr(self, "_on_home_env_save"):
                await self._on_home_env_save(user_id, env_type, env_vars)

    async def _handle_block_suggestion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle external_select options requests for dynamic command selection"""
        action_id = payload.get("action_id", "")
        value = payload.get("value", "")

        if action_id == "slash_command_select":
            return await self._get_slash_command_options(value)

        return {"options": []}

    async def _get_slash_command_options(self, keyword: str) -> Dict[str, Any]:
        """Get slash command options from ~/.claude/commands/ directory"""
        import os
        from pathlib import Path

        commands_dir = Path.home() / ".claude" / "commands"
        options = []

        if commands_dir.exists():
            for cmd_file in sorted(commands_dir.glob("*.md")):
                cmd_name = cmd_file.stem
                if not keyword or keyword.lower() in cmd_name.lower():
                    options.append(
                        {
                            "text": {"type": "plain_text", "text": f"/{cmd_name}"},
                            "value": cmd_name,
                        }
                    )

        return {"options": options[:100]}

    async def send_command_selector(
        self,
        context: MessageContext,
        thread_ts: Optional[str] = None,
    ) -> str:
        """Send a message with external_select for slash command selection"""
        self._ensure_clients()

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Select a command:*",
                },
                "accessory": {
                    "type": "external_select",
                    "action_id": "slash_command_select",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Type to search commands...",
                    },
                    "min_query_length": 0,
                },
            }
        ]

        kwargs = {
            "channel": context.channel_id,
            "text": "Select a command",
            "blocks": blocks,
        }

        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        elif context.thread_id:
            kwargs["thread_ts"] = context.thread_id

        response = await self.web_client.chat_postMessage(**kwargs)
        return response["ts"]

    def run(self):
        """Run the Slack bot"""
        if self.config.app_token:
            # Socket Mode
            logger.info("Starting Slack bot in Socket Mode...")

            async def start():
                self._ensure_clients()
                self.register_handlers()
                self._loop = asyncio.get_running_loop()
                self._stop_event = asyncio.Event()
                await self.socket_client.connect()
                # Call on_ready callback after successful connection
                if self._on_ready:
                    try:
                        await self._on_ready()
                    except Exception as e:
                        logger.error(f"on_ready callback failed: {e}", exc_info=True)
                await self._stop_event.wait()
                await self._async_close()

            asyncio.run(start())
        else:
            # Web API only mode (for development/testing)
            logger.warning("No app token provided, running in Web API only mode")

            async def start():
                self._ensure_clients()
                self._loop = asyncio.get_running_loop()
                self._stop_event = asyncio.Event()
                # Call on_ready callback (even in Web API only mode)
                if self._on_ready:
                    try:
                        await self._on_ready()
                    except Exception as e:
                        logger.error(f"on_ready callback failed: {e}", exc_info=True)
                await self._stop_event.wait()
                await self._async_close()

            try:
                asyncio.run(start())
            except KeyboardInterrupt:
                logger.info("Shutting down...")

    def stop(self) -> None:
        if self._stop_event is None:
            return
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop_event.set)
        else:
            self._stop_event.set()

    async def shutdown(self) -> None:
        """Best-effort async shutdown for Slack clients."""
        if self._stop_event is not None:
            self._stop_event.set()

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._loop and self._loop.is_running() and self._loop is not current_loop:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_close(), self._loop
                )
                future.result(timeout=5)
            except Exception as exc:
                logger.debug(f"Slack shutdown dispatch failed: {exc}")
            return

        await self._async_close()

    async def _async_close(self) -> None:
        if self.socket_client is not None:
            try:
                disconnect = getattr(self.socket_client, "disconnect", None)
                if callable(disconnect):
                    result = disconnect()
                    if asyncio.iscoroutine(result):
                        await result
            except Exception as exc:
                logger.debug(f"Socket mode disconnect failed: {exc}")
            try:
                close = getattr(self.socket_client, "close", None)
                if callable(close):
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
            except Exception as exc:
                logger.debug(f"Socket mode close failed: {exc}")

        if self.web_client is not None:
            try:
                await self.web_client.close()
            except Exception as exc:
                logger.debug(f"Slack web client close failed: {exc}")

    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get information about a Slack user"""
        self._ensure_clients()
        try:
            response = await self.web_client.users_info(user=user_id)
            user = response["user"]
            return {
                "id": user["id"],
                "name": user.get("name"),
                "real_name": user.get("real_name"),
                "display_name": user.get("profile", {}).get("display_name"),
                "email": user.get("profile", {}).get("email"),
                "is_bot": user.get("is_bot", False),
            }
        except SlackApiError as e:
            logger.error(f"Error getting user info: {e}")
            raise

    async def get_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """Get information about a Slack channel"""
        self._ensure_clients()
        try:
            response = await self.web_client.conversations_info(channel=channel_id)
            channel = response["channel"]
            return {
                "id": channel["id"],
                "name": channel.get("name"),
                "is_private": channel.get("is_private", False),
                "is_im": channel.get("is_im", False),
                "is_channel": channel.get("is_channel", False),
                "topic": channel.get("topic", {}).get("value"),
                "purpose": channel.get("purpose", {}).get("value"),
            }
        except SlackApiError as e:
            logger.error(f"Error getting channel info: {e}")
            raise

    async def get_bot_channels(self) -> List[Dict[str, Any]]:
        """Get list of channels the bot is a member of."""
        self._ensure_clients()
        channels = []
        cursor = None
        try:
            while True:
                response = await self.web_client.conversations_list(
                    types="public_channel,private_channel",
                    exclude_archived=True,
                    limit=200,
                    cursor=cursor,
                )
                for channel in response.get("channels", []):
                    if channel.get("is_member", False):
                        channels.append(
                            {
                                "id": channel.get("id"),
                                "name": channel.get("name"),
                                "is_private": channel.get("is_private", False),
                            }
                        )
                cursor = response.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
            return sorted(channels, key=lambda x: x.get("name", "").lower())
        except SlackApiError as e:
            logger.error(f"Error getting bot channels: {e}")
            return []

    def format_markdown(self, text: str) -> str:
        """Format markdown text for Slack mrkdwn format

        Slack uses single asterisks for bold and different formatting rules
        """
        # Convert double asterisks to single for bold
        formatted = text.replace("**", "*")

        # Convert inline code blocks (backticks work the same)
        # Lists work similarly
        # Links work similarly [text](url) -> <url|text>
        # But we'll keep simple for now - just handle bold

        return formatted

    async def open_settings_modal(
        self,
        trigger_id: str,
        user_settings: Any,
        message_types: list,
        display_names: dict,
        channel_id: str = None,
        current_require_mention: object = None,  # None=default, True, False
        global_require_mention: bool = False,
    ):
        """Open a modal dialog for settings"""
        self._ensure_clients()

        # Create options for the multi-select menu
        options = []
        selected_options = []

        for msg_type in message_types:
            display_name = display_names.get(msg_type, msg_type)
            option = {
                "text": {"type": "plain_text", "text": display_name, "emoji": True},
                "value": msg_type,
                "description": {
                    "type": "plain_text",
                    "text": self._get_message_type_description(msg_type),
                    "emoji": True,
                },
            }
            options.append(option)

            # If this type is shown, add THE SAME option object to selected options
            if msg_type in user_settings.show_message_types:
                selected_options.append(option)  # Same object reference!

        logger.info(
            f"Creating modal with {len(options)} options, {len(selected_options)} selected"
        )
        logger.info(f"Show types: {user_settings.show_message_types}")

        # Debug: Log the actual data being sent
        import json

        logger.info(f"Options: {json.dumps(options, indent=2)}")
        logger.info(f"Selected options: {json.dumps(selected_options, indent=2)}")

        # Create the multi-select element
        multi_select_element = {
            "type": "multi_static_select",
            "placeholder": {
                "type": "plain_text",
                "text": "Select message types to show",
                "emoji": True,
            },
            "options": options,
            "action_id": "show_types_select",
        }

        # Only add initial_options if there are selected options
        if selected_options:
            multi_select_element["initial_options"] = selected_options

        # Build require_mention selector
        global_mention_label = "On" if global_require_mention else "Off"
        require_mention_options = [
            {
                "text": {
                    "type": "plain_text",
                    "text": f"(Default) - {global_mention_label}",
                },
                "value": "__default__",
            },
            {
                "text": {"type": "plain_text", "text": "Require @mention"},
                "value": "true",
            },
            {
                "text": {"type": "plain_text", "text": "Don't require @mention"},
                "value": "false",
            },
        ]

        # Determine initial option for require_mention
        initial_require_mention = require_mention_options[0]  # Default
        if current_require_mention is not None:
            target_value = "true" if current_require_mention else "false"
            for opt in require_mention_options:
                if opt["value"] == target_value:
                    initial_require_mention = opt
                    break

        require_mention_select = {
            "type": "static_select",
            "action_id": "require_mention_select",
            "placeholder": {"type": "plain_text", "text": "Select @mention behavior"},
            "options": require_mention_options,
            "initial_option": initial_require_mention,
        }

        # Create the modal view
        view = {
            "type": "modal",
            "callback_id": "settings_modal",
            "private_metadata": channel_id or "",  # Store channel_id for later use
            "title": {"type": "plain_text", "text": "Settings", "emoji": True},
            "submit": {"type": "plain_text", "text": "Save", "emoji": True},
            "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Channel Behavior",
                        "emoji": True,
                    },
                },
                {
                    "type": "input",
                    "block_id": "require_mention_block",
                    "element": require_mention_select,
                    "label": {
                        "type": "plain_text",
                        "text": "Require @mention to respond",
                        "emoji": True,
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "_When enabled, the bot only responds when @mentioned in channels (DMs always work)._",
                        }
                    ],
                },
                {"type": "divider"},
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Message Visibility",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Choose which message types to *show* from agent output. Unselected types won't appear in your Slack workspace.",
                    },
                },
                {
                    "type": "input",
                    "block_id": "show_message_types",
                    "element": multi_select_element,
                    "label": {
                        "type": "plain_text",
                        "text": "Show these message types:",
                        "emoji": True,
                    },
                    "optional": True,
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "_💡 Tip: You can show/hide message types at any time. Changes apply immediately to new messages._",
                        }
                    ],
                },
            ],
        }

        try:
            await self.web_client.views_open(trigger_id=trigger_id, view=view)
        except SlackApiError as e:
            logger.error(f"Error opening modal: {e}")
            raise

    def _get_message_type_description(self, msg_type: str) -> str:
        """Get description for a message type"""
        descriptions = {
            "system": "System initialization and status messages",
            "toolcall": "Agent tool name + params (one line)",
            "assistant": "Agent responses and explanations",
        }
        return descriptions.get(msg_type, f"{msg_type} messages")

    async def open_change_cwd_modal(
        self, trigger_id: str, current_cwd: str, channel_id: str = None
    ):
        """Open a modal dialog for changing working directory"""
        self._ensure_clients()

        # Create the modal view
        view = {
            "type": "modal",
            "callback_id": "change_cwd_modal",
            "private_metadata": channel_id or "",  # Store channel_id for later use
            "title": {
                "type": "plain_text",
                "text": "Change Working Directory",
                "emoji": True,
            },
            "submit": {"type": "plain_text", "text": "Change", "emoji": True},
            "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Current working directory:\n`{current_cwd}`",
                    },
                },
                {"type": "divider"},
                {
                    "type": "input",
                    "block_id": "new_cwd_block",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "new_cwd_input",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Enter new directory path",
                            "emoji": True,
                        },
                        "initial_value": current_cwd,
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "New Working Directory:",
                        "emoji": True,
                    },
                    "hint": {
                        "type": "plain_text",
                        "text": "Use absolute path (e.g., /home/user/project) or ~ for home directory",
                        "emoji": True,
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "💡 _Tip: The directory will be created if it doesn't exist._",
                        }
                    ],
                },
            ],
        }

        try:
            await self.web_client.views_open(trigger_id=trigger_id, view=view)
        except SlackApiError as e:
            logger.error(f"Error opening change CWD modal: {e}")
            raise

    async def open_sessions_modal(
        self,
        trigger_id: str,
        sessions: list,
        working_path: str,
        channel_id: str = None,
        agent_name: str = "opencode",
    ):
        self._ensure_clients()
        import json
        from datetime import datetime

        agent_label = "Claude Code" if agent_name == "claude" else "OpenCode"
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"📁 目录：`{working_path}`\n🤖 Agent：{agent_label}",
                },
            },
            {"type": "divider"},
        ]

        if not sessions:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "📋 没有找到会话\n\n💡 发送消息开始新对话",
                    },
                }
            )
        else:
            options = []
            for session in sessions[:20]:
                session_id = session.get("id", "unknown")
                title = session.get("title", "")

                time_str = ""
                time_info = session.get("time", {})
                updated_ts = time_info.get("updated", 0) or time_info.get("created", 0)
                if updated_ts:
                    time_str = datetime.fromtimestamp(updated_ts / 1000).strftime(
                        "%m-%d %H:%M"
                    )
                else:
                    modified_iso = session.get("modified", "") or session.get(
                        "created", ""
                    )
                    if modified_iso:
                        try:
                            dt = datetime.fromisoformat(
                                modified_iso.replace("Z", "+00:00")
                            )
                            time_str = dt.strftime("%m-%d %H:%M")
                        except (ValueError, TypeError):
                            pass

                if title.startswith("vibe-remote:"):
                    title = ""

                display_text = (
                    f"{time_str} {title}" if title else f"{time_str} {session_id[:16]}"
                )
                display_text = display_text.strip()[:70]

                options.append(
                    {
                        "text": {
                            "type": "plain_text",
                            "text": display_text or session_id[:20],
                        },
                        "value": session_id,
                    }
                )

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"📋 找到 {len(sessions)} 个会话，选择要恢复的：",
                    },
                }
            )
            blocks.append(
                {
                    "type": "actions",
                    "block_id": "session_select_block",
                    "elements": [
                        {
                            "type": "static_select",
                            "action_id": "session_select",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "选择会话...",
                            },
                            "options": options,
                        }
                    ],
                }
            )
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": "💡 选择后在线程中输入消息继续对话"}
                    ],
                }
            )

        metadata = json.dumps(
            {"channel_id": channel_id or "", "agent_name": agent_name}
        )
        view = {
            "type": "modal",
            "callback_id": "sessions_modal",
            "private_metadata": metadata,
            "title": {"type": "plain_text", "text": "恢复会话"},
            "close": {"type": "plain_text", "text": "关闭"},
            "blocks": blocks,
        }

        try:
            await self.web_client.views_open(trigger_id=trigger_id, view=view)
        except SlackApiError as e:
            logger.error(f"Error opening sessions modal: {e}")
            raise

    async def open_diff_modal(
        self,
        trigger_id: str,
        stat_output: str,
        diff_output: str,
        working_path: str,
        channel_id: str = None,
    ):
        self._ensure_clients()

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"📁 目录：`{working_path}`"},
            },
            {"type": "divider"},
        ]

        if not stat_output:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "✅ 没有未提交的更改"},
                }
            )
        else:
            truncated_stat = (
                stat_output[:2800] if len(stat_output) > 2800 else stat_output
            )
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```\n{truncated_stat}\n```"},
                }
            )

            if diff_output and len(diff_output) > 100:
                diff_preview = diff_output[:1500]
                if len(diff_output) > 1500:
                    diff_preview += "\n\n... (内容过长，已截断)"
                blocks.append({"type": "divider"})
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*详细变更：*\n```\n{diff_preview}\n```",
                        },
                    }
                )

        view = {
            "type": "modal",
            "callback_id": "diff_modal",
            "private_metadata": channel_id or "",
            "title": {"type": "plain_text", "text": "Git 变更"},
            "close": {"type": "plain_text", "text": "关闭"},
            "blocks": blocks,
        }

        try:
            await self.web_client.views_open(trigger_id=trigger_id, view=view)
        except SlackApiError as e:
            logger.error(f"Error opening diff modal: {e}")
            raise

    def _get_default_opencode_agent_name(self, opencode_agents: list) -> Optional[str]:
        """Resolve the default OpenCode agent name."""
        for agent in opencode_agents:
            name = agent.get("name")
            if name == "build":
                return name
        for agent in opencode_agents:
            name = agent.get("name")
            if name:
                return name
        return None

    def _resolve_opencode_default_model(
        self,
        opencode_default_config: dict,
        opencode_agents: list,
        selected_agent: Optional[str],
    ) -> Optional[str]:
        """Resolve the default model for a selected OpenCode agent."""
        agent_name = selected_agent or self._get_default_opencode_agent_name(
            opencode_agents
        )
        if isinstance(opencode_default_config, dict):
            agents_config = opencode_default_config.get("agent", {})
            if isinstance(agents_config, dict) and agent_name:
                agent_config = agents_config.get(agent_name, {})
                if isinstance(agent_config, dict):
                    model = agent_config.get("model")
                    if isinstance(model, str) and model:
                        return model
            model = opencode_default_config.get("model")
            if isinstance(model, str) and model:
                return model
        return None

    def _build_routing_modal_view(
        self,
        channel_id: str,
        registered_backends: list,
        current_backend: str,
        current_routing,
        opencode_agents: list,
        opencode_models: dict,
        opencode_default_config: dict,
        selected_backend: object = _UNSET,
        selected_opencode_agent: object = _UNSET,
        selected_opencode_model: object = _UNSET,
        selected_opencode_reasoning: object = _UNSET,
        current_require_mention: object = _UNSET,
        global_require_mention: bool = False,
        current_env_vars: Optional[Dict[str, str]] = None,
        current_claude_mode: object = _UNSET,
        current_claude_env_vars: Optional[Dict[str, str]] = None,
    ) -> dict:
        """Build modal view for agent/model routing settings."""
        # Build backend options
        backend_display_names = {
            "claude": "Claude Code",
            "codex": "Codex",
            "opencode": "OpenCode",
        }
        backend_options = []
        for backend in registered_backends:
            display_name = backend_display_names.get(backend, backend.capitalize())
            backend_options.append(
                {
                    "text": {"type": "plain_text", "text": display_name},
                    "value": backend,
                }
            )

        # Find initial backend option
        selected_backend_value = (
            current_backend if selected_backend is _UNSET else selected_backend
        )
        initial_backend = None
        for option in backend_options:
            if option["value"] == selected_backend_value:
                initial_backend = option
                break
        if initial_backend is None and backend_options:
            initial_backend = backend_options[0]

        backend_select = {
            "type": "static_select",
            "action_id": "backend_select",
            "placeholder": {"type": "plain_text", "text": "Select backend"},
            "options": backend_options,
            "initial_option": initial_backend,
        }

        # Build modal blocks
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Current Backend:* {backend_display_names.get(current_backend, current_backend)}",
                },
            },
            {"type": "divider"},
            {
                "type": "input",
                "block_id": "backend_block",
                "dispatch_action": True,
                "element": backend_select,
                "label": {"type": "plain_text", "text": "Backend"},
            },
        ]

        # Add require_mention selector
        # Build options: Default (uses global), Require @mention, Don't require @mention
        global_mention_label = "On" if global_require_mention else "Off"
        require_mention_options = [
            {
                "text": {
                    "type": "plain_text",
                    "text": f"(Default) - {global_mention_label}",
                },
                "value": "__default__",
            },
            {
                "text": {"type": "plain_text", "text": "Require @mention"},
                "value": "true",
            },
            {
                "text": {"type": "plain_text", "text": "Don't require @mention"},
                "value": "false",
            },
        ]

        # Determine initial option
        initial_require_mention = require_mention_options[0]  # Default
        if (
            current_require_mention is not _UNSET
            and current_require_mention is not None
        ):
            target_value = "true" if current_require_mention else "false"
            for opt in require_mention_options:
                if opt["value"] == target_value:
                    initial_require_mention = opt
                    break

        require_mention_select = {
            "type": "static_select",
            "action_id": "require_mention_select",
            "placeholder": {"type": "plain_text", "text": "Select @mention behavior"},
            "options": require_mention_options,
            "initial_option": initial_require_mention,
        }

        blocks.append(
            {
                "type": "input",
                "block_id": "require_mention_block",
                "element": require_mention_select,
                "label": {"type": "plain_text", "text": "Require @mention to respond"},
            }
        )

        # OpenCode-specific options (only if opencode is selected as backend)
        if "opencode" in registered_backends and selected_backend_value == "opencode":
            # Get current opencode settings
            if selected_opencode_agent is _UNSET:
                current_oc_agent = (
                    current_routing.opencode_agent if current_routing else None
                )
            else:
                current_oc_agent = selected_opencode_agent

            if selected_opencode_model is _UNSET:
                current_oc_model = (
                    current_routing.opencode_model if current_routing else None
                )
            else:
                current_oc_model = selected_opencode_model

            if selected_opencode_reasoning is _UNSET:
                current_oc_reasoning = (
                    current_routing.opencode_reasoning_effort
                    if current_routing
                    else None
                )
            else:
                current_oc_reasoning = selected_opencode_reasoning

            # Determine default agent/model from OpenCode config
            default_model_str = self._resolve_opencode_default_model(
                opencode_default_config, opencode_agents, current_oc_agent
            )

            # Build agent options
            agent_options = [
                {
                    "text": {"type": "plain_text", "text": "(Default)"},
                    "value": "__default__",
                }
            ]
            for agent in opencode_agents:
                agent_name = agent.get("name", "")
                if agent_name:
                    agent_options.append(
                        {
                            "text": {"type": "plain_text", "text": agent_name},
                            "value": agent_name,
                        }
                    )

            # Find initial agent
            initial_agent = agent_options[0]  # Default
            if current_oc_agent:
                for opt in agent_options:
                    if opt["value"] == current_oc_agent:
                        initial_agent = opt
                        break

            agent_select = {
                "type": "static_select",
                "action_id": "opencode_agent_select",
                "placeholder": {"type": "plain_text", "text": "Select OpenCode agent"},
                "options": agent_options,
                "initial_option": initial_agent,
            }

            # Build model options
            default_label = "(Default)"
            if default_model_str:
                default_label = f"(Default) - {default_model_str}"
            model_options = [
                {
                    "text": {"type": "plain_text", "text": default_label},
                    "value": "__default__",
                }
            ]

            # Add models from providers
            providers_data = opencode_models.get("providers", [])
            defaults = opencode_models.get("default", {})

            # Calculate max models per provider to fit within Slack's 100 option limit
            # Reserve 1 for "(Default)" option
            num_providers = len(providers_data)
            max_per_provider = (
                max(5, (99 // num_providers)) if num_providers > 0 else 99
            )

            def model_sort_key(model_item):
                """Sort models by release_date (newest first), deprioritize utility models."""
                model_id, model_info = model_item
                mid_lower = model_id.lower()

                # Deprioritize embedding and utility models (put them at the end)
                is_utility = any(
                    kw in mid_lower
                    for kw in [
                        "embedding",
                        "tts",
                        "whisper",
                        "ada",
                        "davinci",
                        "turbo-instruct",
                    ]
                )
                utility_penalty = 1 if is_utility else 0

                # Get release_date for sorting (newest first)
                # Default to old date if not available, convert to negative int for DESC sort
                release_date = "1970-01-01"
                if isinstance(model_info, dict):
                    release_date = (
                        model_info.get("release_date", "1970-01-01") or "1970-01-01"
                    )
                # Convert YYYY-MM-DD to int (e.g., 20250414) and negate for descending order
                try:
                    date_int = -int(release_date.replace("-", ""))
                except (ValueError, AttributeError):
                    date_int = 0

                # Sort by: utility_penalty ASC, release_date DESC (via negative int), model_id ASC
                return (utility_penalty, date_int, model_id)

            for provider in providers_data:
                provider_id = provider.get("id", "")
                provider_name = provider.get("name", provider_id)
                models = provider.get("models", {})

                # Handle both dict and list formats for models
                if isinstance(models, dict):
                    model_items = list(models.items())
                elif isinstance(models, list):
                    model_items = [
                        (m, m) if isinstance(m, str) else (m.get("id", ""), m)
                        for m in models
                    ]
                else:
                    model_items = []

                # Sort models by priority
                model_items.sort(key=model_sort_key)

                # Limit models per provider
                provider_model_count = 0
                for model_id, model_info in model_items:
                    if provider_model_count >= max_per_provider:
                        break

                    # Get model name
                    if isinstance(model_info, dict):
                        model_name = model_info.get("name", model_id)
                    else:
                        model_name = model_id

                    if model_id:
                        full_model = f"{provider_id}/{model_id}"
                        # Mark if this is the provider's default
                        is_default = defaults.get(provider_id) == model_id
                        display = f"{provider_name}: {model_name}"
                        if is_default:
                            display += " (default)"

                        model_options.append(
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": display[:75],
                                },  # Slack limit
                                "value": full_model,
                            }
                        )
                        provider_model_count += 1

            # Final safety check for Slack's 100 option limit
            if len(model_options) > 100:
                model_options = model_options[:100]
                logger.warning("Truncated model options to 100 for Slack modal")

            # Find initial model
            initial_model = model_options[0]  # Default
            if current_oc_model:
                for opt in model_options:
                    if opt["value"] == current_oc_model:
                        initial_model = opt
                        break

            model_select = {
                "type": "static_select",
                "action_id": "opencode_model_select",
                "placeholder": {"type": "plain_text", "text": "Select model"},
                "options": model_options,
                "initial_option": initial_model,
            }

            # Build reasoning effort options dynamically based on model variants
            target_model = current_oc_model or default_model_str
            model_variants: Dict[str, Any] = {}

            reasoning_model_key = target_model or "__default__"
            reasoning_action_id = (
                "opencode_reasoning_select__"
                + hashlib.sha1(reasoning_model_key.encode("utf-8")).hexdigest()[:8]
            )

            if target_model:
                # Parse provider/model format
                parts = target_model.split("/", 1)
                if len(parts) == 2:
                    target_provider, target_model_id = parts
                    # Search for this model in providers data
                    for provider in providers_data:
                        if provider.get("id") != target_provider:
                            continue

                        models = provider.get("models", {})
                        model_info: Optional[dict] = None

                        if isinstance(models, dict):
                            candidate = models.get(target_model_id)
                            if isinstance(candidate, dict):
                                model_info = candidate
                        elif isinstance(models, list):
                            for entry in models:
                                if (
                                    isinstance(entry, dict)
                                    and entry.get("id") == target_model_id
                                ):
                                    model_info = entry
                                    break

                        if isinstance(model_info, dict):
                            variants = model_info.get("variants", {})
                            if isinstance(variants, dict):
                                model_variants = variants

                        break

            # Build options from variants or use fallback
            reasoning_effort_options = [
                {
                    "text": {"type": "plain_text", "text": "(Default)"},
                    "value": "__default__",
                }
            ]

            if model_variants:
                # Use model-specific variants with stable ordering
                variant_order = [
                    "none",
                    "minimal",
                    "low",
                    "medium",
                    "high",
                    "xhigh",
                    "max",
                ]
                variant_display_names = {
                    "none": "None",
                    "minimal": "Minimal",
                    "low": "Low",
                    "medium": "Medium",
                    "high": "High",
                    "xhigh": "Extra High",
                    "max": "Max",
                }
                # Sort variants by predefined order, unknown variants go to end alphabetically
                sorted_variants = sorted(
                    model_variants.keys(),
                    key=lambda x: (
                        variant_order.index(x)
                        if x in variant_order
                        else len(variant_order),
                        x,
                    ),
                )
                for variant_key in sorted_variants:
                    display_name = variant_display_names.get(
                        variant_key, variant_key.capitalize()
                    )
                    reasoning_effort_options.append(
                        {
                            "text": {"type": "plain_text", "text": display_name},
                            "value": variant_key,
                        }
                    )
            else:
                # Fallback to common options
                reasoning_effort_options.extend(
                    [
                        {"text": {"type": "plain_text", "text": "Low"}, "value": "low"},
                        {
                            "text": {"type": "plain_text", "text": "Medium"},
                            "value": "medium",
                        },
                        {
                            "text": {"type": "plain_text", "text": "High"},
                            "value": "high",
                        },
                    ]
                )

            # Find initial reasoning effort
            initial_reasoning = reasoning_effort_options[0]  # Default
            if current_oc_reasoning:
                for opt in reasoning_effort_options:
                    if opt["value"] == current_oc_reasoning:
                        initial_reasoning = opt
                        break

            reasoning_select = {
                "type": "static_select",
                "action_id": reasoning_action_id,
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select reasoning effort",
                },
                "options": reasoning_effort_options,
                "initial_option": initial_reasoning,
            }

            # Add OpenCode section
            blocks.extend(
                [
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*OpenCode Options* (only applies when backend is OpenCode)",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "opencode_agent_block",
                        "optional": True,
                        "dispatch_action": True,
                        "element": agent_select,
                        "label": {"type": "plain_text", "text": "OpenCode Agent"},
                    },
                    {
                        "type": "input",
                        "block_id": "opencode_model_block",
                        "optional": True,
                        "dispatch_action": True,
                        "element": model_select,
                        "label": {"type": "plain_text", "text": "Model"},
                    },
                    {
                        "type": "input",
                        "block_id": "opencode_reasoning_block",
                        "optional": True,
                        "element": reasoning_select,
                        "label": {
                            "type": "plain_text",
                            "text": "Reasoning Effort (Thinking Mode)",
                        },
                    },
                ]
            )

            env_vars_str = ""
            if current_env_vars:
                env_vars_str = "\n".join(
                    f"{k}={v}" for k, v in current_env_vars.items()
                )

            blocks.extend(
                [
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Environment Variables* (for Vertex AI, etc.)",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "opencode_env_vars_block",
                        "optional": True,
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "opencode_env_vars_input",
                            "multiline": True,
                            "placeholder": {
                                "type": "plain_text",
                                "text": "KEY=value\nANOTHER_KEY=another_value",
                            },
                            "initial_value": env_vars_str,
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "Environment Variables (KEY=VALUE, one per line)",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "_⚠️ Changes require OpenCode restart to take effect._",
                            }
                        ],
                    },
                ]
            )

        if "claude" in registered_backends and selected_backend_value == "claude":
            claude_mode = None
            if current_claude_mode is not _UNSET:
                claude_mode = current_claude_mode
            elif current_routing and hasattr(current_routing, "claude_mode"):
                claude_mode = current_routing.claude_mode

            mode_options = [
                {
                    "text": {"type": "plain_text", "text": "(Default) - Normal"},
                    "value": "__default__",
                },
                {
                    "text": {"type": "plain_text", "text": "Plan Mode"},
                    "value": "plan",
                },
            ]

            initial_mode = mode_options[0]
            if claude_mode == "plan":
                initial_mode = mode_options[1]

            mode_select = {
                "type": "static_select",
                "action_id": "claude_mode_select",
                "placeholder": {"type": "plain_text", "text": "Select mode"},
                "options": mode_options,
                "initial_option": initial_mode,
            }

            claude_model_options = [
                {"text": {"type": "plain_text", "text": "Opus 4.5"}, "value": "opus"},
                {
                    "text": {"type": "plain_text", "text": "Sonnet 4.5"},
                    "value": "sonnet",
                },
                {
                    "text": {"type": "plain_text", "text": "Sonnet 4.5 (1M context)"},
                    "value": "sonnet-1m",
                },
                {"text": {"type": "plain_text", "text": "Haiku 4.5"}, "value": "haiku"},
            ]

            current_claude_model = None
            if current_routing and hasattr(current_routing, "claude_model"):
                current_claude_model = current_routing.claude_model

            initial_claude_model = claude_model_options[1]
            if current_claude_model:
                for opt in claude_model_options:
                    if opt["value"] == current_claude_model:
                        initial_claude_model = opt
                        break

            claude_model_select = {
                "type": "static_select",
                "action_id": "claude_model_select",
                "placeholder": {"type": "plain_text", "text": "Select model"},
                "options": claude_model_options,
                "initial_option": initial_claude_model,
            }

            claude_env_str = ""
            if current_claude_env_vars:
                claude_env_str = "\n".join(
                    f"{k}={v}" for k, v in current_claude_env_vars.items()
                )
            elif current_routing and hasattr(current_routing, "claude_env_vars"):
                env_vars = current_routing.claude_env_vars
                if env_vars:
                    claude_env_str = "\n".join(f"{k}={v}" for k, v in env_vars.items())

            blocks.extend(
                [
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Claude Code Options*",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "claude_model_block",
                        "optional": True,
                        "element": claude_model_select,
                        "label": {"type": "plain_text", "text": "Model"},
                    },
                    {
                        "type": "input",
                        "block_id": "claude_mode_block",
                        "optional": True,
                        "element": mode_select,
                        "label": {"type": "plain_text", "text": "Mode"},
                    },
                    {
                        "type": "input",
                        "block_id": "claude_env_vars_block",
                        "optional": True,
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "claude_env_vars_input",
                            "multiline": True,
                            "placeholder": {
                                "type": "plain_text",
                                "text": "KEY=value\nANOTHER_KEY=another_value",
                            },
                            "initial_value": claude_env_str,
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "Environment Variables (KEY=VALUE, one per line)",
                        },
                    },
                ]
            )

        return {
            "type": "modal",
            "callback_id": "routing_modal",
            "private_metadata": channel_id,
            "title": {"type": "plain_text", "text": "Agent Settings"},
            "submit": {"type": "plain_text", "text": "Save"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": blocks,
        }

    async def open_opencode_question_modal(
        self,
        trigger_id: str,
        context: MessageContext,
        pending: Dict[str, Any],
    ):
        self._ensure_clients()

        questions = pending.get("questions")
        questions = questions if isinstance(questions, list) else []
        if not questions:
            raise ValueError("No questions available")

        import json

        private_metadata = json.dumps(
            {
                "channel_id": context.channel_id,
                "thread_id": context.thread_id,
                "question_count": len(questions),
            }
        )

        blocks: list[Dict[str, Any]] = []
        for idx, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            header = (q.get("header") or f"Question {idx + 1}").strip()
            prompt = (q.get("question") or "").strip()
            multiple = bool(q.get("multiple"))
            options = q.get("options") if isinstance(q.get("options"), list) else []

            option_items = []
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                label = opt.get("label")
                if label is None:
                    continue
                desc = opt.get("description")
                item: Dict[str, Any] = {
                    "text": {
                        "type": "plain_text",
                        "text": str(label)[:75],
                        "emoji": True,
                    },
                    "value": str(label),
                }
                if desc:
                    item["description"] = {
                        "type": "plain_text",
                        "text": str(desc)[:75],
                        "emoji": True,
                    }
                option_items.append(item)

            element: Dict[str, Any]
            if multiple:
                element = {
                    "type": "multi_static_select",
                    "action_id": "select",
                    "options": option_items,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select one or more",
                        "emoji": True,
                    },
                }
            else:
                element = {
                    "type": "static_select",
                    "action_id": "select",
                    "options": option_items,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select one",
                        "emoji": True,
                    },
                }

            label_text = header
            if prompt:
                label_text = f"{header}: {prompt}"[:150]

            blocks.append(
                {
                    "type": "input",
                    "block_id": f"q{idx}",
                    "label": {
                        "type": "plain_text",
                        "text": label_text,
                        "emoji": True,
                    },
                    "element": element,
                }
            )

        view = {
            "type": "modal",
            "callback_id": "opencode_question_modal",
            "private_metadata": private_metadata,
            "title": {"type": "plain_text", "text": "OpenCode", "emoji": True},
            "submit": {"type": "plain_text", "text": "Submit", "emoji": True},
            "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
            "blocks": blocks,
        }

        await self.web_client.views_open(trigger_id=trigger_id, view=view)

    async def open_routing_modal(
        self,
        trigger_id: str,
        channel_id: str,
        registered_backends: list,
        current_backend: str,
        current_routing,
        opencode_agents: list,
        opencode_models: dict,
        opencode_default_config: dict,
        current_require_mention: object = None,
        global_require_mention: bool = False,
        current_env_vars: Optional[Dict[str, str]] = None,
        current_claude_env_vars: Optional[Dict[str, str]] = None,
    ):
        self._ensure_clients()

        view = self._build_routing_modal_view(
            channel_id=channel_id,
            registered_backends=registered_backends,
            current_backend=current_backend,
            current_routing=current_routing,
            opencode_agents=opencode_agents,
            opencode_models=opencode_models,
            opencode_default_config=opencode_default_config,
            current_require_mention=current_require_mention,
            global_require_mention=global_require_mention,
            current_env_vars=current_env_vars,
            current_claude_env_vars=current_claude_env_vars,
        )

        try:
            await self.web_client.views_open(trigger_id=trigger_id, view=view)
        except SlackApiError as e:
            logger.error(f"Error opening routing modal: {e}")
            raise

    async def update_routing_modal(
        self,
        view_id: str,
        view_hash: str,
        channel_id: str,
        registered_backends: list,
        current_backend: str,
        current_routing,
        opencode_agents: list,
        opencode_models: dict,
        opencode_default_config: dict,
        selected_backend: Optional[str] = None,
        selected_opencode_agent: Optional[str] = None,
        selected_opencode_model: Optional[str] = None,
        selected_opencode_reasoning: Optional[str] = None,
        current_require_mention: object = None,
        global_require_mention: bool = False,
        current_env_vars: Optional[Dict[str, str]] = None,
        current_claude_env_vars: Optional[Dict[str, str]] = None,
    ) -> None:
        self._ensure_clients()

        view = self._build_routing_modal_view(
            channel_id=channel_id,
            registered_backends=registered_backends,
            current_backend=current_backend,
            current_routing=current_routing,
            opencode_agents=opencode_agents,
            opencode_models=opencode_models,
            opencode_default_config=opencode_default_config,
            selected_backend=selected_backend,
            selected_opencode_agent=selected_opencode_agent,
            selected_opencode_model=selected_opencode_model,
            selected_opencode_reasoning=selected_opencode_reasoning,
            current_require_mention=current_require_mention,
            global_require_mention=global_require_mention,
            current_env_vars=current_env_vars,
            current_claude_env_vars=current_claude_env_vars,
        )

        try:
            await self.web_client.views_update(
                view_id=view_id, hash=view_hash, view=view
            )
        except SlackApiError as e:
            logger.error(f"Error updating routing modal: {e}")
            raise

    def register_callbacks(
        self,
        on_message: Optional[Callable] = None,
        on_command: Optional[Dict[str, Callable]] = None,
        on_callback_query: Optional[Callable] = None,
        **kwargs,
    ):
        """Register callback functions for different events"""
        super().register_callbacks(on_message, on_command, on_callback_query, **kwargs)

        # Register command handlers
        if on_command:
            self.command_handlers.update(on_command)

        # Register settings update handler
        if "on_settings_update" in kwargs:
            self._on_settings_update = kwargs["on_settings_update"]

        # Register change CWD handler
        if "on_change_cwd" in kwargs:
            self._on_change_cwd = kwargs["on_change_cwd"]

        # Register routing update handler
        if "on_routing_update" in kwargs:
            self._on_routing_update = kwargs["on_routing_update"]

        # Register routing modal update handler
        if "on_routing_modal_update" in kwargs:
            self._on_routing_modal_update = kwargs["on_routing_modal_update"]

        # Register on_ready handler (called when connected)
        if "on_ready" in kwargs:
            self._on_ready = kwargs["on_ready"]

        if "on_app_home_opened" in kwargs:
            self._on_app_home_opened = kwargs["on_app_home_opened"]

        if "on_home_setting_change" in kwargs:
            self._on_home_setting_change = kwargs["on_home_setting_change"]

        if "on_home_edit_env" in kwargs:
            self._on_home_edit_env = kwargs["on_home_edit_env"]

        if "on_home_env_save" in kwargs:
            self._on_home_env_save = kwargs["on_home_env_save"]

        if "on_home_channel_select" in kwargs:
            self._on_home_channel_select = kwargs["on_home_channel_select"]

    async def get_or_create_thread(
        self, channel_id: str, user_id: str
    ) -> Optional[str]:
        """Get existing thread timestamp or return None for new thread"""
        # Deprecated: Thread handling now uses user's message timestamp directly
        return None

    async def _is_authorized_channel(self, channel_id: str) -> bool:
        """Check if a channel is authorized based on whitelist configuration"""
        if not self.settings_manager:
            return True

        settings = self.settings_manager.get_channel_settings(channel_id)
        if settings is None:
            return True

        if settings.enabled:
            return True

        logger.info("Channel explicitly disabled: %s", channel_id)
        return False

    async def _send_unauthorized_message(self, channel_id: str):
        """Send unauthorized access message to channel"""
        try:
            self._ensure_clients()
            await self.web_client.chat_postMessage(
                channel=channel_id,
                text="❌ This channel is disabled.",
            )
        except Exception as e:
            logger.error(f"Failed to send unauthorized message to {channel_id}: {e}")

    def _build_app_home_view(
        self,
        user_id: str,
        registered_backends: list,
        current_backend: str,
        opencode_agents: list,
        opencode_models: dict,
        opencode_default_config: dict,
        current_routing,
        global_require_mention: bool = False,
        current_env_vars: Optional[Dict[str, str]] = None,
        current_claude_env_vars: Optional[Dict[str, str]] = None,
        status_info: Optional[Dict[str, Any]] = None,
        channels: Optional[List[Dict[str, Any]]] = None,
        selected_channel_id: Optional[str] = None,
    ) -> dict:
        backend_display_names = {
            "claude": "Claude Code",
            "codex": "Codex",
            "opencode": "OpenCode",
        }

        current_backend_display = backend_display_names.get(
            current_backend, current_backend
        )

        selected_channel_name = None
        if channels and selected_channel_id:
            for ch in channels:
                if ch["id"] == selected_channel_id:
                    prefix = "🔒 " if ch.get("is_private") else "#"
                    selected_channel_name = f"{prefix}{ch['name']}"
                    break

        blocks: list[Dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🤖 Slack Coder", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Status:* 🟢 Running",
                },
            },
            {"type": "divider"},
        ]

        if channels:
            channel_options = []
            initial_channel = None
            for ch in channels:
                prefix = "🔒 " if ch.get("is_private") else "#"
                option = {
                    "text": {
                        "type": "plain_text",
                        "text": f"{prefix}{ch['name']}"[:75],
                    },
                    "value": ch["id"],
                }
                channel_options.append(option)
                if ch["id"] == selected_channel_id:
                    initial_channel = option

            if not initial_channel and channel_options:
                initial_channel = channel_options[0]

            blocks.append(
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "📺 Channel Settings",
                        "emoji": True,
                    },
                }
            )
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*Select Channel*"},
                    "accessory": {
                        "type": "static_select",
                        "action_id": "home_channel_select",
                        "options": channel_options[:100],
                        "initial_option": initial_channel,
                    },
                }
            )
            if selected_channel_name:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Configuring: *{selected_channel_name}* | Backend: *{current_backend_display}*",
                            }
                        ],
                    }
                )
            blocks.append({"type": "divider"})

        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "⚙️ Agent Settings",
                    "emoji": True,
                },
            }
        )

        backend_options = []
        for backend in registered_backends:
            display_name = backend_display_names.get(backend, backend.capitalize())
            backend_options.append(
                {
                    "text": {"type": "plain_text", "text": display_name},
                    "value": backend,
                }
            )

        initial_backend = backend_options[0] if backend_options else None
        for opt in backend_options:
            if opt["value"] == current_backend:
                initial_backend = opt
                break

        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Backend*"},
                "accessory": {
                    "type": "static_select",
                    "action_id": "home_backend_select",
                    "options": backend_options,
                    "initial_option": initial_backend,
                },
            }
        )

        if current_backend == "opencode" and "opencode" in registered_backends:
            current_oc_agent = (
                current_routing.opencode_agent if current_routing else None
            )
            current_oc_model = (
                current_routing.opencode_model if current_routing else None
            )
            current_oc_reasoning = (
                current_routing.opencode_reasoning_effort if current_routing else None
            )

            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*OpenCode Options*"},
                }
            )

            agent_options = [
                {
                    "text": {"type": "plain_text", "text": "(Default)"},
                    "value": "__default__",
                }
            ]
            for agent in opencode_agents:
                agent_name = agent.get("name", "")
                if agent_name:
                    agent_options.append(
                        {
                            "text": {"type": "plain_text", "text": agent_name},
                            "value": agent_name,
                        }
                    )

            initial_agent = agent_options[0]
            if current_oc_agent:
                for opt in agent_options:
                    if opt["value"] == current_oc_agent:
                        initial_agent = opt
                        break

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Agent"},
                    "accessory": {
                        "type": "static_select",
                        "action_id": "home_opencode_agent_select",
                        "options": agent_options,
                        "initial_option": initial_agent,
                    },
                }
            )

            model_options = [
                {
                    "text": {"type": "plain_text", "text": "(Default)"},
                    "value": "__default__",
                }
            ]
            providers_data = opencode_models.get("providers", [])
            defaults = opencode_models.get("default", {})
            for provider in providers_data:
                provider_id = provider.get("id", "")
                provider_name = provider.get("name", provider_id)
                models = provider.get("models", {})
                if isinstance(models, dict):
                    for model_id, model_info in list(models.items())[:5]:
                        if model_id:
                            full_model = f"{provider_id}/{model_id}"
                            model_name = (
                                model_info.get("name", model_id)
                                if isinstance(model_info, dict)
                                else model_id
                            )
                            model_options.append(
                                {
                                    "text": {
                                        "type": "plain_text",
                                        "text": f"{provider_name}: {model_name}"[:75],
                                    },
                                    "value": full_model,
                                }
                            )

            if len(model_options) > 100:
                model_options = model_options[:100]

            initial_model = model_options[0]
            if current_oc_model:
                for opt in model_options:
                    if opt["value"] == current_oc_model:
                        initial_model = opt
                        break

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Model"},
                    "accessory": {
                        "type": "static_select",
                        "action_id": "home_opencode_model_select",
                        "options": model_options,
                        "initial_option": initial_model,
                    },
                }
            )

            reasoning_options = [
                {
                    "text": {"type": "plain_text", "text": "(Default)"},
                    "value": "__default__",
                },
                {"text": {"type": "plain_text", "text": "Low"}, "value": "low"},
                {"text": {"type": "plain_text", "text": "Medium"}, "value": "medium"},
                {"text": {"type": "plain_text", "text": "High"}, "value": "high"},
            ]

            initial_reasoning = reasoning_options[0]
            if current_oc_reasoning:
                for opt in reasoning_options:
                    if opt["value"] == current_oc_reasoning:
                        initial_reasoning = opt
                        break

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Reasoning Effort"},
                    "accessory": {
                        "type": "static_select",
                        "action_id": "home_opencode_reasoning_select",
                        "options": reasoning_options,
                        "initial_option": initial_reasoning,
                    },
                }
            )

            env_vars_str = ""
            if current_env_vars:
                env_vars_str = ", ".join(f"{k}" for k in current_env_vars.keys())
            env_display = env_vars_str if env_vars_str else "None configured"

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Environment Variables:* {env_display}",
                    },
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit", "emoji": True},
                        "action_id": "home_edit_opencode_env",
                    },
                }
            )

        elif current_backend == "claude" and "claude" in registered_backends:
            current_claude_mode = (
                current_routing.claude_mode if current_routing else None
            )
            current_claude_model = (
                current_routing.claude_model if current_routing else None
            )
            claude_env = current_routing.claude_env_vars if current_routing else None

            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*Claude Code Options*"},
                }
            )

            model_options = [
                {"text": {"type": "plain_text", "text": "Opus 4.5"}, "value": "opus"},
                {
                    "text": {"type": "plain_text", "text": "Sonnet 4.5"},
                    "value": "sonnet",
                },
                {
                    "text": {"type": "plain_text", "text": "Sonnet 4.5 (1M context)"},
                    "value": "sonnet-1m",
                },
                {"text": {"type": "plain_text", "text": "Haiku 4.5"}, "value": "haiku"},
            ]

            initial_model = model_options[1]
            if current_claude_model:
                for opt in model_options:
                    if opt["value"] == current_claude_model:
                        initial_model = opt
                        break

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Model"},
                    "accessory": {
                        "type": "static_select",
                        "action_id": "home_claude_model_select",
                        "options": model_options,
                        "initial_option": initial_model,
                    },
                }
            )

            mode_options = [
                {
                    "text": {"type": "plain_text", "text": "(Default) - Normal"},
                    "value": "__default__",
                },
                {"text": {"type": "plain_text", "text": "Plan Mode"}, "value": "plan"},
            ]

            initial_mode = mode_options[0]
            if current_claude_mode == "plan":
                initial_mode = mode_options[1]

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Mode"},
                    "accessory": {
                        "type": "static_select",
                        "action_id": "home_claude_mode_select",
                        "options": mode_options,
                        "initial_option": initial_mode,
                    },
                }
            )

            env_vars_str = ""
            if claude_env:
                env_vars_str = ", ".join(f"{k}" for k in claude_env.keys())
            env_display = env_vars_str if env_vars_str else "None configured"

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Environment Variables:* {env_display}",
                    },
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit", "emoji": True},
                        "action_id": "home_edit_claude_env",
                    },
                }
            )

        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "💡 Changes are saved automatically when you select an option.",
                    }
                ],
            }
        )

        return {"type": "home", "blocks": blocks}

    async def publish_app_home(
        self,
        user_id: str,
        registered_backends: list,
        current_backend: str,
        opencode_agents: list,
        opencode_models: dict,
        opencode_default_config: dict,
        current_routing,
        global_require_mention: bool = False,
        current_env_vars: Optional[Dict[str, str]] = None,
        current_claude_env_vars: Optional[Dict[str, str]] = None,
        status_info: Optional[Dict[str, Any]] = None,
        channels: Optional[List[Dict[str, Any]]] = None,
        selected_channel_id: Optional[str] = None,
    ):
        self._ensure_clients()

        view = self._build_app_home_view(
            user_id=user_id,
            registered_backends=registered_backends,
            current_backend=current_backend,
            opencode_agents=opencode_agents,
            opencode_models=opencode_models,
            opencode_default_config=opencode_default_config,
            current_routing=current_routing,
            global_require_mention=global_require_mention,
            current_env_vars=current_env_vars,
            current_claude_env_vars=current_claude_env_vars,
            status_info=status_info,
            channels=channels,
            selected_channel_id=selected_channel_id,
        )

        try:
            await self.web_client.views_publish(user_id=user_id, view=view)
            logger.info(f"Published App Home for user {user_id}")
        except SlackApiError as e:
            logger.error(f"Error publishing App Home: {e}")

    async def open_env_vars_modal(
        self,
        trigger_id: str,
        user_id: str,
        env_type: str,
        current_env_vars: Optional[Dict[str, str]] = None,
    ):
        self._ensure_clients()

        env_vars_str = ""
        if current_env_vars:
            env_vars_str = "\n".join(f"{k}={v}" for k, v in current_env_vars.items())

        title = "OpenCode Env Vars" if env_type == "opencode" else "Claude Env Vars"
        callback_id = f"home_env_modal_{env_type}"

        view = {
            "type": "modal",
            "callback_id": callback_id,
            "private_metadata": user_id,
            "title": {"type": "plain_text", "text": title[:24]},
            "submit": {"type": "plain_text", "text": "Save"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "env_vars_block",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "env_vars_input",
                        "multiline": True,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "KEY=value\nANOTHER_KEY=another_value",
                        },
                        "initial_value": env_vars_str,
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "Environment Variables (KEY=VALUE, one per line)",
                    },
                    "optional": True,
                },
            ],
        }

        try:
            await self.web_client.views_open(trigger_id=trigger_id, view=view)
        except SlackApiError as e:
            logger.error(f"Error opening env vars modal: {e}")
