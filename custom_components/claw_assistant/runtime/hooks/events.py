from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from time import monotonic
from typing import Any, Literal

from homeassistant.core import HomeAssistant

from ...const import DOMAIN
from ..core.state import get_runtime_store

LOGGER = logging.getLogger(__name__)

HookEvent = Literal["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]
HookDecision = Literal["pass", "block", "warn", "error"]
HookListener = Callable[["HookPayload"], Awaitable["HookOutcome | None"]]

EVENTS: tuple[HookEvent, ...] = (
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
)
BLOCKING_EVENTS: frozenset[HookEvent] = frozenset(
    {"UserPromptSubmit", "PreToolUse"}
)
_LISTENERS_KEY = "hook_event_listeners"
_RECENT_RUNS_KEY = "hook_recent_runs"
_RECENT_RUNS_LIMIT = 80


@dataclass(slots=True)
class HookPayload:
    event: HookEvent
    conversation_id: str | None = None
    agent_id: str | None = None
    user_text: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class HookOutcome:
    name: str
    decision: HookDecision = "pass"
    message: str = ""
    duration_ms: int = 0


@dataclass(slots=True)
class HookReport:
    event: HookEvent
    outcomes: list[HookOutcome]
    blocked: bool = False


def _listeners(hass: HomeAssistant) -> dict[HookEvent, list[tuple[str, HookListener]]]:
    store = get_runtime_store(hass)
    listeners = store.setdefault(_LISTENERS_KEY, {})
    for event in EVENTS:
        listeners.setdefault(event, [])
    return listeners


def register_hook_listener(
    hass: HomeAssistant,
    event: HookEvent,
    name: str,
    listener: HookListener,
) -> Callable[[], None]:
    if event not in EVENTS:
        raise ValueError(f"Unknown hook event: {event}")

    bucket = _listeners(hass)[event]
    bucket.append((name, listener))

    def _unregister() -> None:
        try:
            bucket.remove((name, listener))
        except ValueError:
            pass

    return _unregister


async def fire_hook_event(
    hass: HomeAssistant,
    payload: HookPayload,
) -> HookReport:
    outcomes: list[HookOutcome] = []
    blocked = False

    for name, listener in list(_listeners(hass).get(payload.event, [])):
        start = monotonic()
        try:
            outcome = await listener(payload)
        except Exception as err:  # noqa: BLE001
            LOGGER.warning(
                "Hook listener %s failed for %s: %s",
                name,
                payload.event,
                err,
            )
            outcome = HookOutcome(name=name, decision="error", message=str(err))

        if outcome is None:
            outcome = HookOutcome(name=name)
        elif not outcome.name:
            outcome.name = name
        outcome.duration_ms = int((monotonic() - start) * 1000)
        outcomes.append(outcome)

        if payload.event in BLOCKING_EVENTS and outcome.decision == "block":
            blocked = True
            break

    report = HookReport(event=payload.event, outcomes=outcomes, blocked=blocked)
    _remember_hook_report(hass, payload, report)
    return report


def get_recent_hook_runs(hass: HomeAssistant) -> list[dict[str, Any]]:
    runs = get_runtime_store(hass).get(_RECENT_RUNS_KEY)
    if not runs:
        return []
    return list(runs)


def _remember_hook_report(
    hass: HomeAssistant,
    payload: HookPayload,
    report: HookReport,
) -> None:
    if not report.outcomes:
        return

    store = get_runtime_store(hass)
    runs = store.get(_RECENT_RUNS_KEY)
    if runs is None:
        runs = deque(maxlen=_RECENT_RUNS_LIMIT)
        store[_RECENT_RUNS_KEY] = runs

    for outcome in report.outcomes:
        runs.append(
            {
                "event": report.event,
                "listener": outcome.name,
                "decision": outcome.decision,
                "message": outcome.message,
                "duration_ms": outcome.duration_ms,
                "conversation_id": payload.conversation_id,
                "agent_id": payload.agent_id,
                "tool_name": payload.tool_name,
                "domain": DOMAIN,
            }
        )
