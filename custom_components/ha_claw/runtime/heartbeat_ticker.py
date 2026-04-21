from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .heartbeat_store import get_due_tasks, async_record_heartbeat_result, HeartbeatTask

LOGGER = logging.getLogger(__name__)
_TICK_INTERVAL = timedelta(seconds=10)
_UNSUB_KEY = "heartbeat_ticker_unsub"

_HEARTBEAT_SYSTEM_PROMPT = (
    "You are a background automation agent. "
    "Execute the task silently and efficiently. "
    "Do not ask questions. Do not output markdown. "
    "Use available tools to complete the objective. "
    "Reply with a brief status only."
)


def _build_heartbeat_text(task: HeartbeatTask) -> str:
    parts = [f"[heartbeat:{task.slug}]"]
    if task.objective:
        parts.append(task.objective)
    if task.steps:
        parts.append(f"Steps: {task.steps}")
    return " ".join(parts)


async def _tick(hass: HomeAssistant, _now: Any = None) -> None:
    due_tasks = await hass.async_add_executor_job(get_due_tasks)
    if not due_tasks:
        return

    from .state import get_runtime_store

    runtime_store = get_runtime_store(hass)
    original_async_converse = runtime_store.get("original_async_converse")
    if not original_async_converse:
        LOGGER.warning("Heartbeat ticker: runtime hook not ready")
        return

    entry = runtime_store.get("config_entry")
    if not entry:
        LOGGER.warning("Heartbeat ticker: config entry not found")
        return

    for task in due_tasks:
        LOGGER.info("Heartbeat due: %s — %s", task.slug, task.objective)
        try:
            text = _build_heartbeat_text(task)
            result = await original_async_converse(
                hass,
                text,
                f"heartbeat_{task.slug}",
                hass.data.get("kadermanager_context"),
                None,
                None,
                None,
                None,
                _HEARTBEAT_SYSTEM_PROMPT,
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
    if _UNSUB_KEY in hass.data:
        return

    @callback
    def _schedule_tick(now: Any) -> None:
        hass.async_create_task(_tick(hass, now), "heartbeat_tick")

    unsub = async_track_time_interval(hass, _schedule_tick, _TICK_INTERVAL)
    hass.data[_UNSUB_KEY] = unsub
    hass.async_create_task(_tick(hass), "heartbeat_tick_initial")


@callback
def async_unload_heartbeat_ticker(hass: HomeAssistant) -> None:
    unsub = hass.data.pop(_UNSUB_KEY, None)
    if unsub:
        unsub()
