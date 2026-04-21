

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .events import EVENT_AI_RESPONSE
from .state import get_conversation_status

LOGGER = logging.getLogger(__name__)


def setup_ai_coordinator(hass: HomeAssistant, entry: ConfigEntry) -> None:

    if get_conversation_status(hass).get("coordinator_installed"):
        return

    async def handle_ai_response(event):
        LOGGER.debug(
            "AI coordinator received a response event; forced internal termination checks stay disabled: %s",
            event.data.get("conversation_id"),
        )

    hass.bus.async_listen(EVENT_AI_RESPONSE, handle_ai_response)
    get_conversation_status(hass)["coordinator_installed"] = True
    LOGGER.debug("AI coordinator installed: internal forced-termination logic is disabled")
