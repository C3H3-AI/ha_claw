

from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol

from homeassistant.helpers import llm

from ..runtime.utils.route_hints import build_route_envelope, build_route_hint
from ..runtime.storage.skill_store import filter_installed_skills

_BUILTIN_SKILL_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "MemorySkill",
        "description": "Store durable preferences, facts, and user-specific context.",
        "use_for": ["durable preference", "long-term fact", "stable user profile"],
        "avoid_for": ["reminder", "scheduled follow-up", "one-off transient note"],
        "route_to": "HeartbeatSkill for reminders and follow-up tasks",
        "next_tool": "ConversationMemory",
        "next_action": "save",
    },
    {
        "name": "HeartbeatSkill",
        "description": "Manage reminders, follow-up tasks, and recurring checks.",
        "use_for": ["reminder", "follow-up task", "scheduled check-in"],
        "avoid_for": ["durable preference", "permanent profile fact"],
        "route_to": "Use MemorySkill for durable facts that should persist",
        "next_tool": "HeartbeatManager",
        "next_action": "upsert",
    },
    {
        "name": "SearchSkill",
        "description": "Fetch real-time public information from the web when local context is insufficient.",
        "use_for": ["latest news", "current weather", "public web lookup"],
        "avoid_for": ["local entity state", "durable memory"],
        "route_to": "Use LiveContextSkill for Home Assistant state and SearchSkill for the open web",
        "next_tool": "WebSearch",
        "next_action": "search",
    },
    {
        "name": "LiveContextSkill",
        "description": "Read current Home Assistant entities, states, and device context.",
        "use_for": ["current entity state", "available device list", "real-time HA context"],
        "avoid_for": ["web research", "durable preference"],
        "route_to": "Use SearchSkill for public sites and MemorySkill for durable notes",
        "next_tool": "GetLiveContext",
        "next_action": "query",
    },
    {
        "name": "ConversationHistorySkill",
        "description": "Inspect the current conversation transcript before asking follow-up questions.",
        "use_for": ["recent turn recall", "conversation grounding", "what was just said"],
        "avoid_for": ["durable storage", "scheduled reminders"],
        "route_to": "Use MemorySkill for long-term storage and HeartbeatSkill for future work",
        "next_tool": "GetConversationHistory",
        "next_action": "list",
    },
    {
        "name": "InstalledSkillSkill",
        "description": "Discover and read installed markdown skills before executing their procedures.",
        "use_for": ["installed workflow lookup", "skill discovery", "markdown skill reading"],
        "avoid_for": ["blind execution without reading the skill"],
        "route_to": "Read the installed markdown first, then follow its procedure",
        "next_tool": "GetInstalledSkill",
        "next_action": "get",
    },
    {
        "name": "WorkspaceSkill",
        "description": "Read or update runtime workspace documents such as MEMORY, HEARTBEAT, and TOOLS.",
        "use_for": ["workspace doc lookup", "runtime notes", "working memory docs"],
        "avoid_for": ["web research", "device control"],
        "route_to": "Use MemorySkill or HeartbeatSkill when the request is data-oriented",
        "next_tool": "GetWorkspaceDoc",
        "next_action": "read",
    },
    {
        "name": "HomeAssistantGuideSkill",
        "description": "Consult the bundled Home Assistant development and runtime guide.",
        "use_for": ["HA workflow guidance", "integration best practice", "runtime playbook"],
        "avoid_for": ["real-time entity state", "web news"],
        "route_to": "Use LiveContextSkill for state and SearchSkill for public web info",
        "next_tool": "HomeAssistantGuide",
        "next_action": "search",
    },
    {
        "name": "SystemIndexSkill",
        "description": "Get a structural overview of areas, domains, people, automations, and scripts.",
        "use_for": ["system overview", "area inventory", "domain index"],
        "avoid_for": ["precise live state", "durable storage"],
        "route_to": "Use LiveContextSkill once you know which entities to inspect",
        "next_tool": "GetSystemIndex",
        "next_action": "list",
    },
    {
        "name": "ConfigFileSkill",
        "description": "Inspect or stage changes inside the Home Assistant config directory.",
        "use_for": ["config file read", "staged config edit", "workspace filesystem task"],
        "avoid_for": ["blind destructive change", "public web research"],
        "route_to": "Use validation tools before applying config changes",
        "next_tool": "ConfigFile",
        "next_action": "list",
    },
    {
        "name": "AgentHandoffSkill",
        "description": "Hand the turn to another configured agent when the current agent should defer.",
        "use_for": ["agent delegation", "switch active assistant", "cross-agent handoff"],
        "avoid_for": ["simple local action", "memory storage"],
        "route_to": "Use only when a different agent should answer the turn",
        "next_tool": "AgentHandoff",
        "next_action": "request",
    },
)


def _normalize_match_field(value: object) -> str:

    if isinstance(value, str):
        return value.lower()
    if isinstance(value, dict):
        return " ".join(_normalize_match_field(item) for item in value.values()).strip()
    if isinstance(value, (list, tuple, set)):
        return " ".join(_normalize_match_field(item) for item in value).strip()
    return str(value).lower()


def _build_skill_route_entry(
    *,
    name: str,
    description: str,
    use_for: list[str],
    avoid_for: list[str],
    route_to: str,
    next_tool: str,
    next_action: str,
) -> dict[str, Any]:

    route_hint = build_route_hint(
        "skill_route",
        next_tool,
        next_action,
        recommendation=route_to,
    )
    entry = {
        "name": name,
        "description": description,
        "use_for": list(use_for),
        "avoid_for": list(avoid_for),
        "route_to": route_to,
        **build_route_envelope("skill_route", next_tool, next_action),
        "route_hint": route_hint,
    }
    entry["match_fields"] = [
        field
        for field in dict.fromkeys(
            value
            for value in (
                _normalize_match_field(name),
                _normalize_match_field(description),
                *(_normalize_match_field(item) for item in use_for),
                *(_normalize_match_field(item) for item in avoid_for),
                _normalize_match_field(route_to),
                _normalize_match_field(entry["route_kind"]),
                _normalize_match_field(entry["next_action"]),
                _normalize_match_field(route_hint),
            )
            if value
        )
    ]
    return entry


def _builtin_skill_catalog() -> list[dict[str, Any]]:

    return [
        _build_skill_route_entry(
            name=str(spec["name"]),
            description=str(spec["description"]),
            use_for=list(spec["use_for"]),
            avoid_for=list(spec["avoid_for"]),
            route_to=str(spec["route_to"]),
            next_tool=str(spec["next_tool"]),
            next_action=str(spec["next_action"]),
        )
        for spec in _BUILTIN_SKILL_SPECS
    ]


def _skill_matches_keyword(item: dict[str, Any], keyword: str) -> bool:

    normalized_keyword = keyword.strip().lower()
    if not normalized_keyword:
        return True
    return any(
        normalized_keyword in _normalize_match_field(value)
        for value in (
            item.get("name", ""),
            item.get("description", ""),
            item.get("use_for", []),
            item.get("avoid_for", []),
            item.get("route_to", ""),
            item.get("route_kind", ""),
            item.get("next_action", {}),
            item.get("route_hint", {}),
            item.get("match_fields", []),
        )
    )


def _summarize_native_intent_response(result: object) -> str:

    matched_states = getattr(result, "matched_states", []) or []
    if matched_states:
        state = matched_states[0]
        name = getattr(state, "name", "Entity")
        entity_state = getattr(state, "state", "unknown")
        return f"{name} is currently {entity_state}"

    success_results = getattr(result, "success_results", []) or []
    if success_results:
        names = [
            getattr(item, "name", "").strip()
            for item in success_results
            if getattr(item, "name", "").strip()
        ]
        if names:
            return f"Completed: {', '.join(names)}"

    error_code = getattr(result, "error_code", None)
    if error_code not in (None, ""):
        return f"Intent error: {error_code}"
    return "Intent completed"


class GetSkillIndexTool(llm.Tool):


    name = "GetSkillIndex"
    description = (
        "List builtin routing skills and installed markdown skills. "
        "Params: keyword(optional)"
    )
    parameters = vol.Schema({vol.Optional("keyword", default=""): str})

    async def async_call(self, hass, tool_input: llm.ToolInput, llm_context) -> dict[str, Any]:
        del hass
        del llm_context

        keyword = str(tool_input.tool_args.get("keyword", "")).strip()
        builtin_skills = _builtin_skill_catalog()
        installed_skills = filter_installed_skills(keyword)

        if keyword:
            builtin_skills = [
                item for item in builtin_skills if _skill_matches_keyword(item, keyword)
            ]

        return {
            "builtin_skills": deepcopy(builtin_skills),
            "installed_markdown_skills": deepcopy(installed_skills),
        }


def build_skill_tool_list() -> list[llm.Tool]:

    return [GetSkillIndexTool()]
