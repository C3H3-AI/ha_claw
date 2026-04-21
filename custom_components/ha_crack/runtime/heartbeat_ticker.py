from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .heartbeat_store import get_due_tasks, async_record_heartbeat_result

LOGGER = logging.getLogger(__name__)
_TICK_INTERVAL = timedelta(seconds=60)
_UNSUB_KEY = "heartbeat_ticker_unsub"


async def _tick(hass: HomeAssistant, _now: Any = None) -> None:
    due_tasks = await hass.async_add_executor_job(get_due_tasks)
    if not due_tasks:
        return

    for task in due_tasks:
        LOGGER.info("Heartbeat due: %s — %s", task.slug, task.objective)
        try:
            from homeassistant.components.conversation import async_converse

            result = await async_converse(
                hass,
                text=f"[heartbeat:{task.slug}] {task.objective}",
                conversation_id=f"heartbeat_{task.slug}",
                context=hass.data.get("kadermanager_context"),
            )
            status = "success" if result.response.speech else "executed"
            await async_record_heartbeat_result(
                hass, slug=task.slug, status=status, note="auto-tick"
            )
        except Exception:
            LOGGER.exception("Heartbeat tick failed for %s", task.slug)
            await async_record_heartbeat_result(
                hass, slug=task.slug, status="error", note="auto-tick failed"
            )


@callback
def async_setup_heartbeat_ticker(hass: HomeAssistant) -> None:
    @callback
    def _schedule_tick(now: Any) -> None:
        hass.async_create_task(_tick(hass, now), "heartbeat_tick")

    unsub = async_track_time_interval(hass, _schedule_tick, _TICK_INTERVAL)
    hass.data[_UNSUB_KEY] = unsub


@callback
def async_unload_heartbeat_ticker(hass: HomeAssistant) -> None:
    unsub = hass.data.pop(_UNSUB_KEY, None)
    if unsub:
        unsub()
