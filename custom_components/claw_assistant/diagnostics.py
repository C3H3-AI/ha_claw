from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

REDACT_KEYS = {"api_key", "token", "secret", "password", "key", "access_token", "refresh_token"}


def _redact_sensitive(data: dict) -> dict:
    result = {}
    for k, v in data.items():
        if any(sensitive in k.lower() for sensitive in REDACT_KEYS):
            result[k] = "**REDACTED**"
        elif isinstance(v, dict):
            result[k] = _redact_sensitive(v)
        else:
            result[k] = v
    return result


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    from .runtime.core.state import get_conversation_status, get_active_conversation_state
    from .runtime.agent.loop_controller import get_loop_status
    from .runtime.history.continuous_conversation import continuous_conversation_enabled
    from .runtime.hooks.official_websocket_hook import (
        context_status_bar_enabled,
        file_upload_enabled,
        sidebar_dock_enabled,
        sound_notifications_enabled,
        activity_tracking_enabled,
        tool_details_enabled,
        tool_progress_enabled,
    )

    entity_registry = er.async_get(hass)
    entities = [
        {
            "entity_id": e.entity_id,
            "platform": e.platform,
            "disabled": e.disabled,
        }
        for e in entity_registry.entities.values()
        if e.platform == DOMAIN
    ]

    conversation_agents = []
    try:
        from homeassistant.components.conversation import async_get_agent_info
        agents = await async_get_agent_info(hass)
        conversation_agents = [
            {"id": a.id, "name": a.name}
            for a in agents
        ]
    except Exception as e:
        conversation_agents = [{"error": str(e)}]

    runtime_state = {}
    try:
        runtime_state = {
            "conversation_status": get_conversation_status(hass),
            "loop_status": get_loop_status(hass),
            "active_conversation": get_active_conversation_state(hass),
        }
    except Exception as e:
        runtime_state = {"error": str(e)}

    installed_skills = []
    try:
        from .tools.misc_tools import list_installed_skills
        installed_skills = list_installed_skills(hass)
    except Exception as e:
        installed_skills = [{"error": str(e)}]

    tool_activities = []
    try:
        from .runtime.core.state import _domain_data
        dd = _domain_data(hass)
        tool_activities = dd.get("tool_activities", [])[-10:]
    except Exception:
        pass

    return {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "version": entry.version,
            "options": _redact_sensitive(dict(entry.options)),
        },
        "settings": {
            "continuous_conversation": continuous_conversation_enabled(hass),
            "context_status_bar": context_status_bar_enabled(hass),
            "file_upload": file_upload_enabled(hass),
            "sidebar_dock": sidebar_dock_enabled(hass),
            "sound_notifications": sound_notifications_enabled(hass),
            "activity_tracking": activity_tracking_enabled(hass),
            "tool_details": tool_details_enabled(hass),
            "tool_progress": tool_progress_enabled(hass),
        },
        "entities": entities,
        "conversation_agents": conversation_agents,
        "runtime_state": _redact_sensitive(runtime_state) if isinstance(runtime_state, dict) else runtime_state,
        "installed_skills_count": len(installed_skills) if isinstance(installed_skills, list) else 0,
        "recent_tool_activities": len(tool_activities),
        "ha_version": getattr(hass.config, "version", None) or __import__("homeassistant.const", fromlist=["__version__"]).__version__,
        "language": hass.config.language,
        "time_zone": str(hass.config.time_zone),
    }
