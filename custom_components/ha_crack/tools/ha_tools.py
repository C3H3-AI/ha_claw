from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from urllib.parse import quote, urlparse

import aiohttp
import voluptuous as vol
import voluptuous_serialize
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import llm
from homeassistant.loader import (
    Integration,
    IntegrationNotFound,
    async_get_config_flows,
    async_get_integration_descriptions,
    async_get_integrations,
)
from homeassistant.util.json import JsonObjectType

_LOGGER = logging.getLogger(__name__)


_SHELL_MAX_OUTPUT = 64 * 1024
_SHELL_DEFAULT_TIMEOUT = 30
_SHELL_MAX_TIMEOUT = 600


async def _run_shell(hass: HomeAssistant, params: dict) -> JsonObjectType:

    command = str(params.get("command", "")).strip()
    if not command:
        return {"success": False, "error": "Missing required parameter: command"}

    raw_timeout = params.get("timeout", _SHELL_DEFAULT_TIMEOUT) or _SHELL_DEFAULT_TIMEOUT
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError):
        timeout = _SHELL_DEFAULT_TIMEOUT
    timeout = max(1, min(timeout, _SHELL_MAX_TIMEOUT))

    cwd = params.get("cwd") or hass.config.config_dir

    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    except Exception as err:
        return {"success": False, "error": f"spawn failed: {err}"}

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "success": False,
            "error": f"command exceeded {timeout}s",
            "timeout": True,
            "elapsed": round(time.monotonic() - started, 3),
        }

    elapsed = round(time.monotonic() - started, 3)
    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")
    if len(stdout) > _SHELL_MAX_OUTPUT:
        stdout = stdout[:_SHELL_MAX_OUTPUT] + f"\n...[truncated, {len(stdout)} bytes total]"
    if len(stderr) > _SHELL_MAX_OUTPUT:
        stderr = stderr[:_SHELL_MAX_OUTPUT] + f"\n...[truncated, {len(stderr)} bytes total]"

    rc = proc.returncode if proc.returncode is not None else -1
    return {
        "success": rc == 0,
        "returncode": rc,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed": elapsed,
        "cwd": str(cwd),
    }


def _normalize_repo_source(value: str) -> dict[str, str]:

    raw = value.strip()
    if not raw:
        return {"raw": "", "repository": "", "source_url": "", "host": ""}

    host = ""
    source_url = ""
    repository = ""

    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        host = parsed.netloc.lower()
        source_url = raw
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            repository = f"{parts[0]}/{parts[1]}".rstrip("/")
            if repository.endswith(".git"):
                repository = repository[:-4]
    else:
        repository = raw.split("?")[0].split("#")[0].rstrip("/")

    if repository:
        repository = repository.strip("/")
        repository = repository[:-4] if repository.endswith(".git") else repository

    return {
        "raw": raw,
        "repository": repository,
        "source_url": source_url,
        "host": host,
    }


async def _search_github_repositories(query: str) -> list[dict[str, object]]:

    if not query.strip():
        return []

    results: list[dict[str, object]] = []
    async with aiohttp.ClientSession() as session:
        for search_query in [query, f"{query} home assistant", f"{query} hass"]:
            async with session.get(
                f"https://api.github.com/search/repositories?q={quote(search_query)}&sort=stars&per_page=10",
                headers={"Accept": "application/vnd.github.v3+json"},
            ) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json()
                for item in data.get("items", []):
                    full_name = item.get("full_name")
                    if full_name and not any(
                        result["full_name"] == full_name for result in results
                    ):
                        results.append(
                            {
                                "name": item.get("name"),
                                "full_name": full_name,
                                "description": item.get("description", "")[:150]
                                if item.get("description")
                                else "",
                                "stars": item.get("stargazers_count"),
                                "html_url": item.get("html_url", ""),
                            }
                        )
                        if len(results) >= 15:
                            break
            if len(results) >= 15:
                break

    results.sort(key=lambda item: int(item.get("stars", 0) or 0), reverse=True)
    return results[:15]


def _find_repo_by_query(hacs_data, query: str):
    query_lower = query.lower().strip()
    if not query_lower:
        return None
    for repo in hacs_data.repositories.list_all:
        haystacks = [
            str(repo.data.name or "").lower(),
            str(repo.data.full_name or "").lower(),
            str(repo.data.description or "").lower(),
            " ".join(repo.data.topics or []).lower(),
        ]
        if any(query_lower in hay for hay in haystacks):
            return repo
    return None


def _serialize_hacs_repo(repo) -> dict[str, object]:
    latest = repo.data.last_version or repo.data.last_commit
    return {
        "id": str(getattr(repo.data, "id", "")),
        "name": repo.data.name,
        "full_name": repo.data.full_name,
        "description": repo.data.description or "",
        "installed": bool(repo.data.installed),
        "installed_version": repo.data.installed_version,
        "latest": latest,
        "update_available": bool(
            repo.data.installed and latest and latest != repo.data.installed_version
        ),
        "domain": getattr(repo.data, "domain", None),
        "category": str(getattr(repo.data, "category", "")),
        "stars": getattr(repo.data, "stargazers_count", 0),
        "topics": list(getattr(repo.data, "topics", []) or []),
        "show_beta": bool(getattr(repo.data, "show_beta", False)),
        "selected_tag": getattr(repo.data, "selected_tag", None),
        "state": getattr(repo, "state", None),
        "default_branch": getattr(repo.data, "default_branch", None),
    }


def _prepare_flow_result_json(
    result: data_entry_flow.FlowResult,
    *,
    include_entry_result: bool = False,
) -> dict[str, object]:

    if result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY:
        data = {
            key: val for key, val in result.items() if key not in ("data", "context")
        }
        if include_entry_result and "result" in result:
            entry: config_entries.ConfigEntry = result["result"]
            data["result"] = entry.as_json_fragment
        return data

    data = dict(result)
    if "data_schema" not in result:
        return data

    schema = result["data_schema"]
    if schema is None:
        data["data_schema"] = []
        data["data_schema_fields"] = []
    else:
        data["data_schema"] = voluptuous_serialize.convert(
            schema, custom_serializer=cv.custom_serializer
        )
        data["data_schema_fields"] = _extract_serialized_schema_fields(
            data["data_schema"]
        )
    return data


def _extract_serialized_schema_fields(
    serialized_schema: object,
) -> list[dict[str, object]]:

    if not isinstance(serialized_schema, list):
        return []

    fields: list[dict[str, object]] = []
    for item in serialized_schema:
        if not isinstance(item, dict):
            continue

        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue

        field: dict[str, object] = {"name": name}
        if "required" in item:
            field["required"] = bool(item["required"])
        if "default" in item:
            field["default"] = item["default"]
        if "type" in item and item["type"] not in (None, ""):
            field["type"] = item["type"]
        if "value" in item:
            field["value"] = item["value"]

        selector = item.get("selector")
        if isinstance(selector, dict) and selector:
            selector_name, selector_config = next(iter(selector.items()))
            field["selector"] = selector_name
            if isinstance(selector_config, dict):
                for key in ("mode", "multiple", "custom_value", "type", "min", "max", "step"):
                    if key in selector_config:
                        field[key] = selector_config[key]
                options = selector_config.get("options")
                if isinstance(options, list):
                    normalized_options: list[object] = []
                    for option in options[:50]:
                        if isinstance(option, dict):
                            normalized_options.append(
                                option.get("value", option.get("label", option))
                            )
                        else:
                            normalized_options.append(option)
                    field["options"] = normalized_options
                    if len(options) > 50:
                        field["options_truncated"] = True

        if "description" in item and item["description"] not in (None, ""):
            field["description"] = item["description"]

        fields.append(field)

    return fields


async def _matching_config_entries_json_fragments(
    hass: HomeAssistant,
    *,
    type_filter: list[str] | None = None,
    domain: str | None = None,
) -> list[object]:

    if domain:
        entries = hass.config_entries.async_entries(domain)
    else:
        entries = hass.config_entries.async_entries()

    if not type_filter:
        return [entry.as_json_fragment for entry in entries]

    integrations: dict[str, Integration] = {}
    domains = {entry.domain for entry in entries}
    for domain_key, integration_or_exc in (
        await async_get_integrations(hass, domains)
    ).items():
        if isinstance(integration_or_exc, Integration):
            integrations[domain_key] = integration_or_exc
        elif not isinstance(integration_or_exc, IntegrationNotFound):
            raise integration_or_exc

    filter_is_not_helper = type_filter != ["helper"]
    filter_set = set(type_filter)
    return [
        entry.as_json_fragment
        for entry in entries
        if (
            (integration := integrations.get(entry.domain))
            and integration.integration_type in filter_set
        )
        or (filter_is_not_helper and entry.domain not in integrations)
    ]


def _normalize_filter_list(value: object) -> list[str] | None:

    if value in (None, "", []):
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return None


def _coerce_params(raw_params: object) -> dict[str, object]:

    if isinstance(raw_params, str):
        try:
            parsed = json.loads(raw_params)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return dict(raw_params) if isinstance(raw_params, dict) else {}


class HAControlTool(llm.Tool):
    name = "HAControl"
    description = """Advanced Home Assistant control for system actions, UI-adjacent operations,
integration inspection, and host shell execution.

Available actions:
- shell: Run a shell command via `/bin/sh -c` asynchronously. params: {command, timeout=30, cwd}.
  Returns stdout/stderr/returncode/elapsed. Default cwd is the HA config directory.
  Example: {"command": "curl -sS https://api.github.com/zen"}
- check_config: Validate the current Home Assistant configuration
- list_integrations: List installed integrations
- get_integration: Get details for one integration (params: {domain: "integration_domain"})
- list_entities_by_integration: List entities for one integration (params: {domain: "integration_domain"})
- reload_integration: Reload one integration (params: {domain: "integration_domain"})
- rename_entry: Rename a config entry (params: {domain: "integration_domain", name: "new_name"})
- navigate: Navigate to a page (path: "/lovelace", "/config", "/developer-tools/service", etc.)
- reload_themes/reload_resources/reload_scripts/reload_automations: Reload related HA resources
- show_toast: Show a toast message (message)
- show_dialog: Show a dialog (title, message)"""
    parameters = vol.Schema(
        {
            vol.Required("action"): str,
            vol.Optional("params", default={}): vol.Any(dict, str),
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        action = tool_input.tool_args.get("action", "")
        params = tool_input.tool_args.get("params", {})

        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}

        if action == "shell":
            return await _run_shell(hass, params)

        if action == "list_integrations":
            entries = hass.config_entries.async_entries()
            integrations = {}
            for entry in entries:
                domain = entry.domain
                integrations.setdefault(domain, {"count": 0, "entries": []})
                integrations[domain]["count"] += 1
                integrations[domain]["entries"].append(
                    {
                        "title": entry.title,
                        "state": entry.state.value
                        if hasattr(entry.state, "value")
                        else str(entry.state),
                        "entry_id": entry.entry_id[:8],
                    }
                )
            return {"success": True, "integrations": integrations, "total": len(entries)}

        if action == "get_integration":
            domain = params.get("domain", "")
            if not domain:
                return {"success": False, "error": "Missing required parameter: domain"}
            entries = [entry for entry in hass.config_entries.async_entries() if entry.domain == domain]
            if not entries:
                return {"success": False, "error": f"Integration not found: {domain}"}
            result = []
            for entry in entries:
                result.append(
                    {
                        "title": entry.title,
                        "domain": entry.domain,
                        "state": entry.state.value
                        if hasattr(entry.state, "value")
                        else str(entry.state),
                        "entry_id": entry.entry_id,
                        "data": {
                            key: "***"
                            if "key" in key.lower()
                            or "token" in key.lower()
                            or "password" in key.lower()
                            else value
                            for key, value in entry.data.items()
                        },
                    }
                )
            return {"success": True, "integration": domain, "entries": result}

        if action == "list_entities_by_integration":
            domain = params.get("domain", "")
            if not domain:
                return {"success": False, "error": "Missing required parameter: domain"}
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(hass)
            entities = []
            for entity in registry.entities.values():
                if entity.platform == domain:
                    state = hass.states.get(entity.entity_id)
                    entities.append(
                        {
                            "entity_id": entity.entity_id,
                            "name": entity.name or entity.original_name,
                            "state": state.state if state else "unknown",
                            "device_class": entity.device_class
                            or entity.original_device_class,
                        }
                    )
            return {
                "success": True,
                "integration": domain,
                "entities": entities,
                "count": len(entities),
            }

        if action == "navigate":
            return {
                "success": False,
                "error": "The frontend bridge has been removed; HAControl no longer supports navigation actions",
            }

        if action in ["reload_themes", "reload_resources", "reload_scripts", "reload_automations"]:
            service_map = {
                "reload_themes": ("frontend", "reload_themes"),
                "reload_resources": ("lovelace", "reload_resources"),
                "reload_scripts": ("script", "reload"),
                "reload_automations": ("automation", "reload"),
            }
            domain, service = service_map[action]
            await hass.services.async_call(domain, service, {}, blocking=True)
            return {"success": True, "message": f"Reloaded {action}"}

        if action == "check_config":
            await hass.services.async_call(
                "homeassistant",
                "check_config",
                {},
                blocking=True,
            )
            return {
                "success": True,
                "message": "Configuration check completed",
            }

        if action == "reload_integration":
            domain = params.get("domain", "")
            if not domain:
                return {"success": False, "error": "You must specify an integration domain (domain)"}
            entries = hass.config_entries.async_entries(domain)
            if not entries:
                return {"success": False, "error": f"Integration not found: {domain}"}

            failed_entries = []
            for entry in entries:
                if not await hass.config_entries.async_reload(entry.entry_id):
                    failed_entries.append(entry.entry_id)

            if failed_entries:
                return {
                    "success": False,
                    "error": f"Failed to reload integration {domain}",
                    "failed_entries": failed_entries,
                }

            return {
                "success": True,
                "message": f"Reloaded integration {domain}",
                "reloaded_entries": len(entries),
            }

        if action == "rename_entry":
            domain = params.get("domain", "")
            new_name = params.get("name", "")
            if not domain or not new_name:
                return {
                    "success": False,
                    "error": "You must specify an integration domain (domain) and a new name (name)",
                }
            entries = hass.config_entries.async_entries(domain)
            if entries:
                for entry in entries:
                    hass.config_entries.async_update_entry(entry, title=new_name)
                return {"success": True, "message": f"Renamed {domain} to {new_name}"}
            return {"success": False, "error": f"Integration not found: {domain}"}

        if action in {"show_toast", "show_dialog"}:
            return {
                "success": False,
                "error": "The frontend bridge has been removed; HAControl no longer supports frontend popup actions",
            }

        return {"success": False, "error": f"Unknown action: {action}"}


class ConfigEntriesTool(llm.Tool):
    name = "ConfigEntries"
    description = """Home Assistant integration and config-entry management tool.

This tool mirrors the Home Assistant config-entry frontend/backend workflow.

Supported actions:
- integration/descriptions
- config_entries/get
- config_entries/get_single
- config_entries/get_supported_subentry_types
- config_entries/update
- config_entries/disable
- config_entries/delete
- config_entries/reload
- config_entries/flow_handlers
- config_entries/flow/progress
- config_entries/flow/init
- config_entries/flow/get
- config_entries/flow/configure
- config_entries/flow/abort
- config_entries/ignore_flow
- config_entries/options/init
- config_entries/options/get
- config_entries/options/configure
- config_entries/options/abort
- config_entries/subentries/list
- config_entries/subentries/update
- config_entries/subentries/delete
- config_entries/subentries/flow/init
- config_entries/subentries/flow/get
- config_entries/subentries/flow/configure
- config_entries/subentries/flow/abort

Use the flow actions to add integrations or continue setup forms.
Use the options actions to change settings for an existing config entry.
Use the subentry flow actions when an installed integration exposes add/configure actions such as "添加对话助手"."""
    parameters = vol.Schema(
        {
            vol.Required("action"): str,
            vol.Optional("params", default={}): vol.Any(dict, str),
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        del llm_context
        action = str(tool_input.tool_args.get("action", "") or "").strip()
        params = _coerce_params(tool_input.tool_args.get("params", {}))

        try:
            if action == "integration/descriptions":
                descriptions = await async_get_integration_descriptions(hass)
                return {
                    "success": True,
                    "message": "Loaded integration descriptions",
                    "descriptions": descriptions,
                }

            if action == "config_entries/get":
                type_filter = _normalize_filter_list(params.get("type_filter"))
                domain = str(params.get("domain", "") or "").strip() or None
                fragments = await _matching_config_entries_json_fragments(
                    hass,
                    type_filter=type_filter,
                    domain=domain,
                )
                return {
                    "success": True,
                    "message": f"Found {len(fragments)} config entries",
                    "config_entries": fragments,
                    "count": len(fragments),
                }

            if action == "config_entries/get_single":
                entry_id = str(params.get("entry_id", "") or "").strip()
                if not entry_id:
                    return {"success": False, "error": "Missing required parameter: entry_id"}
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is None:
                    return {"success": False, "error": "Config entry not found"}
                return {
                    "success": True,
                    "message": f"Loaded config entry {entry.title or entry.domain}",
                    "config_entry": entry.as_json_fragment,
                }

            if action == "config_entries/get_supported_subentry_types":
                entry_id = str(params.get("entry_id", "") or "").strip()
                if not entry_id:
                    return {"success": False, "error": "Missing required parameter: entry_id"}
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is None:
                    return {"success": False, "error": "Config entry not found"}
                handler = await config_entries._async_get_flow_handler(
                    hass, entry.domain, {}
                )
                supported = sorted(
                    handler.async_get_supported_subentry_types(entry).keys()
                )
                return {
                    "success": True,
                    "message": f"Loaded supported subentry types for {entry.title or entry.domain}",
                    "entry_id": entry_id,
                    "subentry_types": supported,
                    "count": len(supported),
                }

            if action == "config_entries/update":
                entry_id = str(params.get("entry_id", "") or "").strip()
                if not entry_id:
                    return {"success": False, "error": "Missing required parameter: entry_id"}
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is None:
                    return {"success": False, "error": "Config entry not found"}

                changes = {
                    key: params[key]
                    for key in ("title", "pref_disable_new_entities", "pref_disable_polling")
                    if key in params
                }
                if not changes:
                    return {"success": False, "error": "No supported update fields provided"}

                old_disable_polling = entry.pref_disable_polling
                hass.config_entries.async_update_entry(entry, **changes)
                result: dict[str, object] = {
                    "success": True,
                    "message": f"Updated config entry {entry.title or entry.domain}",
                    "config_entry": entry.as_json_fragment,
                    "require_restart": False,
                }
                initial_state = entry.state
                if (
                    old_disable_polling != entry.pref_disable_polling
                    and initial_state is config_entries.ConfigEntryState.LOADED
                ):
                    if not await hass.config_entries.async_reload(entry.entry_id):
                        result["require_restart"] = (
                            entry.state is config_entries.ConfigEntryState.FAILED_UNLOAD
                        )
                return result

            if action == "config_entries/disable":
                entry_id = str(params.get("entry_id", "") or "").strip()
                if not entry_id:
                    return {"success": False, "error": "Missing required parameter: entry_id"}
                disabled_by_param = params.get("disabled_by")
                disabled_by = None
                if disabled_by_param is not None:
                    disabled_by = config_entries.ConfigEntryDisabler(str(disabled_by_param))
                try:
                    success = await hass.config_entries.async_set_disabled_by(
                        entry_id, disabled_by
                    )
                except config_entries.OperationNotAllowed:
                    success = False
                except config_entries.UnknownEntry:
                    return {"success": False, "error": "Config entry not found"}
                return {
                    "success": True,
                    "message": (
                        f"Disabled config entry {entry_id}"
                        if disabled_by is not None
                        else f"Enabled config entry {entry_id}"
                    ),
                    "require_restart": not success,
                }

            if action == "config_entries/delete":
                entry_id = str(params.get("entry_id", "") or "").strip()
                if not entry_id:
                    return {"success": False, "error": "Missing required parameter: entry_id"}
                try:
                    result = await hass.config_entries.async_remove(entry_id)
                except config_entries.UnknownEntry:
                    return {"success": False, "error": "Invalid entry specified"}
                return {
                    "success": True,
                    "message": f"Deleted config entry {entry_id}",
                    **result,
                }

            if action == "config_entries/reload":
                entry_id = str(params.get("entry_id", "") or "").strip()
                if not entry_id:
                    return {"success": False, "error": "Missing required parameter: entry_id"}
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is None:
                    return {"success": False, "error": "Invalid entry specified"}
                try:
                    await hass.config_entries.async_reload(entry_id)
                except config_entries.OperationNotAllowed:
                    return {"success": False, "error": "Entry cannot be reloaded"}
                return {
                    "success": True,
                    "message": f"Reloaded config entry {entry.title or entry.domain}",
                    "require_restart": not entry.state.recoverable,
                }

            if action == "config_entries/flow_handlers":
                type_filter = str(params.get("type_filter", "") or "").strip() or None
                handlers = sorted(await async_get_config_flows(hass, type_filter=type_filter))
                return {
                    "success": True,
                    "message": f"Loaded {len(handlers)} flow handlers",
                    "handlers": handlers,
                    "count": len(handlers),
                }

            if action == "config_entries/flow/progress":
                flows = [
                    flow
                    for flow in hass.config_entries.flow.async_progress()
                    if flow["context"]["source"]
                    not in (config_entries.SOURCE_RECONFIGURE, config_entries.SOURCE_USER)
                ]
                return {
                    "success": True,
                    "message": f"Found {len(flows)} in-progress discovered flows",
                    "flows": flows,
                    "count": len(flows),
                }

            if action == "config_entries/flow/init":
                handler = params.get("handler")
                if handler in (None, ""):
                    return {"success": False, "error": "Missing required parameter: handler"}
                context: dict[str, object] = {
                    "show_advanced_options": bool(
                        params.get("show_advanced_options", False)
                    )
                }
                if entry_id := str(params.get("entry_id", "") or "").strip():
                    context["source"] = config_entries.SOURCE_RECONFIGURE
                    context["entry_id"] = entry_id
                else:
                    context["source"] = config_entries.SOURCE_USER
                try:
                    result = await hass.config_entries.flow.async_init(
                        str(handler), context=context
                    )
                except data_entry_flow.UnknownHandler:
                    return {"success": False, "error": "Invalid handler specified"}
                except data_entry_flow.UnknownStep as err:
                    return {"success": False, "error": str(err)}
                prepared = _prepare_flow_result_json(result, include_entry_result=True)
                return {
                    "success": True,
                    "message": f"Initialized config flow for {handler}",
                    **prepared,
                }

            if action in {"config_entries/flow/get", "config_entries/flow/configure"}:
                flow_id = str(params.get("flow_id", "") or "").strip()
                if not flow_id:
                    return {"success": False, "error": "Missing required parameter: flow_id"}
                user_input = params.get("user_input")
                if action == "config_entries/flow/get":
                    user_input = None
                elif user_input is None:
                    user_input = {}
                if isinstance(user_input, str):
                    try:
                        user_input = json.loads(user_input)
                    except Exception:
                        user_input = {}
                if not isinstance(user_input, dict):
                    return {"success": False, "error": "user_input must be an object"}
                try:
                    result = await hass.config_entries.flow.async_configure(
                        flow_id, user_input
                    )
                except data_entry_flow.UnknownFlow:
                    return {"success": False, "error": "Invalid flow specified"}
                except data_entry_flow.InvalidData as err:
                    return {
                        "success": False,
                        "error": "Invalid data",
                        "errors": err.schema_errors,
                    }
                prepared = _prepare_flow_result_json(result, include_entry_result=True)
                return {
                    "success": True,
                    "message": f"Processed config flow {flow_id}",
                    **prepared,
                }

            if action == "config_entries/flow/abort":
                flow_id = str(params.get("flow_id", "") or "").strip()
                if not flow_id:
                    return {"success": False, "error": "Missing required parameter: flow_id"}
                try:
                    hass.config_entries.flow.async_abort(flow_id)
                except data_entry_flow.UnknownFlow:
                    return {"success": False, "error": "Invalid flow specified"}
                return {"success": True, "message": "Flow aborted"}

            if action == "config_entries/ignore_flow":
                flow_id = str(params.get("flow_id", "") or "").strip()
                title = str(params.get("title", "") or "").strip()
                if not flow_id or not title:
                    return {
                        "success": False,
                        "error": "Missing required parameters: flow_id and title",
                    }
                flow = next(
                    (
                        flw
                        for flw in hass.config_entries.flow.async_progress()
                        if flw["flow_id"] == flow_id
                    ),
                    None,
                )
                if flow is None:
                    return {"success": False, "error": "Config flow not found"}
                if "unique_id" not in flow["context"]:
                    return {
                        "success": False,
                        "error": "Specified flow has no unique ID.",
                    }
                context = config_entries.ConfigFlowContext(
                    source=config_entries.SOURCE_IGNORE
                )
                if "discovery_key" in flow["context"]:
                    context["discovery_key"] = flow["context"]["discovery_key"]
                await hass.config_entries.flow.async_init(
                    flow["handler"],
                    context=context,
                    data={
                        "unique_id": flow["context"]["unique_id"],
                        "title": title,
                    },
                )
                return {"success": True, "message": f"Ignored flow {flow_id}"}

            if action == "config_entries/options/init":
                entry_id = str(params.get("entry_id", "") or "").strip()
                if not entry_id:
                    return {"success": False, "error": "Missing required parameter: entry_id"}
                try:
                    result = await hass.config_entries.options.async_init(entry_id)
                except data_entry_flow.UnknownHandler:
                    return {"success": False, "error": "Invalid handler specified"}
                except data_entry_flow.UnknownStep as err:
                    return {"success": False, "error": str(err)}
                prepared = _prepare_flow_result_json(result)
                return {
                    "success": True,
                    "message": f"Initialized options flow for {entry_id}",
                    **prepared,
                }

            if action in {
                "config_entries/options/get",
                "config_entries/options/configure",
            }:
                flow_id = str(params.get("flow_id", "") or "").strip()
                if not flow_id:
                    return {"success": False, "error": "Missing required parameter: flow_id"}
                user_input = params.get("user_input")
                if action == "config_entries/options/get":
                    user_input = None
                elif user_input is None:
                    user_input = {}
                if isinstance(user_input, str):
                    try:
                        user_input = json.loads(user_input)
                    except Exception:
                        user_input = {}
                if not isinstance(user_input, dict):
                    return {"success": False, "error": "user_input must be an object"}
                try:
                    result = await hass.config_entries.options.async_configure(
                        flow_id, user_input
                    )
                except data_entry_flow.UnknownFlow:
                    return {"success": False, "error": "Invalid flow specified"}
                except data_entry_flow.InvalidData as err:
                    return {
                        "success": False,
                        "error": "Invalid data",
                        "errors": err.schema_errors,
                    }
                prepared = _prepare_flow_result_json(result)
                return {
                    "success": True,
                    "message": f"Processed options flow {flow_id}",
                    **prepared,
                }

            if action == "config_entries/options/abort":
                flow_id = str(params.get("flow_id", "") or "").strip()
                if not flow_id:
                    return {"success": False, "error": "Missing required parameter: flow_id"}
                try:
                    hass.config_entries.options.async_abort(flow_id)
                except data_entry_flow.UnknownFlow:
                    return {"success": False, "error": "Invalid flow specified"}
                return {"success": True, "message": "Options flow aborted"}

            if action == "config_entries/subentries/list":
                entry_id = str(params.get("entry_id", "") or "").strip()
                if not entry_id:
                    return {"success": False, "error": "Missing required parameter: entry_id"}
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is None:
                    return {"success": False, "error": "Config entry not found"}
                result = [
                    {
                        "subentry_id": subentry.subentry_id,
                        "subentry_type": subentry.subentry_type,
                        "title": subentry.title,
                        "unique_id": subentry.unique_id,
                        "data": dict(subentry.data),
                    }
                    for subentry in entry.subentries.values()
                ]
                return {
                    "success": True,
                    "message": f"Listed {len(result)} subentries for {entry.title or entry.domain}",
                    "subentries": result,
                    "count": len(result),
                }

            if action == "config_entries/subentries/update":
                entry_id = str(params.get("entry_id", "") or "").strip()
                subentry_id = str(params.get("subentry_id", "") or "").strip()
                if not entry_id or not subentry_id:
                    return {
                        "success": False,
                        "error": "Missing required parameters: entry_id and subentry_id",
                    }
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is None:
                    return {"success": False, "error": "Config entry not found"}
                subentry = entry.subentries.get(subentry_id)
                if subentry is None:
                    return {"success": False, "error": "Config subentry not found"}
                changes = {
                    key: params[key]
                    for key in ("title",)
                    if key in params
                }
                if not changes:
                    return {"success": False, "error": "No supported update fields provided"}
                hass.config_entries.async_update_subentry(entry, subentry, **changes)
                return {
                    "success": True,
                    "message": f"Updated subentry {subentry.title}",
                }

            if action == "config_entries/subentries/delete":
                entry_id = str(params.get("entry_id", "") or "").strip()
                subentry_id = str(params.get("subentry_id", "") or "").strip()
                if not entry_id or not subentry_id:
                    return {
                        "success": False,
                        "error": "Missing required parameters: entry_id and subentry_id",
                    }
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is None:
                    return {"success": False, "error": "Config entry not found"}
                try:
                    hass.config_entries.async_remove_subentry(entry, subentry_id)
                except config_entries.UnknownSubEntry:
                    return {"success": False, "error": "Config subentry not found"}
                return {
                    "success": True,
                    "message": f"Deleted subentry {subentry_id}",
                }

            if action == "config_entries/subentries/flow/init":
                entry_id = str(params.get("entry_id", "") or "").strip()
                subentry_type = str(params.get("subentry_type", "") or "").strip()
                if not entry_id or not subentry_type:
                    return {
                        "success": False,
                        "error": "Missing required parameters: entry_id and subentry_type",
                    }
                context: dict[str, object] = {
                    "show_advanced_options": bool(
                        params.get("show_advanced_options", False)
                    ),
                    "source": config_entries.SOURCE_USER,
                }
                if subentry_id := str(params.get("subentry_id", "") or "").strip():
                    context["source"] = config_entries.SOURCE_RECONFIGURE
                    context["subentry_id"] = subentry_id
                try:
                    result = await hass.config_entries.subentries.async_init(
                        (entry_id, subentry_type), context=context
                    )
                except data_entry_flow.UnknownHandler as err:
                    return {"success": False, "error": str(err)}
                except data_entry_flow.UnknownStep as err:
                    return {"success": False, "error": str(err)}
                prepared = _prepare_flow_result_json(result)
                return {
                    "success": True,
                    "message": f"Initialized subentry flow for {entry_id}:{subentry_type}",
                    **prepared,
                }

            if action in {
                "config_entries/subentries/flow/get",
                "config_entries/subentries/flow/configure",
            }:
                flow_id = str(params.get("flow_id", "") or "").strip()
                if not flow_id:
                    return {"success": False, "error": "Missing required parameter: flow_id"}
                user_input = params.get("user_input")
                if action == "config_entries/subentries/flow/get":
                    user_input = None
                elif user_input is None:
                    user_input = {}
                if isinstance(user_input, str):
                    try:
                        user_input = json.loads(user_input)
                    except Exception:
                        user_input = {}
                if not isinstance(user_input, dict):
                    return {"success": False, "error": "user_input must be an object"}
                try:
                    result = await hass.config_entries.subentries.async_configure(
                        flow_id, user_input
                    )
                except data_entry_flow.UnknownFlow:
                    return {"success": False, "error": "Invalid flow specified"}
                except data_entry_flow.InvalidData as err:
                    return {
                        "success": False,
                        "error": "Invalid data",
                        "errors": err.schema_errors,
                    }
                prepared = _prepare_flow_result_json(result)
                return {
                    "success": True,
                    "message": f"Processed subentry flow {flow_id}",
                    **prepared,
                }

            if action == "config_entries/subentries/flow/abort":
                flow_id = str(params.get("flow_id", "") or "").strip()
                if not flow_id:
                    return {"success": False, "error": "Missing required parameter: flow_id"}
                try:
                    hass.config_entries.subentries.async_abort(flow_id)
                except data_entry_flow.UnknownFlow:
                    return {"success": False, "error": "Invalid flow specified"}
                return {"success": True, "message": "Subentry flow aborted"}

            return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as err:
            return {"success": False, "error": str(err)}


class HACSTool(llm.Tool):
    name = "HACS"
    description = """HACS store tool.

Available actions:
- action=list: List HACS repositories
- action=search: Search the local HACS cache
- action=github_search: Search GitHub remotely for discovery
- action=info: Fetch repository details and README
- action=install / update: Install or update a repository using repository/source/query
- action=uninstall: Uninstall a repository
- action=remove: Remove a repository from the HACS registry
- action=manage / edit: View or update repository settings (version/show_beta/state)
- action=open_add_integration: Open the HA add-integration flow and search

Supported params:
- repository: owner/repo or URL
- source: any repository source URL
- query: search term or repository keyword
- category: integration/lovelace/plugin/theme/appdaemon/python_script/template
- params: management params such as version/show_beta/state"""
    parameters = vol.Schema(
        {
            vol.Required("action"): str,
            vol.Optional("repository", default=""): str,
            vol.Optional("source", default=""): str,
            vol.Optional("query", default=""): str,
            vol.Optional("category", default="integration"): str,
            vol.Optional("params", default={}): vol.Any(dict, str),
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        action = tool_input.tool_args.get("action", "")
        repository = tool_input.tool_args.get("repository", "")
        source = tool_input.tool_args.get("source", "")
        query = tool_input.tool_args.get("query", "")
        category = tool_input.tool_args.get("category", "integration")
        params = tool_input.tool_args.get("params", {})

        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}

        normalized_source = _normalize_repo_source(source or repository)
        repository = normalized_source["repository"]

        try:
            hacs_data = hass.data.get("hacs")
            if not hacs_data:
                return {"success": False, "error": "HACS is not installed"}

            if action == "list":
                repos = []
                for repo in hacs_data.repositories.list_all:
                    repos.append(_serialize_hacs_repo(repo))
                return {"success": True, "total": len(repos), "repositories": repos}

            if action == "search":
                if not query:
                    return {"success": False, "error": "A search query is required (query)"}
                results = []
                query_lower = query.lower()
                for repo in hacs_data.repositories.list_all:
                    if (
                        query_lower in repo.data.name.lower()
                        or query_lower in (repo.data.description or "").lower()
                        or query_lower in " ".join(repo.data.topics or []).lower()
                    ):
                        results.append(
                            {
                                "name": repo.data.name,
                                "full_name": repo.data.full_name,
                                "description": repo.data.description[:200]
                                if repo.data.description
                                else "",
                                "installed": repo.data.installed,
                                "stars": repo.data.stargazers_count,
                                "domain": getattr(repo.data, "domain", None),
                                "category": str(getattr(repo.data, "category", "")),
                            }
                        )
                        if len(results) >= 20:
                            break
                return {"success": True, "results": results}

            if action == "github_search":
                if not query:
                    return {"success": False, "error": "A search query is required (query)"}
                return {"success": True, "results": await _search_github_repositories(query)}

            if action == "info":
                repo = hacs_data.repositories.get_by_full_name(repository) if repository else None
                if repo is not None:
                    info = _serialize_hacs_repo(repo)
                    readme = ""
                    try:
                        readme = await repo.get_documentation()
                    except Exception:
                        readme = ""
                    info["readme"] = readme[:2000] if readme else ""
                    return {"success": True, **info}

                if not repository or "/" not in repository:
                    return {
                        "success": False,
                        "error": "Missing a recognizable repository/source; unable to fetch remote details",
                        "normalized_source": normalized_source,
                    }

                async with aiohttp.ClientSession() as session:
                    async with session.get(f"https://api.github.com/repos/{repository}") as resp:
                        if resp.status != 200:
                            return {"success": False, "error": f"GitHub API error: {resp.status}"}
                        repo_data = await resp.json()

                    async with session.get(
                        f"https://api.github.com/repos/{repository}/readme",
                        headers={"Accept": "application/vnd.github.raw"},
                    ) as resp:
                        readme = ""
                        if resp.status == 200:
                            readme_raw = await resp.text()
                            readme = readme_raw[:2000] if len(readme_raw) > 2000 else readme_raw

                return {
                    "success": True,
                    "name": repo_data.get("name"),
                    "full_name": repo_data.get("full_name"),
                    "description": repo_data.get("description"),
                    "stars": repo_data.get("stargazers_count"),
                    "topics": repo_data.get("topics", []),
                    "readme": readme,
                    "normalized_source": normalized_source,
                }

            if action in {"install", "update"}:
                from custom_components.hacs.enums import HacsCategory

                category_map = {
                    "integration": HacsCategory.INTEGRATION,
                    "lovelace": HacsCategory.LOVELACE,
                    "plugin": HacsCategory.PLUGIN,
                    "theme": HacsCategory.THEME,
                    "appdaemon": HacsCategory.APPDAEMON,
                    "python_script": HacsCategory.PYTHON_SCRIPT,
                    "template": HacsCategory.TEMPLATE,
                }
                hacs_category = category_map.get(category, HacsCategory.INTEGRATION)

                repo = hacs_data.repositories.get_by_full_name(repository) if repository else None
                target_repository = repository

                if not target_repository and query:
                    repo = _find_repo_by_query(hacs_data, query)
                    if repo is not None:
                        target_repository = repo.data.full_name
                    else:
                        remote_results = await _search_github_repositories(query)
                        if remote_results:
                            target_repository = str(remote_results[0]["full_name"])

                if not target_repository or "/" not in target_repository:
                    return {
                        "success": False,
                        "error": "Unable to resolve an installable repository from repository/source/query",
                        "normalized_source": normalized_source,
                    }

                existing = repo or hacs_data.repositories.get_by_full_name(target_repository)
                if existing and existing.data.installed:
                    await existing.async_download_repository(ref=params.get("version"))
                    return {
                        "success": True,
                        "message": f"Updated {existing.data.full_name}",
                        "repository": _serialize_hacs_repo(existing),
                    }

                if existing is None:
                    await hacs_data.async_register_repository(target_repository, hacs_category)
                repo = hacs_data.repositories.get_by_full_name(target_repository)
                if repo:
                    await repo.async_download_repository(ref=params.get("version"))
                    domain = (
                        repo.data.domain
                        or repo.data.name.replace("-", "_").replace(" ", "_").lower()
                    )
                    return {
                        "success": True,
                        "message": f"Installed {target_repository}",
                        "domain": domain,
                        "repository": _serialize_hacs_repo(repo),
                        "next_action": f"You can now search for '{domain}' in the Home Assistant integrations page to finish setup.",
                    }
                return {"success": False, "error": f"Registration failed: {target_repository}"}

            if action == "uninstall":
                repo = hacs_data.repositories.get_by_full_name(repository) if repository else None
                if repo is None and query:
                    repo = _find_repo_by_query(hacs_data, query)
                if repo is None:
                    return {"success": False, "error": "Could not find a repository to uninstall"}
                await repo.uninstall()
                return {
                    "success": True,
                    "message": f"Uninstalled {repo.data.full_name}",
                    "repository": _serialize_hacs_repo(repo),
                }

            if action == "remove":
                repo = hacs_data.repositories.get_by_full_name(repository) if repository else None
                if repo is None and query:
                    repo = _find_repo_by_query(hacs_data, query)
                if repo is None:
                    return {"success": False, "error": "Could not find a repository to remove"}
                repo.remove()
                data_store = getattr(hacs_data, "data", None)
                if data_store is not None and hasattr(data_store, "async_write"):
                    await data_store.async_write()
                return {"success": True, "message": f"Removed {repo.data.full_name} from the HACS registry"}

            if action in {"manage", "edit"}:
                repo = hacs_data.repositories.get_by_full_name(repository) if repository else None
                if repo is None and query:
                    repo = _find_repo_by_query(hacs_data, query)
                if repo is None:
                    return {"success": False, "error": "Could not find a repository to manage"}

                updated_fields: dict[str, object] = {}
                if "state" in params:
                    repo.state = params["state"]
                    updated_fields["state"] = repo.state
                if "show_beta" in params:
                    repo.data.show_beta = bool(params["show_beta"])
                    updated_fields["show_beta"] = repo.data.show_beta
                if "version" in params:
                    requested_version = str(params["version"])
                    if requested_version == str(getattr(repo.data, "default_branch", "")):
                        repo.data.selected_tag = None
                    else:
                        repo.data.selected_tag = requested_version
                    updated_fields["selected_tag"] = repo.data.selected_tag
                if updated_fields:
                    await repo.update_repository(force=True)
                    repo.state = None
                return {
                    "success": True,
                    "message": "Repository state updated" if updated_fields else "Repository details",
                    "updated_fields": updated_fields,
                    "repository": _serialize_hacs_repo(repo),
                }

            if action == "open_add_integration":
                search_query = query or ""
                return {
                    "success": True,
                    "message": "Open Home Assistant's integrations page, choose Add Integration, and search as needed.",
                    "query": search_query,
                }

            return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as err:
            return {"success": False, "error": str(err)}


__all__ = [
    "ConfigEntriesTool",
    "HAControlTool",
    "HACSTool",
]
