

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_SUPPORTED_STEP_KINDS = frozenset({"call_tool", "final", "ask_user", "stop"})


class StepProtocolError(ValueError):
    pass

@dataclass(slots=True, frozen=True)
class AgentStep:


    kind: str
    step_title: str = ""
    step_explanation: str = ""
    expected_output: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    final_answer: str = ""
    user_question: str = ""
    stop_reason: str = ""


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None

    candidates = [stripped]
    if match := _JSON_BLOCK_RE.search(stripped):
        candidates.insert(0, match.group(1).strip())

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _coerce_legacy_toolcalls_payload(payload: dict[str, Any]) -> dict[str, Any]:

    mode = str(payload.get("mode", "")).strip().lower()
    raw_calls = payload.get("toolcalls")
    if not isinstance(raw_calls, list):
        raw_calls = payload.get("tool_calls")

    if mode not in {"toolcalls", "tool_calls"} and not isinstance(raw_calls, list):
        return payload

    if not isinstance(raw_calls, list) or len(raw_calls) != 1:
        raise StepProtocolError(
            "Legacy toolcalls payload must contain exactly one tool call"
        )

    raw_call = raw_calls[0]
    if not isinstance(raw_call, dict):
        raise StepProtocolError("Legacy tool call entry must be an object")

    tool_name = str(raw_call.get("name", "")).strip()
    if not tool_name:
        raise StepProtocolError("Legacy tool call is missing name")

    tool_args = raw_call.get("arguments", {})
    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except json.JSONDecodeError as err:
            raise StepProtocolError(
                "Legacy tool call arguments are not valid JSON"
            ) from err

    if not isinstance(tool_args, dict):
        raise StepProtocolError("Legacy tool call arguments must be an object")

    return {
        "kind": "call_tool",
        "step_title": str(raw_call.get("step_title") or f"Call {tool_name}").strip(),
        "step_explanation": str(
            raw_call.get("step_explanation")
            or f"Execute runtime tool {tool_name}."
        ).strip(),
        "expected_output": str(raw_call.get("expected_output") or "").strip(),
        "tool_name": tool_name,
        "tool_args": tool_args,
    }


def parse_agent_step(text: str) -> AgentStep:

    payload = _extract_json_object(text)
    if payload is None:
        raise StepProtocolError("Planner response is not valid JSON")
    payload = _coerce_legacy_toolcalls_payload(payload)

    kind = str(payload.get("kind", "")).strip().lower()
    if kind not in _SUPPORTED_STEP_KINDS:
        raise StepProtocolError(f"Unsupported planner action kind: {kind or '<empty>'}")

    step = AgentStep(
        kind=kind,
        step_title=str(payload.get("step_title", "")).strip(),
        step_explanation=str(payload.get("step_explanation", "")).strip(),
        expected_output=str(payload.get("expected_output", "")).strip(),
        tool_name=str(payload.get("tool_name", "")).strip(),
        tool_args=payload.get("tool_args", {}) if isinstance(payload.get("tool_args", {}), dict) else {},
        final_answer=str(payload.get("final_answer", "")).strip(),
        user_question=str(payload.get("user_question", "")).strip(),
        stop_reason=str(payload.get("stop_reason", "")).strip(),
    )
    _validate_agent_step(step)
    return step


def _validate_agent_step(step: AgentStep) -> None:
    if step.kind == "call_tool":
        if not step.tool_name:
            raise StepProtocolError("call_tool action requires tool_name")
        if not step.step_title:
            raise StepProtocolError("call_tool action requires step_title")
        if not step.step_explanation:
            raise StepProtocolError("call_tool action requires step_explanation")
        return

    if step.kind == "final" and not step.final_answer:
        raise StepProtocolError("final action requires final_answer")
    if step.kind == "ask_user" and not step.user_question:
        raise StepProtocolError("ask_user action requires user_question")
    if step.kind == "stop" and not step.stop_reason:
        raise StepProtocolError("stop action requires stop_reason")


def render_step_contract() -> str:

    return (
        "## Kernel Step Contract\n"
        "You are not allowed to call tools directly in this mode. "
        "Return exactly one JSON object and nothing else.\n\n"
        "Supported actions:\n"
        '1. {"kind":"call_tool","step_title":"...","step_explanation":"...",'
        '"expected_output":"...","tool_name":"ToolName","tool_args":{...}}\n'
        '2. {"kind":"final","final_answer":"..."}\n'
        '3. {"kind":"ask_user","user_question":"..."}\n'
        '4. {"kind":"stop","stop_reason":"..."}\n\n'
        "Rules:\n"
        "- Choose at most one action.\n"
        "- Prefer call_tool when information is missing.\n"
        "- Use final only when you can fully answer.\n"
        "- Never wrap the JSON in prose.\n"
        "- Never repeat an already-failed identical tool call.\n"
        "- Do not invent tool results."
    )
