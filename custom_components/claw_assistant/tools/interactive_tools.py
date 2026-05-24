"""Interactive tools for user confirmation, selection, and input.

These tools allow Claw to ask users for confirmation, present choices,
or request input in IM channels (Feishu, WeChat, etc.).

The output uses interactive markup syntax that cn_im_hub parses and
renders as platform-specific interactive elements.

See: D:\ai-hub\memory\shared\interactive_markup_spec.md
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

_LOGGER = logging.getLogger(__name__)


class AskUserConfirmTool(llm.Tool):
    """Ask user for confirmation (Yes/No).

    Use this when you need explicit user confirmation before taking action,
    especially for destructive operations or important decisions.

    The tool returns interactive markup that cn_im_hub renders as
    confirmation buttons in IM channels.
    """

    name = "AskUserConfirm"
    description = (
        "Ask user for confirmation before taking action. "
        "Use for destructive operations or important decisions. "
        "Params: message (confirmation question), id (unique identifier). "
        "Returns interactive markup with confirm/cancel buttons."
    )

    parameters = vol.Schema({
        vol.Required("message"): str,
        vol.Required("id"): str,
    })

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_call: llm.ToolCall,
    ) -> JsonObjectType:
        """Generate interactive markup for confirmation."""
        message = tool_call.parameters["message"]
        confirm_id = tool_call.parameters["id"]

        # Generate interactive markup
        markup = (
            f"[INTERACTIVE type=\"confirm\" id=\"{confirm_id}\" message=\"{message}\"]"
            f"[/INTERACTIVE]"
        )

        return {
            "speech": markup,
            "requires_user_response": True,
            "interactive_type": "confirm",
            "interactive_id": confirm_id,
        }


class AskUserSelectTool(llm.Tool):
    """Ask user to select from multiple options.

    Use this when there are multiple valid choices and you want
    the user to pick one.

    The tool returns interactive markup that cn_im_hub renders as
    option buttons in IM channels.
    """

    name = "AskUserSelect"
    description = (
        "Ask user to select from multiple options. "
        "Use when there are multiple valid choices. "
        "Params: message (question/prompt), id (unique identifier), "
        "options (list of {id, label, style?}). "
        "Returns interactive markup with option buttons."
    )

    parameters = vol.Schema({
        vol.Required("message"): str,
        vol.Required("id"): str,
        vol.Required("options"): [{
            vol.Required("id"): str,
            vol.Required("label"): str,
            vol.Optional("style", default="default"): vol.In(["default", "primary"]),
        }],
    })

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_call: llm.ToolCall,
    ) -> JsonObjectType:
        """Generate interactive markup for selection."""
        message = tool_call.parameters["message"]
        select_id = tool_call.parameters["id"]
        options = tool_call.parameters["options"]

        # Build options markup
        options_markup = "\n".join(
            f'[OPTION id="{opt["id"]}" label="{opt["label"]}" style="{opt.get("style", "default")}"]'
            for opt in options
        )

        markup = (
            f"[INTERACTIVE type=\"select\" id=\"{select_id}\" message=\"{message}\"]\n"
            f"{options_markup}\n"
            f"[/INTERACTIVE]"
        )

        return {
            "speech": markup,
            "requires_user_response": True,
            "interactive_type": "select",
            "interactive_id": select_id,
            "options": [opt["id"] for opt in options],
        }


class AskUserInputTool(llm.Tool):
    """Ask user for text/number input.

    Use this when you need specific information from the user
    that can't be provided via buttons.

    The tool returns interactive markup that cn_im_hub renders as
    an input prompt in IM channels.
    """

    name = "AskUserInput"
    description = (
        "Ask user for text or number input. "
        "Use when you need specific information from the user. "
        "Params: message (prompt), id (unique identifier), "
        "hint (optional input hint), unit (optional unit like °C). "
        "Returns interactive markup with input prompt."
    )

    parameters = vol.Schema({
        vol.Required("message"): str,
        vol.Required("id"): str,
        vol.Optional("hint"): str,
        vol.Optional("unit"): str,
    })

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_call: llm.ToolCall,
    ) -> JsonObjectType:
        """Generate interactive markup for input."""
        message = tool_call.parameters["message"]
        input_id = tool_call.parameters["id"]
        hint = tool_call.parameters.get("hint", "")
        unit = tool_call.parameters.get("unit", "")

        # Build attributes
        attrs = f' message="{message}"'
        if hint:
            attrs += f' hint="{hint}"'
        if unit:
            attrs += f' unit="{unit}"'

        markup = f"[INTERACTIVE type=\"input\" id=\"{input_id}\"{attrs}][/INTERACTIVE]"

        return {
            "speech": markup,
            "requires_user_response": True,
            "interactive_type": "input",
            "interactive_id": input_id,
        }


class MultiStepWizardTool(llm.Tool):
    """Multi-step wizard for complex workflows.

    Use this for multi-step setup or configuration workflows.

    The tool returns interactive markup showing progress and options.
    """

    name = "MultiStepWizard"
    description = (
        "Present a multi-step wizard for complex workflows. "
        "Use for multi-step setup or configuration. "
        "Params: message (step prompt), id (unique identifier), "
        "step (current step number), total (total steps), "
        "options (list of {id, label}). "
        "Returns interactive markup with progress and options."
    )

    parameters = vol.Schema({
        vol.Required("message"): str,
        vol.Required("id"): str,
        vol.Required("step"): vol.All(int, vol.Range(min=1)),
        vol.Required("total"): vol.All(int, vol.Range(min=1)),
        vol.Required("options"): [{
            vol.Required("id"): str,
            vol.Required("label"): str,
        }],
    })

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_call: llm.ToolCall,
    ) -> JsonObjectType:
        """Generate interactive markup for multi-step wizard."""
        message = tool_call.parameters["message"]
        wizard_id = tool_call.parameters["id"]
        step = tool_call.parameters["step"]
        total = tool_call.parameters["total"]
        options = tool_call.parameters["options"]

        # Build options markup
        options_markup = "\n".join(
            f'[OPTION id="{opt["id"]}" label="{opt["label"]}"]'
            for opt in options
        )

        markup = (
            f"[INTERACTIVE type=\"multi_step\" id=\"{wizard_id}\" "
            f"step=\"{step}\" total=\"{total}\" message=\"{message}\"]\n"
            f"{options_markup}\n"
            f"[/INTERACTIVE]"
        )

        return {
            "speech": markup,
            "requires_user_response": True,
            "interactive_type": "multi_step",
            "interactive_id": wizard_id,
            "step": step,
            "total": total,
        }
