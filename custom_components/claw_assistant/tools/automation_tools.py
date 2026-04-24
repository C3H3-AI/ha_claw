"""Automation management tools for Home Assistant."""
from __future__ import annotations

import logging
import os
import re
import time
import uuid

import voluptuous as vol

from homeassistant.components.automation import DATA_COMPONENT, DOMAIN as AUTOMATION_DOMAIN
from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.const import CONF_ID, SERVICE_RELOAD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, llm
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.json import JsonObjectType
from homeassistant.util.yaml import dump, load_yaml

_LOGGER = logging.getLogger(__name__)


class AutomationTool(llm.Tool):
    """Manage Home Assistant automations via official APIs."""

    name = "Automation"
    description = (
        "Manage Home Assistant automations via official APIs (not shell/ConfigFile). "
        "Actions: list, get, create, update, delete, trigger, enable, disable. "
        "Params: action, automation_id, entity_id, config (dict, partial on update), icon, area_id, page, page_size. "
        "list returns paginated results (default page=1, page_size=10); response includes page/total_pages/total. "
        "create requires full config. update merges partial config over existing; "
        "icon and area_id target the entity registry entry (area must already exist)."
    )

    parameters = vol.Schema(
        {
            vol.Required("action"): vol.In(
                ["list", "get", "trigger", "enable", "disable", "create", "update", "delete"]
            ),
            vol.Optional("entity_id", default=""): str,
            vol.Optional("config", default={}): dict,
            vol.Optional("automation_id", default=""): str,
            vol.Optional("page", default=1): vol.Coerce(int),
            vol.Optional("page_size", default=10): vol.Coerce(int),
            vol.Optional("icon"): vol.Any(str, None),
            vol.Optional("area_id"): vol.Any(str, None),
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        """Execute automation tool action."""
        action = tool_input.tool_args.get("action", "list")
        entity_id = tool_input.tool_args.get("entity_id", "")
        automation_id = str(tool_input.tool_args.get("automation_id", "")).strip()
        config = tool_input.tool_args.get("config") or {}
        args = tool_input.tool_args
        # Entity-registry-level fields (icon/area_id). Use sentinel so that
        # omitting them preserves the current value, while explicitly passing
        # None clears it.
        _SENTINEL = object()
        icon = args.get("icon", _SENTINEL) if "icon" in args else _SENTINEL
        area_id = args.get("area_id", _SENTINEL) if "area_id" in args else _SENTINEL

        try:
            if action == "list":
                page = max(1, int(tool_input.tool_args.get("page", 1)))
                page_size = max(1, int(tool_input.tool_args.get("page_size", 10)))
                return await self._list_automations(hass, page=page, page_size=page_size)

            if action == "get":
                return await self._get_automation(hass, entity_id, automation_id)

            if action == "trigger" and entity_id:
                await hass.services.async_call(
                    "automation", "trigger", {"entity_id": entity_id}, blocking=True
                )
                return {"success": True, "message": f"Triggered {entity_id}"}

            if action == "enable" and entity_id:
                await hass.services.async_call(
                    "automation", "turn_on", {"entity_id": entity_id}, blocking=True
                )
                return {"success": True, "message": f"Enabled {entity_id}"}

            if action == "disable" and entity_id:
                await hass.services.async_call(
                    "automation", "turn_off", {"entity_id": entity_id}, blocking=True
                )
                return {"success": True, "message": f"Disabled {entity_id}"}

            if action == "create":
                return await self._create_or_update_automation(
                    hass, config, automation_id,
                    is_update=False, icon=icon, area_id=area_id, sentinel=_SENTINEL,
                )

            if action == "update":
                return await self._create_or_update_automation(
                    hass, config, automation_id,
                    is_update=True, icon=icon, area_id=area_id, sentinel=_SENTINEL,
                )

            if action == "delete":
                return await self._delete_automation(hass, entity_id, automation_id)

            return {"success": False, "error": "Invalid action or missing required parameters"}
        except Exception as err:
            _LOGGER.error("AutomationTool error: %s", err)
            return {"success": False, "error": str(err)}

    async def _list_automations(
        self, hass: HomeAssistant, *, page: int = 1, page_size: int = 10
    ) -> JsonObjectType:
        """List automations with pagination."""
        registry = er.async_get(hass)
        all_items = []
        for state in hass.states.async_all():
            if not state.entity_id.startswith("automation."):
                continue
            auto_id = state.entity_id.removeprefix("automation.")
            reg_entry = registry.async_get(state.entity_id)
            all_items.append({
                "entity_id": state.entity_id,
                "automation_id": auto_id,
                "name": state.name,
                "state": state.state,
                "icon": reg_entry.icon if reg_entry else None,
                "area_id": reg_entry.area_id if reg_entry else None,
            })
        total = len(all_items)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        items = all_items[start : start + page_size]
        return {
            "success": True,
            "automations": items,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total": total,
        }

    async def _get_automation(
        self, hass: HomeAssistant, entity_id: str, automation_id: str
    ) -> JsonObjectType:
        """Get full config of a single automation."""
        if not entity_id and automation_id:
            entity_id = f"automation.{automation_id}"
        if not entity_id:
            return {"success": False, "error": "entity_id or automation_id is required"}

        automation_component = hass.data.get(DATA_COMPONENT)
        if automation_component is None:
            return {"success": False, "error": "Automation component not loaded"}

        automation = automation_component.get_entity(entity_id)
        if automation is None:
            return {"success": False, "error": f"Automation not found: {entity_id}"}

        raw_config = getattr(automation, "raw_config", None)
        if raw_config is None:
            return {"success": False, "error": f"Cannot get config for {entity_id}"}

        config_id = raw_config.get("id", entity_id.removeprefix("automation."))
        registry = er.async_get(hass)
        reg_entry = registry.async_get(entity_id)
        return {
            "success": True,
            "entity_id": entity_id,
            "automation_id": config_id,
            "config": raw_config,
            "icon": reg_entry.icon if reg_entry else None,
            "area_id": reg_entry.area_id if reg_entry else None,
            "labels": sorted(reg_entry.labels) if reg_entry else [],
        }

    async def _load_existing_config(
        self, hass: HomeAssistant, automation_id: str
    ) -> dict | None:
        """Return the current raw config dict for an automation, or None.

        Prefer the in-memory loaded entity (fast, reflects runtime state). Fall
        back to reading automations.yaml directly when the entity is not loaded
        (e.g. disabled or failed to load).
        """
        component = hass.data.get(DATA_COMPONENT)
        if component is not None:
            auto = component.get_entity(f"automation.{automation_id}")
            if auto is not None:
                raw = getattr(auto, "raw_config", None)
                if isinstance(raw, dict):
                    return dict(raw)
        # Fallback: read automations.yaml
        path = hass.config.path(AUTOMATION_CONFIG_PATH)
        if not os.path.isfile(path):
            return None
        try:
            loaded = await hass.async_add_executor_job(load_yaml, path)
        except Exception as err:  # pragma: no cover - IO/YAML error path
            _LOGGER.warning("Failed to read %s: %s", path, err)
            return None
        if not isinstance(loaded, list):
            return None
        for item in loaded:
            if isinstance(item, dict) and str(item.get(CONF_ID, "")) == automation_id:
                return dict(item)
        return None

    async def _create_or_update_automation(
        self,
        hass: HomeAssistant,
        config: dict,
        automation_id: str,
        *,
        is_update: bool,
        icon=None,
        area_id=None,
        sentinel=None,
    ) -> JsonObjectType:
        """Create or update automation using HA's config view API (same as frontend).

        Update supports partial patches: any fields omitted from `config` are
        preserved from the existing automation. Only create requires a full config.
        """
        from homeassistant.components.config.automation import EditAutomationConfigView
        from homeassistant.helpers import config_validation as cv

        if not isinstance(config, dict):
            return {"success": False, "error": "config must be a dict"}

        if is_update and not automation_id:
            return {"success": False, "error": "automation_id is required for update"}

        # Track whether the caller supplied any YAML-level fields so we can
        # skip a pointless rewrite when they only want to touch icon/area_id.
        config_patch_empty = is_update and not config
        touch_icon = icon is not sentinel
        touch_area = area_id is not sentinel

        existing: dict | None = None
        if is_update:
            existing = await self._load_existing_config(hass, automation_id)
            if existing is None:
                return {
                    "success": False,
                    "error": f"Automation '{automation_id}' not found",
                }
            # Shallow merge: patch fields override existing; omitted fields preserved.
            merged = dict(existing)
            merged.update(config)
            config = merged

        if not config:
            return {"success": False, "error": "Missing required parameter: config (dict)"}

        alias = str(config.get("alias", "")).strip()
        if not alias:
            return {"success": False, "error": "config.alias is required"}
        if "trigger" not in config and "triggers" not in config:
            return {"success": False, "error": "config.trigger or config.triggers is required"}
        if "action" not in config and "actions" not in config:
            return {"success": False, "error": "config.action or config.actions is required"}

        if not automation_id:
            slug = re.sub(r"[^a-z0-9_]+", "_", alias.lower()).strip("_")
            automation_id = slug or f"auto_{int(time.time())}"

        if not is_update:
            dup = await self._load_existing_config(hass, automation_id)
            if dup is not None:
                return {
                    "success": False,
                    "error": f"Automation '{automation_id}' already exists (alias: {dup.get('alias', '?')}). Use update instead.",
                    "existing_id": automation_id,
                }
            for state in hass.states.async_all():
                if not state.entity_id.startswith("automation."):
                    continue
                if state.attributes.get("friendly_name", "").strip().lower() == alias.lower():
                    return {
                        "success": False,
                        "error": f"An automation with the same name '{alias}' already exists: {state.entity_id}. Use update to modify it.",
                        "existing_entity_id": state.entity_id,
                    }

        entry = dict(config)
        if CONF_ID in entry:
            del entry[CONF_ID]

        try:
            await async_validate_config_item(hass, automation_id, entry)
        except vol.Invalid as err:
            return {"success": False, "error": f"Invalid automation config: {err}"}

        async def hook(action: str, config_key: str) -> None:
            """Post-write hook that reloads automations."""
            await hass.services.async_call(
                AUTOMATION_DOMAIN, SERVICE_RELOAD, {CONF_ID: config_key}, blocking=True
            )

        view = EditAutomationConfigView(
            AUTOMATION_DOMAIN,
            "config",
            AUTOMATION_CONFIG_PATH,
            cv.string,
            post_write_hook=hook,
            data_validator=async_validate_config_item,
        )

        path = hass.config.path(AUTOMATION_CONFIG_PATH)

        # Short-circuit: metadata-only update (only icon/area_id, no config patch)
        # skips the YAML rewrite + reload entirely.
        wrote_yaml = False
        if not (config_patch_empty and (touch_icon or touch_area)):
            async with view.mutation_lock:
                current = await view.read_config(hass)
                view._write_value(hass, current, automation_id, entry)
                await hass.async_add_executor_job(
                    lambda: write_utf8_file_atomic(path, dump(current))
                )
            await hook("create_update", automation_id)
            wrote_yaml = True

        target_entity_id = f"automation.{automation_id}"
        applied: dict[str, object] = {}
        if touch_icon or touch_area:
            try:
                registry = er.async_get(hass)
                if registry.async_get(target_entity_id) is None:
                    applied["entity_registry"] = "entity not yet registered; retry after it exists"
                else:
                    kwargs: dict[str, object] = {}
                    if touch_icon:
                        kwargs["icon"] = icon if icon else None
                    if touch_area:
                        if area_id:
                            # Validate area exists to give AI a crisp error
                            from homeassistant.helpers import area_registry as ar

                            areas = ar.async_get(hass)
                            if areas.async_get_area(area_id) is None:
                                return {
                                    "success": False,
                                    "error": f"Area '{area_id}' not found; use Registry area action=list to discover.",
                                }
                            kwargs["area_id"] = area_id
                        else:
                            kwargs["area_id"] = None
                    registry.async_update_entity(target_entity_id, **kwargs)
                    applied["icon"] = kwargs.get("icon") if touch_icon else None
                    applied["area_id"] = kwargs.get("area_id") if touch_area else None
            except Exception as err:
                _LOGGER.warning("Failed to update entity registry for %s: %s", target_entity_id, err)
                applied["entity_registry_error"] = str(err)

        action_word = "Updated" if is_update else "Created"
        return {
            "success": True,
            "message": f"{action_word} automation '{alias}' (id={automation_id})",
            "automation_id": automation_id,
            "entity_id": target_entity_id,
            "yaml_rewritten": wrote_yaml,
            **({"applied_registry": applied} if applied else {}),
        }

    async def _delete_automation(
        self, hass: HomeAssistant, entity_id: str, automation_id: str
    ) -> JsonObjectType:
        """Delete automation using HA's config view API (same as frontend)."""
        from homeassistant.components.config.automation import EditAutomationConfigView
        from homeassistant.helpers import config_validation as cv

        real_config_id = automation_id
        target_entity_id = entity_id

        if entity_id and not automation_id:
            if not entity_id.startswith("automation."):
                entity_id = f"automation.{entity_id}"
            target_entity_id = entity_id
            automation_component = hass.data.get(DATA_COMPONENT)
            if automation_component:
                automation = automation_component.get_entity(entity_id)
                if automation and hasattr(automation, "raw_config"):
                    raw_config = automation.raw_config
                    if isinstance(raw_config, dict) and "id" in raw_config:
                        real_config_id = raw_config["id"]
                        _LOGGER.info(
                            "Found real config id %s for entity %s",
                            real_config_id, entity_id
                        )
            if not real_config_id:
                real_config_id = entity_id.removeprefix("automation.")

        if not real_config_id:
            return {"success": False, "error": "automation_id or entity_id is required"}

        async def delete_hook(action: str, config_key: str) -> None:
            """Post-delete hook that removes entity from registry."""
            ent_reg = er.async_get(hass)
            reg_entity_id = ent_reg.async_get_entity_id(
                AUTOMATION_DOMAIN, AUTOMATION_DOMAIN, config_key
            )
            if reg_entity_id:
                ent_reg.async_remove(reg_entity_id)

        view = EditAutomationConfigView(
            AUTOMATION_DOMAIN,
            "config",
            AUTOMATION_CONFIG_PATH,
            cv.string,
            post_write_hook=delete_hook,
            data_validator=async_validate_config_item,
        )

        path = hass.config.path(AUTOMATION_CONFIG_PATH)

        try:
            async with view.mutation_lock:
                current = await view.read_config(hass)
                value = view._get_value(hass, current, real_config_id)

                if value is None:
                    all_ids = [
                        item.get(CONF_ID) for item in current if isinstance(item, dict)
                    ]
                    return {
                        "success": False,
                        "error": f"Automation '{real_config_id}' not found. Available IDs: {all_ids}",
                    }

                view._delete_value(hass, current, real_config_id)
                await hass.async_add_executor_job(
                    lambda: write_utf8_file_atomic(path, dump(current))
                )

            await delete_hook("delete", real_config_id)

            return {
                "success": True,
                "message": f"Deleted automation (config_id={real_config_id})",
                "automation_id": real_config_id,
                "entity_id": target_entity_id,
            }
        except Exception as err:
            return {"success": False, "error": f"Failed to delete automation: {err}"}
