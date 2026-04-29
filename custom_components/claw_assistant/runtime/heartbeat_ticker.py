from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from custom_components.cn_im_hub.rich_media import (
    GifSegment,
    ImageSegment,
    TextSegment,
    VideoSegment,
    VoiceSegment,
    is_camera_entity,
    parse_reply_segments,
)

from .heartbeat_store import get_due_tasks, async_record_heartbeat_result, HeartbeatTask

LOGGER = logging.getLogger(__name__)
_TICK_INTERVAL = timedelta(seconds=10)
_UNSUB_KEY = "heartbeat_ticker_unsub"

_HEARTBEAT_SYSTEM_PROMPT = (
    "You are a background heartbeat agent running an automated task. "
    "RULES: "
    "1. NEVER call the Notify tool. Your reply IS the notification — it will be auto-delivered to the user. "
    "2. Use other tools (HAControl, SmartDiscovery, etc.) if the task requires device data. "
    "3. Reply with SHORT, user-facing Chinese text only. No markdown, no questions. "
    "4. If delivery capability hints are present in the task text, you may use the listed media tags exactly as described there. "
    "5. If you see an AUTO_DELIVER marker, your reply goes straight to that channel — just write the message content."
)


def _build_delivery_capability_hint(channel: str) -> str:
    provider = _channel_provider(channel)
    if provider == "qq":
        return (
            "[DELIVERY_CAPABILITIES] "
            "Supported tags for this channel: "
            "`[VOICE:<speech text>]`, `[IMAGE:camera.entity_id]`, "
            "`[VIDEO:camera.entity_id]`, `[GIF:camera.entity_id]`. "
            "Use tags only when the media itself should be delivered."
        )
    if provider == "wechat":
        return (
            "[DELIVERY_CAPABILITIES] "
            "Supported tags for this channel: "
            "`[IMAGE:camera.entity_id]`. "
            "Use tags only when the media itself should be delivered."
        )
    return ""


def _build_heartbeat_text(task: HeartbeatTask) -> str:
    parts = [f"[heartbeat:{task.slug}]"]
    if task.objective:
        parts.append(task.objective)
    if task.steps:
        parts.append(f"Steps: {task.steps}")
    if task.notify_channel:
        from .state import get_channel_type
        ch_type = get_channel_type(task.notify_channel)
        if ch_type != "ha":
            parts.append(f"[AUTO_DELIVER:{ch_type}] Your reply text will be sent to {ch_type} automatically. Do NOT call Notify.")
            capability_hint = _build_delivery_capability_hint(task.notify_channel)
            if capability_hint:
                parts.append(capability_hint)
        else:
            parts.append(f"[AUTO_DELIVER:{task.notify_channel}]")
    return " ".join(parts)


async def _tick(hass: HomeAssistant, _now: Any = None) -> None:
    due_tasks = await hass.async_add_executor_job(get_due_tasks)
    if not due_tasks:
        return

    from .state import get_runtime_store

    from homeassistant.components.conversation import agent_manager

    runtime_store = get_runtime_store(hass)
    if not runtime_store.get("original_async_converse"):
        LOGGER.warning("Heartbeat ticker: runtime hook not ready")
        return

    for task in due_tasks:
        LOGGER.info("Heartbeat due: %s — %s", task.slug, task.objective)
        try:
            text = _build_heartbeat_text(task)
            result = await agent_manager.async_converse(
                hass,
                text,
                f"heartbeat_{task.slug}",
                hass.data.get("claw_assistant_context"),
                None,
                None,
                None,
                None,
                _HEARTBEAT_SYSTEM_PROMPT,
            )
            speech = ""
            if result.response.speech:
                speech = (
                    result.response.speech.get("plain", {}).get("speech", "")
                    if isinstance(result.response.speech, dict)
                    else ""
                )
            if speech and task.notify_channel:
                await _push_reply_to_channel(hass, task.notify_channel, speech)
            status = "success" if speech else "executed"
            await async_record_heartbeat_result(
                hass, slug=task.slug, status=status, note="auto-tick"
            )
        except Exception:
            LOGGER.exception("Heartbeat tick failed for %s", task.slug)
            await async_record_heartbeat_result(
                hass, slug=task.slug, status="error", note="auto-tick failed"
            )


def _build_im_service_data(channel: str, message: str = "") -> dict[str, str]:
    parts = channel.split(":", 2)
    provider = parts[0] if parts else ""
    if provider == "wechat":
        svc_data: dict[str, str] = {
            "channel": "wechat/user_id",
            "message": message,
        }
        if len(parts) >= 2:
            svc_data["wechat_account_id"] = parts[1]
        if len(parts) >= 3:
            svc_data["target"] = parts[2]
        return svc_data
    if provider == "qq":
        if len(parts) < 3 or parts[1] not in ("user", "group", "channel"):
            raise ValueError("QQ notify_channel must be qq:user:openid, qq:group:group_openid, or qq:channel:channel_id")
        return {
            "channel": f"qq/{parts[1]}",
            "message": message,
            "target": parts[2],
        }
    raise ValueError(f"Unknown notify_channel format: {channel}")


def _channel_provider(channel: str) -> str:
    return channel.split(":", 1)[0].strip() if channel else ""


async def _push_to_channel(hass: HomeAssistant, channel: str, message: str) -> None:
    if not hass.services.has_service("cn_im_hub", "send_message"):
        raise RuntimeError("cn_im_hub.send_message not available yet")
    await hass.services.async_call(
        "cn_im_hub", "send_message", _build_im_service_data(channel, message), blocking=True,
    )


async def _push_reply_to_channel(hass: HomeAssistant, channel: str, reply: str) -> None:
    segments = parse_reply_segments(reply)
    for segment in segments:
        if isinstance(segment, TextSegment):
            if segment.text.strip():
                await _push_to_channel(hass, channel, segment.text)
            continue

        if isinstance(segment, ImageSegment):
            if not is_camera_entity(segment.source):
                raise ValueError("Heartbeat media only supports camera entity sources for now")
            svc_data = _build_im_service_data(channel)
            svc_data["camera_entity"] = segment.source
            await hass.services.async_call(
                "cn_im_hub", "send_message", svc_data, blocking=True,
            )
            continue

        if isinstance(segment, VoiceSegment):
            if _channel_provider(channel) == "qq":
                svc_data = _build_im_service_data(channel)
                svc_data["tts_text"] = segment.text
                await hass.services.async_call(
                    "cn_im_hub", "send_message", svc_data, blocking=True,
                )
            elif segment.text.strip():
                await _push_to_channel(hass, channel, segment.text)
            continue

        if isinstance(segment, VideoSegment):
            if not is_camera_entity(segment.source):
                raise ValueError("Heartbeat video only supports camera entity sources")
            svc_data = _build_im_service_data(channel)
            svc_data["camera_entity"] = segment.source
            svc_data["media_type"] = "video"
            await hass.services.async_call(
                "cn_im_hub", "send_message", svc_data, blocking=True,
            )
            continue

        if isinstance(segment, GifSegment):
            if not is_camera_entity(segment.source):
                raise ValueError("Heartbeat GIF only supports camera entity sources")
            svc_data = _build_im_service_data(channel)
            svc_data["camera_entity"] = segment.source
            svc_data["media_type"] = "gif"
            await hass.services.async_call(
                "cn_im_hub", "send_message", svc_data, blocking=True,
            )
            continue


@callback
def async_setup_heartbeat_ticker(hass: HomeAssistant) -> None:
    if _UNSUB_KEY in hass.data:
        return

    @callback
    def _schedule_tick(now: Any) -> None:
        hass.async_create_task(_tick(hass, now), "heartbeat_tick")

    unsub = async_track_time_interval(hass, _schedule_tick, _TICK_INTERVAL)
    hass.data[_UNSUB_KEY] = unsub

    async def _deferred_initial_tick() -> None:
        from .state import get_runtime_store
        for _ in range(60):
            hook_ready = get_runtime_store(hass).get("original_async_converse")
            svc_ready = hass.services.has_service("cn_im_hub", "send_message")
            if hook_ready and svc_ready:
                break
            await asyncio.sleep(1)
        await _tick(hass)

    hass.async_create_task(_deferred_initial_tick(), "heartbeat_tick_initial")


@callback
def async_unload_heartbeat_ticker(hass: HomeAssistant) -> None:
    unsub = hass.data.pop(_UNSUB_KEY, None)
    if unsub:
        unsub()
