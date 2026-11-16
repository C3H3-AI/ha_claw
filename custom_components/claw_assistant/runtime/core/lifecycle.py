

from __future__ import annotations

import inspect
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..storage.adaptive_memory import async_setup_adaptive_memory
from ..utils.coordinator import setup_ai_coordinator
from ..utils.data_path import init_storage, output_dir_path
from ..utils.frontend_loader import (
    async_setup_frontend_loader,
    async_unload_frontend_loader,
)
from ..storage.graph_service import async_setup_graph_store, async_unload_graph_store
from ..storage.ha_guide_store import async_setup_homeassistant_guide_store
from ..hooks.hook import uninstall_conversation_hook
from ..llm.internal_llm import async_setup_internal_llm, async_unload_internal_llm
from ..hooks.official_websocket_hook import (
    install_official_websocket_process_hook,
    uninstall_official_websocket_process_hook,
)
from ..utils.output_cleanup import async_setup_output_cleanup, async_unload_output_cleanup
from ..hooks.patches import (
    async_downgrade_intents_package,
    patch_apiinstance_tool_fallback,
    patch_chat_log_result_extraction,
    patch_global_response_format,
    patch_hide_tool_calls_from_pipeline,
    patch_local_intents,
    patch_pipeline_timeout,
    patch_strip_thinking_content_serialization,
    patch_tool_progress,
    patch_websocket_binary_handler_noise,
    unpatch_apiinstance_tool_fallback,
    unpatch_chat_log_result_extraction,
    unpatch_global_response_format,
    unpatch_hide_tool_calls_from_pipeline,
    unpatch_local_intents,
    unpatch_pipeline_timeout,
    unpatch_strip_thinking_content_serialization,
    unpatch_tool_progress,
    unpatch_websocket_binary_handler_noise,
    patch_aihub_provider_timeout,
    unpatch_aihub_provider_timeout,
    patch_aihub_markdown_filter,
    unpatch_aihub_markdown_filter,
    patch_aihub_dynamic_max_tokens,
    unpatch_aihub_dynamic_max_tokens,
    async_patch_openai_allow_empty_key,
    unpatch_openai_allow_empty_key,
    patch_aihub_image_url_retry,
    unpatch_aihub_image_url_retry,
    patch_pipeline_websocket_detach,
    unpatch_pipeline_websocket_detach,
)
from ..storage.skill_store import async_setup_prompt_store
from ..utils.tmp_cleanup import async_setup_tmp_cleanup, async_unload_tmp_cleanup
from ..storage.curator import async_setup_curator, async_unload_curator
from ..storage.workspace_store import async_setup_workspace_store

LOGGER = logging.getLogger(__name__)


async def _warm_aihub_imports(hass: HomeAssistant) -> None:
    """Import the ai_hub module tree on the executor thread.

    ai_hub executes blocking file I/O at import time (consts/defaults.py
    reads ai_providers.json when its package __init__ runs). Our ai_hub
    patch functions import those modules from the event loop, which HA
    flags as a blocking call. Pre-importing here on a worker thread makes
    every subsequent import a sys.modules cache hit.
    """

    def _import_all() -> None:
        import importlib

        for mod in (
            "custom_components.ai_hub.consts",
            "custom_components.ai_hub.providers.base",
            "custom_components.ai_hub.providers.openai_compatible",
            "custom_components.ai_hub.providers.anthropic_compatible",
            "custom_components.ai_hub.providers.ollama_compatible",
            "custom_components.ai_hub.providers.edge_tts",
            "custom_components.ai_hub.providers.siliconflow_stt",
            "custom_components.ai_hub.markdown_filter",
            "custom_components.ai_hub.http",
            "custom_components.ai_hub.entity",
            "custom_components.ai_hub.conversation",
            "custom_components.ai_hub.intents",
        ):
            try:
                importlib.import_module(mod)
            except Exception:  # noqa: BLE001 — ai_hub may be absent or broken
                break

    await hass.async_add_executor_job(_import_all)


async def async_setup_runtime(hass: HomeAssistant, entry: ConfigEntry) -> None:

    from ..hooks.hook import install_conversation_hook

    await hass.async_add_executor_job(init_storage, hass)
    hass.config.allowlist_external_dirs.add(str(output_dir_path(hass)))
    await async_setup_workspace_store(hass)
    await async_setup_graph_store(hass)
    await async_setup_adaptive_memory(hass)
    await async_setup_homeassistant_guide_store(hass)
    await async_setup_prompt_store(hass)
    await async_setup_internal_llm(hass)
    await async_setup_output_cleanup(hass)
    await async_setup_tmp_cleanup(hass)
    await async_setup_curator(hass)
    await async_setup_frontend_loader(hass)
    await _safe_patch("intents-downgrade", async_downgrade_intents_package, hass)
    # The ai_hub patch functions below import ai_hub modules synchronously.
    # That import chain runs ai_hub's module-level code (consts/defaults.py
    # reads ai_providers.json), which HA flags as a blocking call on the
    # event loop. Warm the import on the executor thread first so every
    # later import in the patch group is a cache hit.
    await _warm_aihub_imports(hass)
    for name, patch in (
        ("local-intents", patch_local_intents),
        ("websocket-binary-noise", patch_websocket_binary_handler_noise),
        ("chat-log-result", patch_chat_log_result_extraction),
        ("pipeline-tool-hiding", patch_hide_tool_calls_from_pipeline),
        ("thinking-strip", patch_strip_thinking_content_serialization),
        ("tool-progress", patch_tool_progress),
        ("apiinstance-fallback", patch_apiinstance_tool_fallback),
        ("global-response-format", patch_global_response_format),
        ("pipeline-timeout", patch_pipeline_timeout),
        ("aihub-provider-timeout", patch_aihub_provider_timeout),
        ("aihub-markdown-filter", patch_aihub_markdown_filter),
        ("aihub-max-tokens", patch_aihub_dynamic_max_tokens),
        ("aihub-image-retry", patch_aihub_image_url_retry),
        ("pipeline-websocket-detach", patch_pipeline_websocket_detach),
    ):
        await _safe_patch(name, patch, hass)
    await _safe_patch("openai-empty-key", async_patch_openai_allow_empty_key, hass)
    await _safe_patch(
        "websocket-process-hook", install_official_websocket_process_hook, hass
    )
    await _safe_patch("ai-coordinator", setup_ai_coordinator, hass, entry)
    await _safe_patch("conversation-hook", install_conversation_hook, hass, entry)
    await _safe_patch("ai-hub-intent-bypass", _patch_ai_hub_intent_bypass)


async def _safe_patch(name: str, func: Any, *args: Any) -> None:
    """Run one hook installation step without aborting the whole setup.

    A single Home Assistant internals change used to raise out of
    async_setup_runtime, which surfaced as ConfigEntryNotReady/setup_error and
    took the entire integration down. Each step now logs and continues.
    """
    try:
        result = func(*args)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # noqa: BLE001 — one broken hook must not abort setup
        LOGGER.warning("claw_assistant hook '%s' failed to install: %s", name, exc)



def _patch_ai_hub_intent_bypass() -> None:
    try:
        from custom_components.ai_hub.conversation import AIHubConversationAgent
        original = getattr(AIHubConversationAgent, "_async_handle_local_and_builtin_intents", None)
        if original is None or getattr(original, "_patched_for_consult", False):
            return

        async def _patched(self, user_input, chat_log):
            if "[PEER-CONSULT]" in getattr(user_input, "text", ""):
                LOGGER.debug("ai_hub intent bypass active for peer consult")
                return None
            return await original(self, user_input, chat_log)

        _patched._patched_for_consult = True
        AIHubConversationAgent._async_handle_local_and_builtin_intents = _patched
        LOGGER.debug("ai_hub intent bypass hook installed")
    except Exception as exc:
        LOGGER.debug("ai_hub intent bypass hook skipped: %s", exc)


async def async_unload_runtime(hass: HomeAssistant) -> None:

    from ...index_manager import async_cleanup_index_manager

    await async_cleanup_index_manager(hass)
    await async_unload_graph_store(hass)
    await async_unload_output_cleanup(hass)
    await async_unload_tmp_cleanup(hass)
    await async_unload_curator(hass)
    async_unload_frontend_loader(hass)
    for name, uninstall, args in (
        ("conversation-hook", uninstall_conversation_hook, (hass,)),
        (
            "websocket-process-hook",
            uninstall_official_websocket_process_hook,
            (hass,),
        ),
        ("tool-progress", unpatch_tool_progress, ()),
        ("global-response-format", unpatch_global_response_format, ()),
        ("apiinstance-fallback", unpatch_apiinstance_tool_fallback, ()),
        (
            "thinking-strip",
            unpatch_strip_thinking_content_serialization,
            (),
        ),
        ("pipeline-tool-hiding", unpatch_hide_tool_calls_from_pipeline, ()),
        ("chat-log-result", unpatch_chat_log_result_extraction, ()),
        ("local-intents", unpatch_local_intents, ()),
        ("websocket-binary-noise", unpatch_websocket_binary_handler_noise, ()),
        ("pipeline-timeout", unpatch_pipeline_timeout, ()),
        ("aihub-provider-timeout", unpatch_aihub_provider_timeout, ()),
        ("aihub-max-tokens", unpatch_aihub_dynamic_max_tokens, ()),
        ("aihub-image-retry", unpatch_aihub_image_url_retry, ()),
        ("pipeline-websocket-detach", unpatch_pipeline_websocket_detach, (hass,)),
        ("openai-empty-key", unpatch_openai_allow_empty_key, ()),
        ("aihub-markdown-filter", unpatch_aihub_markdown_filter, ()),
    ):
        try:
            result = uninstall(*args)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001 — unload must always continue
            LOGGER.warning(
                "claw_assistant hook '%s' failed to uninstall: %s", name, exc
            )
    async_unload_internal_llm(hass)
