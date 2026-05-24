"""Thinking status update tools for real-time feedback.

These tools allow Claw to report its thinking status in real-time,
which is displayed in Feishu as a streaming card.

Usage:
    1. Start thinking: UpdateThinkingStatus.start()
    2. Update status: UpdateThinkingStatus.update(status="正在搜索...")
    3. Finish: UpdateThinkingStatus.finish()
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

_LOGGER = logging.getLogger(__name__)


class UpdateThinkingStatusTool(llm.Tool):
    """Update real-time thinking status for display in IM channels.

    Use this tool to show users what Claw is currently doing,
    especially during long operations like searching or processing.

    The status is displayed as a streaming card in Feishu with
    real-time updates and elapsed time.

    Available actions:
    - start: Begin a new thinking session
    - update: Update current status
    - finish: Complete the thinking session
    """

    name = "UpdateThinkingStatus"
    description = (
        "Update real-time thinking status for display in IM channels. "
        "Use this to show users what you're currently doing during long operations. "
        "Actions: start (begin session), update (change status), finish (complete). "
        "Status examples: '🧠 正在分析...', '🔍 正在搜索...', '🛠️ 正在调用工具...'"
    )

    parameters = vol.Schema({
        vol.Required("action"): vol.In(["start", "update", "finish"]),
        vol.Optional("status"): str,
        vol.Optional("details"): str,
        vol.Optional("icon"): str,
    })

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_call: llm.ToolCall,
    ) -> JsonObjectType:
        """Handle thinking status update."""
        action = tool_call.parameters["action"]
        status = tool_call.parameters.get("status", "")
        details = tool_call.parameters.get("details", "")
        icon = tool_call.parameters.get("icon", "🤔")

        # Build status message with icon
        if status and not status.startswith(("🧠", "🔍", "🛠️", "⚙️", "💭", "✍️", "✓", "✅", "🤔")):
            status = f"{icon} {status}"

        # Generate thinking markup for cn_im_hub to parse
        if action == "start":
            markup = f"[THINKING action=\"start\"]{status}[/THINKING]"
            return {
                "speech": markup,
                "thinking_action": "start",
                "status": status,
            }

        elif action == "update":
            markup = f"[THINKING action=\"update\" status=\"{status}\"]{details}[/THINKING]"
            return {
                "speech": markup,
                "thinking_action": "update",
                "status": status,
                "details": details,
            }

        elif action == "finish":
            markup = f"[THINKING action=\"finish\"]{status or '思考完成'}[/THINKING]"
            return {
                "speech": markup,
                "thinking_action": "finish",
                "status": status or "✅ 思考完成",
            }

        return {"speech": "", "error": "Unknown action"}


class StartThinkingTool(llm.Tool):
    """Quick start a thinking session.

    Convenience tool to start thinking with a single call.
    Equivalent to UpdateThinkingStatus with action=start.
    """

    name = "StartThinking"
    description = (
        "Start a thinking session to show real-time progress. "
        "Use at the beginning of complex operations. "
        "Params: status (initial status message), icon (optional emoji)."
    )

    parameters = vol.Schema({
        vol.Optional("status", default="🤔 正在思考..."): str,
        vol.Optional("icon", default="🤔"): str,
    })

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_call: llm.ToolCall,
    ) -> JsonObjectType:
        """Start thinking session."""
        status = tool_call.parameters["status"]
        icon = tool_call.parameters["icon"]

        if not status.startswith(("🧠", "🔍", "🛠️", "⚙️", "💭", "✍️", "✓", "✅", "🤔")):
            status = f"{icon} {status}"

        markup = f"[THINKING action=\"start\"]{status}[/THINKING]"

        return {
            "speech": markup,
            "thinking_action": "start",
            "status": status,
        }


class FinishThinkingTool(llm.Tool):
    """Quick finish a thinking session.

    Convenience tool to finish thinking with a single call.
    Equivalent to UpdateThinkingStatus with action=finish.
    """

    name = "FinishThinking"
    description = (
        "Finish a thinking session. "
        "Use when your thinking process is complete. "
        "Params: status (final status, optional)."
    )

    parameters = vol.Schema({
        vol.Optional("status", default="✅ 思考完成"): str,
    })

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_call: llm.ToolCall,
    ) -> JsonObjectType:
        """Finish thinking session."""
        status = tool_call.parameters["status"]

        markup = f"[THINKING action=\"finish\"]{status}[/THINKING]"

        return {
            "speech": markup,
            "thinking_action": "finish",
            "status": status,
        }
