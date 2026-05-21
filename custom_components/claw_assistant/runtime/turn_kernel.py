

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.helpers import intent

from .internal_llm import reset_runtime_tool_mode, set_runtime_tool_mode
from .kernel_sidechain import (
    create_kernel_sidechain,
    close_kernel_sidechain,
    get_current_kernel_sidechain,
)
from .loop_controller import check_tool_repeat, finalize_kernel_step, record_kernel_step
from .native_chatlog_bridge import (
    append_final_message_and_pause,
    discard_last_planner_message,
)
from .prompting import _fit_base_prompt
from .response_format import get_response_text
from .state import get_conversation_status, get_tool_calls_state, get_tool_results_state
from .step_protocol import AgentStep, StepProtocolError, parse_agent_step, render_step_contract
from .tool_executor import execute_kernel_tool, list_kernel_tool_specs

LOGGER = logging.getLogger(__name__)

_MAX_KERNEL_STEPS = 8


def _append_prompt(base: str | None, extra: str) -> str:
    return _fit_base_prompt(base or "", [extra])


def _build_kernel_planner_prompt(
    *,
    user_text: str,
    steps: list[dict[str, Any]],
    step_index: int,
) -> str:
    """Build an independent kernel planner prompt.
    
    This is a standalone protocol prompt, NOT appended to the main conversation prompt.
    The kernel planner only needs:
    1. Step contract (output format)
    2. Tool catalog (what tools are available)
    3. Completed steps (what has been done)
    4. Planner rules (current goal and constraints)
    """
    sections = [
        "# Kernel Planner Mode",
        "You are a step-by-step planner. Your job is to decide the next action to achieve the user's goal.",
        "You do NOT have access to conversation history or workspace documents in this mode.",
        "Focus only on the current goal and available tools.",
        "",
        render_step_contract(),
        "",
        _render_tool_catalog(full=(step_index == 1)),
        "",
        _render_completed_steps(steps),
        "",
        _render_planner_rules(user_text=user_text, steps=steps),
    ]
    return "\n".join(sections)


def _step_fingerprint(step: AgentStep) -> str:
    if step.kind != "call_tool":
        return step.kind
    return f"{step.tool_name}:{json.dumps(step.tool_args, ensure_ascii=False, sort_keys=True)}"


def _render_tool_catalog(*, full: bool = True) -> str:
    if not full:
        return "## Allowed Runtime Tools\nSee step 1 for the full tool list."
    lines = ["## Allowed Runtime Tools"]
    for spec in list_kernel_tool_specs():
        lines.append(
            f'- {spec["name"]} ({spec["category"]}): {spec["description"]}'
        )
    return "\n".join(lines)


def _render_completed_steps(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return "## Completed Steps\n- none yet"

    lines = ["## Completed Steps"]
    for step in steps[-8:]:
        title = step.get("title") or step.get("tool_name") or step.get("kind")
        status = step.get("status", "unknown")
        observation = str(step.get("observation", "")).strip()
        lines.append(f'- Step {step.get("index", "?")}: {title} [{status}]')
        if observation:
            lines.append(f"  Observation: {observation[:500]}")
    return "\n".join(lines)


def _render_planner_rules(
    *,
    user_text: str,
    steps: list[dict[str, Any]],
) -> str:
    tried = sorted(
        {
            step.get("fingerprint", "")
            for step in steps
            if step.get("fingerprint")
        }
    )
    tried_block = "\n".join(f"- {item}" for item in tried) if tried else "- none yet"
    return (
        "## Kernel Planner Rules\n"
        f'Current user goal: "{user_text}"\n'
        "- Decide only the next best action.\n"
        "- Use one tool per iteration at most.\n"
        "- If enough evidence already exists, return final.\n"
        "- If the user must answer a question, return ask_user.\n"
        "- If repeated attempts are failing, return stop or final.\n"
        "## Previously Attempted Actions\n"
        f"{tried_block}"
    )


def _render_final_answer(final_answer: str, steps: list[dict[str, Any]]) -> str:
    lines = ["Execution process:"]
    for step in steps:
        title = step.get("title") or step.get("tool_name") or step.get("kind")
        lines.append(f'{step.get("index", "?")}. {title}')
        explanation = str(step.get("explanation", "")).strip()
        observation = str(step.get("observation", "")).strip()
        if explanation:
            lines.append(f"Explanation: {explanation}")
        if observation:
            lines.append(f"Result: {observation}")
    lines.append("")
    lines.append("Conclusion:")
    lines.append(final_answer.strip())
    return "\n".join(line for line in lines if line is not None).strip()


def _render_step_message(step: AgentStep, index: int) -> str:
    lines = [f"Step {index}: {step.step_title}"]
    if step.step_explanation:
        lines.append(step.step_explanation)
    if step.expected_output:
        lines.append(f"Expected: {step.expected_output}")
    return "\n".join(lines)


def _render_observation_message(index: int, title: str, observation: str) -> str:
    lines = [f"Step {index} result: {title}"]
    if observation:
        lines.append(observation)
    return "\n".join(lines)


def _finalize_result(result: Any, final_text: str) -> Any:

    response = getattr(result, "response", None)
    if response is None:
        return result
    response.async_set_speech(final_text)
    response.response_type = intent.IntentResponseType.ACTION_DONE
    return result


async def execute_kernel_turn(
    hass,
    *,
    original_async_converse,
    user_text: str,
    conversation_id,
    context,
    language,
    agent_id: str | None,
    device_id,
    satellite_id,
    extra_system_prompt: str | None,
) -> Any | None:

    from .config import DEFAULT_FALLBACK_AGENT_ID

    agent_id = agent_id or DEFAULT_FALLBACK_AGENT_ID
    tool_calls_state = get_tool_calls_state(hass)
    tool_results_state = get_tool_results_state(hass)
    tool_calls_state.clear()
    tool_results_state.clear()

    sidechain = create_kernel_sidechain(
        conversation_id=str(conversation_id or "default"),
        user_text=user_text,
    )
    steps: list[dict[str, Any]] = []
    last_result = None
    get_conversation_status(hass)["kernel_mode_active"] = True

    try:
        for step_index in range(1, _MAX_KERNEL_STEPS + 1):
            kernel_prompt = _build_kernel_planner_prompt(
                user_text=user_text,
                steps=steps,
                step_index=step_index,
            )

            try:
                from .context_compressor import sanitize_tool_pairs
                from homeassistant.util.hass_dict import HassKey
                _DK: HassKey = HassKey("conversation_chat_log")
                _all = hass.data.get(_DK)
                _cl = _all.get(conversation_id) if _all else None
                if _cl and hasattr(_cl, "content") and _cl.content:
                    _fixed = sanitize_tool_pairs(_cl.content)
                    if _fixed is not _cl.content:
                        _cl.content.clear()
                        _cl.content.extend(_fixed)
            except Exception:
                pass

            tool_mode_token = set_runtime_tool_mode("kernel")
            chat_log_len_before = 0
            try:
                from homeassistant.util.hass_dict import HassKey
                _DK: HassKey = HassKey("conversation_chat_log")
                _all = hass.data.get(_DK)
                _cl = _all.get(conversation_id) if _all else None
                if _cl and hasattr(_cl, "content"):
                    chat_log_len_before = len(_cl.content)
            except Exception:
                pass
            try:
                import asyncio as _aio
                result = await _aio.wait_for(
                    original_async_converse(
                        hass,
                        user_text,
                        conversation_id,
                        context,
                        language,
                        agent_id,
                        device_id,
                        satellite_id,
                        kernel_prompt,
                    ),
                    timeout=120,
                )
            except _aio.TimeoutError:
                LOGGER.warning("Kernel API call timed out after 120s at step %d", step_index)
                if steps:
                    final_text = _render_final_answer(
                        "API call timed out; concluding based on completed steps.",
                        steps,
                    )
                    await append_final_message_and_pause(agent_id=agent_id, content=final_text)
                    return _finalize_result(last_result, final_text) if last_result else None
                return None
            finally:
                reset_runtime_tool_mode(tool_mode_token)
                try:
                    _all = hass.data.get(_DK)
                    _cl = _all.get(conversation_id) if _all else None
                    if _cl and hasattr(_cl, "content") and len(_cl.content) > chat_log_len_before:
                        del _cl.content[chat_log_len_before:]
                        LOGGER.debug(
                            "Kernel sidechain: trimmed %d entries from main chat log",
                            len(_cl.content) - chat_log_len_before,
                        )
                except Exception:
                    pass

            last_result = result
            planner_text = get_response_text(result)
            try:
                step = parse_agent_step(planner_text)
            except StepProtocolError as err:
                LOGGER.info("Kernel planner returned invalid step: %s", err)
                if not steps:
                    return None
                final_text = _render_final_answer(
                    f"Completed partial steps, but planner output was invalid: {err}",
                    steps,
                )
                await append_final_message_and_pause(agent_id=agent_id, content=final_text)
                return _finalize_result(result, final_text)

            if step.kind == "final":
                final_text = _render_final_answer(step.final_answer, steps)
                await append_final_message_and_pause(agent_id=agent_id, content=final_text)
                return _finalize_result(result, final_text)

            if step.kind == "ask_user":
                await append_final_message_and_pause(agent_id=agent_id, content=step.user_question)
                return _finalize_result(result, step.user_question)

            if step.kind == "stop":
                await append_final_message_and_pause(agent_id=agent_id, content=step.stop_reason)
                return _finalize_result(result, step.stop_reason)

            fingerprint = _step_fingerprint(step)
            if any(existing.get("fingerprint") == fingerprint for existing in steps):
                final_text = _render_final_answer(
                    "Planner attempted to repeat the same action; stopping loop and concluding based on existing information.",
                    steps,
                )
                await append_final_message_and_pause(agent_id=agent_id, content=final_text)
                return _finalize_result(result, final_text)

            if step.tool_name:
                from ..const import (
                    CONF_MAX_TOOL_REPEAT, DEFAULT_MAX_TOOL_REPEAT,
                    CONF_IDENTICAL_CALL_WARN, DEFAULT_IDENTICAL_CALL_WARN,
                    CONF_IDENTICAL_CALL_STOP, DEFAULT_IDENTICAL_CALL_STOP,
                )
                max_repeat = DEFAULT_MAX_TOOL_REPEAT
                identical_warn = DEFAULT_IDENTICAL_CALL_WARN
                identical_stop = DEFAULT_IDENTICAL_CALL_STOP
                for entry in hass.config_entries.async_entries("claw_assistant"):
                    max_repeat = int(entry.options.get(CONF_MAX_TOOL_REPEAT, DEFAULT_MAX_TOOL_REPEAT))
                    identical_warn = int(entry.options.get(CONF_IDENTICAL_CALL_WARN, DEFAULT_IDENTICAL_CALL_WARN))
                    identical_stop = int(entry.options.get(CONF_IDENTICAL_CALL_STOP, DEFAULT_IDENTICAL_CALL_STOP))
                    break
                bail_prompt, should_stop = check_tool_repeat(
                    hass,
                    tool_name=step.tool_name,
                    tool_args=step.tool_args,
                    max_repeat=max_repeat,
                    identical_warn=identical_warn,
                    identical_stop=identical_stop,
                )
                if should_stop:
                    LOGGER.warning(
                        "Identical tool loop detected: %s, requesting graceful stop",
                        step.tool_name,
                    )
                    extra_system_prompt = _append_prompt(extra_system_prompt, bail_prompt)
                    continue
                if bail_prompt:
                    LOGGER.warning(
                        "Tool repeat limit reached: %s",
                        step.tool_name,
                    )
                    extra_system_prompt = _append_prompt(extra_system_prompt, bail_prompt)
                    continue

            record = record_kernel_step(
                hass,
                kind=step.kind,
                title=step.step_title,
                explanation=step.step_explanation,
                tool_name=step.tool_name,
                tool_args=step.tool_args,
            )
            record["expected_output"] = step.expected_output
            record["fingerprint"] = fingerprint
            sidechain.add_step(
                index=step_index,
                kind=step.kind,
                title=step.step_title,
                explanation=step.step_explanation,
                tool_name=step.tool_name,
                tool_args=step.tool_args,
                expected_output=step.expected_output,
                fingerprint=fingerprint,
            )

            tool_result = await execute_kernel_tool(
                hass,
                tool_name=step.tool_name,
                tool_args=step.tool_args,
                agent_id=agent_id,
                context=context,
                language=language,
                device_id=device_id,
            )
            tool_calls_state.append({
                "tool_name": step.tool_name,
                "tool_args": step.tool_args,
                "success": tool_result.get("success", False),
            })
            tool_results_state.append(
                {
                    "tool_name": tool_result["tool_name"],
                    "tool_args": tool_result["tool_args"],
                    "success": tool_result["success"],
                    "error": tool_result["error"],
                    "result": tool_result["result"],
                }
            )

            observation = str(tool_result.get("summary") or "").strip()
            if not observation:
                observation = (
                    f'{tool_result["tool_name"]} succeeded'
                    if tool_result.get("success", False)
                    else f'{tool_result["tool_name"]} failed'
                )
            finalize_kernel_step(
                hass,
                success=bool(tool_result.get("success", False)),
                observation=observation,
            )
            record["status"] = "done" if tool_result.get("success", False) else "failed"
            record["observation"] = observation
            sidechain.finalize_step(
                success=bool(tool_result.get("success", False)),
                observation=observation,
            )
            steps.append(record)

        if last_result is None:
            return None

        final_text = _render_final_answer(
            "Step budget reached; concluding based on completed steps.",
            steps,
        )
        await append_final_message_and_pause(agent_id=agent_id, content=final_text)
        return _finalize_result(last_result, final_text)
    finally:
        close_kernel_sidechain()
        get_conversation_status(hass)["kernel_mode_active"] = False
