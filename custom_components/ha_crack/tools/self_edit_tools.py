

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

from ..runtime.ha_guide_store import (
    async_delete_runtime_guide_doc,
    async_upsert_runtime_guide_doc,
    get_homeassistant_guide_doc,
    list_homeassistant_guide_docs,
)
from ..runtime.self_edit import (
    async_apply_proposal,
    async_discard_proposal,
    async_list_proposals,
    async_read_changelog,
    async_read_proposal,
    async_stage_proposal,
)
from ..runtime.skill_store import (
    async_delete_skill,
    async_install_skill,
    get_installed_skill,
    list_installed_skills,
)

_LOGGER = logging.getLogger(__name__)







class DeleteSkillTool(llm.Tool):
    name = "DeleteSkill"
    description = (
        "Delete one installed Markdown skill. Every deletion is audited in "
        "changelog.jsonl. Params: name (skill slug or file stem), reason (optional)"
    )
    parameters = vol.Schema(
        {
            vol.Required("name"): str,
            vol.Optional("reason", default=""): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args = tool_input.tool_args
        name = (args.get("name") or "").strip()
        reason = (args.get("reason") or "").strip()
        if not name:
            return {"success": False, "error": "name is required"}
        try:
            path = await async_delete_skill(hass, name, reason=reason)
        except FileNotFoundError as err:
            return {"success": False, "error": str(err)}
        except ValueError as err:
            return {"success": False, "error": str(err)}
        return {
            "success": True,
            "deleted": path.stem,
            "path": str(path),
            "message": f"Skill deleted: {path.stem}",
        }







class UpsertGuideDocTool(llm.Tool):
    name = "UpsertGuideDoc"
    description = (
        "Create or overwrite one runtime Home Assistant guide Markdown doc. "
        "Only writes under data/homeassistant_guide/runtime/. "
        "Params: relative_path (e.g. '30_safety_and_workflows.md'), markdown, reason (optional)"
    )
    parameters = vol.Schema(
        {
            vol.Required("relative_path"): str,
            vol.Required("markdown"): str,
            vol.Optional("reason", default=""): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args = tool_input.tool_args
        relative_path = (args.get("relative_path") or "").strip()
        markdown = args.get("markdown") or ""
        reason = (args.get("reason") or "").strip()
        try:
            path = await async_upsert_runtime_guide_doc(
                hass, relative_path, markdown, reason=reason
            )
        except ValueError as err:
            return {"success": False, "error": str(err)}
        return {
            "success": True,
            "path": str(path),
            "relative_path": relative_path,
            "message": f"Guide doc upserted: runtime/{relative_path}",
        }


class DeleteGuideDocTool(llm.Tool):
    name = "DeleteGuideDoc"
    description = (
        "Delete one runtime Home Assistant guide Markdown doc. "
        "Cannot remove anything under source/ (those are pristine originals). "
        "Params: relative_path, reason (optional)"
    )
    parameters = vol.Schema(
        {
            vol.Required("relative_path"): str,
            vol.Optional("reason", default=""): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args = tool_input.tool_args
        relative_path = (args.get("relative_path") or "").strip()
        reason = (args.get("reason") or "").strip()
        try:
            path = await async_delete_runtime_guide_doc(
                hass, relative_path, reason=reason
            )
        except FileNotFoundError as err:
            return {"success": False, "error": str(err)}
        except ValueError as err:
            return {"success": False, "error": str(err)}
        return {
            "success": True,
            "path": str(path),
            "relative_path": relative_path,
            "message": f"Guide doc deleted: runtime/{relative_path}",
        }







class GetSelfChangelogTool(llm.Tool):
    name = "GetSelfChangelog"
    description = (
        "Read the append-only self-edit audit log. Use this to answer "
        "'what did I change last time?'. Params: limit (default 20), "
        "target_type (optional: skill|guide)"
    )
    parameters = vol.Schema(
        {
            vol.Optional("limit", default=20): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=200)
            ),
            vol.Optional("target_type", default=""): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args = tool_input.tool_args
        limit = int(args.get("limit") or 20)
        target_type_raw = (args.get("target_type") or "").strip().lower()
        target_type = target_type_raw or None
        entries = await async_read_changelog(
            hass, limit=limit, target_type=target_type
        )
        return {
            "success": True,
            "count": len(entries),
            "target_type_filter": target_type,
            "entries": entries,
        }







class ProposeSelfEditTool(llm.Tool):
    name = "ProposeSelfEdit"
    description = (
        "Stage a self-edit proposal for human approval. Use this during "
        "reflection instead of editing directly. "
        "Params: target_type (skill|guide), target_id "
        "(skill slug OR guide relative_path), action (create|update|delete), "
        "markdown (required for create/update), reason"
    )
    parameters = vol.Schema(
        {
            vol.Required("target_type"): str,
            vol.Required("target_id"): str,
            vol.Required("action"): str,
            vol.Optional("markdown", default=""): str,
            vol.Required("reason"): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args = tool_input.tool_args
        target_type = (args.get("target_type") or "").strip().lower()
        target_id = (args.get("target_id") or "").strip()
        action = (args.get("action") or "").strip().lower()
        markdown = args.get("markdown") or ""
        reason = (args.get("reason") or "").strip()
        try:
            proposal = await async_stage_proposal(
                hass,
                target_type=target_type,
                target_id=target_id,
                action=action,
                proposed_markdown=markdown,
                reason=reason,
                slug_hint=f"{target_type}-{target_id}-{action}",
            )
        except ValueError as err:
            return {"success": False, "error": str(err)}
        return {
            "success": True,
            "message": (
                f"Proposal staged for {target_type}/{target_id} ({action}). "
                f"Awaiting human approval via ApplyProposal."
            ),
            **proposal,
        }


class ListProposalsTool(llm.Tool):
    name = "ListProposals"
    description = "List pending self-edit proposals. No parameters."
    parameters = vol.Schema({})

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        proposals = await async_list_proposals(hass)
        return {
            "success": True,
            "count": len(proposals),
            "proposals": proposals,
        }


class GetProposalTool(llm.Tool):
    name = "GetProposal"
    description = "Read the full body of one pending proposal. Params: slug"
    parameters = vol.Schema({vol.Required("slug"): str})

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        slug = (tool_input.tool_args.get("slug") or "").strip()
        try:
            proposal = await async_read_proposal(hass, slug)
        except FileNotFoundError as err:
            return {"success": False, "error": str(err)}
        return {"success": True, **proposal}


class DiscardProposalTool(llm.Tool):
    name = "DiscardProposal"
    description = (
        "Remove one pending proposal without applying it. "
        "Params: slug"
    )
    parameters = vol.Schema({vol.Required("slug"): str})

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        slug = (tool_input.tool_args.get("slug") or "").strip()
        removed = await async_discard_proposal(hass, slug)
        if not removed:
            return {"success": False, "error": f"Proposal not found: {slug}"}
        return {"success": True, "slug": slug, "discarded": True}


async def _apply_skill_proposal(
    hass: HomeAssistant, frontmatter: dict[str, Any], body: str
) -> dict[str, Any]:
    action = str(frontmatter.get("action") or "").lower()
    target_id = str(frontmatter.get("target_id") or "").strip()
    approver = str(frontmatter.get("approved_by") or "human")
    reason = f"approved proposal: {frontmatter.get('reason', '')}".strip()
    if not target_id:
        raise ValueError("target_id is missing from proposal frontmatter")
    if action in {"create", "update"}:
        path = await async_install_skill(
            hass,
            target_id,
            body,
            overwrite=True,
            actor=f"approved_by:{approver}",
            reason=reason,
        )
        return {"action": action, "path": str(path)}
    if action == "delete":
        path = await async_delete_skill(
            hass, target_id, actor=f"approved_by:{approver}", reason=reason
        )
        return {"action": "delete", "path": str(path)}
    raise ValueError(f"Unsupported skill action: {action!r}")


async def _apply_guide_proposal(
    hass: HomeAssistant, frontmatter: dict[str, Any], body: str
) -> dict[str, Any]:
    action = str(frontmatter.get("action") or "").lower()
    target_id = str(frontmatter.get("target_id") or "").strip()
    approver = str(frontmatter.get("approved_by") or "human")
    reason = f"approved proposal: {frontmatter.get('reason', '')}".strip()
    if not target_id:
        raise ValueError("target_id is missing from proposal frontmatter")



    relative_path = target_id.split("/", 1)[1] if "/" in target_id else target_id

    if action in {"create", "update"}:
        path = await async_upsert_runtime_guide_doc(
            hass,
            relative_path,
            body,
            actor=f"approved_by:{approver}",
            reason=reason,
        )
        return {"action": action, "path": str(path)}
    if action == "delete":
        path = await async_delete_runtime_guide_doc(
            hass,
            relative_path,
            actor=f"approved_by:{approver}",
            reason=reason,
        )
        return {"action": "delete", "path": str(path)}
    raise ValueError(f"Unsupported guide action: {action!r}")


_EXECUTORS = {
    "skill": _apply_skill_proposal,
    "guide": _apply_guide_proposal,
}


class ApplyProposalTool(llm.Tool):
    name = "ApplyProposal"
    description = (
        "Approve and apply one pending proposal. Mutations flow through the "
        "regular Upsert/Delete helpers so the changelog records the approver. "
        "Params: slug, approved_by (default 'human')"
    )
    parameters = vol.Schema(
        {
            vol.Required("slug"): str,
            vol.Optional("approved_by", default="human"): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args = tool_input.tool_args
        slug = (args.get("slug") or "").strip()
        approved_by = (args.get("approved_by") or "human").strip() or "human"
        try:
            result = await async_apply_proposal(
                hass, slug, _EXECUTORS, approved_by=approved_by
            )
        except FileNotFoundError as err:
            return {"success": False, "error": str(err)}
        except ValueError as err:
            return {"success": False, "error": str(err)}
        return {"success": True, **result}







class ReviewSelfSkillsTool(llm.Tool):
    name = "ReviewSelfSkills"
    description = (
        "Return a compact self-critique briefing: installed skills summary, "
        "available guide docs, and the most recent self-edit changelog "
        "entries. Use this at the end of a conversation (or when a user "
        "reports repeated failures) to decide whether any skill needs "
        "updating, deleting, or creating, then call ProposeSelfEdit for "
        "each proposed change (do NOT edit skills/guide directly during "
        "reflection). Params: limit (default 10)"
    )
    parameters = vol.Schema(
        {
            vol.Optional("limit", default=10): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=100)
            ),
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        limit = int(tool_input.tool_args.get("limit") or 10)
        skills = list_installed_skills()
        guide_docs = list_homeassistant_guide_docs()
        recent_changes = await async_read_changelog(hass, limit=limit)
        pending = await async_list_proposals(hass)
        return {
            "success": True,
            "instructions": (
                "Review installed skills and recent self-edits. If a skill is "
                "obsolete, misleading, or missing, stage a proposal with "
                "ProposeSelfEdit (never edit the skill/guide directly in this "
                "reflection turn). A human will approve or discard each "
                "proposal."
            ),
            "installed_skills": [
                {"slug": s.get("slug"), "title": s.get("title"), "description": s.get("description")}
                for s in skills
            ],
            "guide_runtime_docs": [
                {"path": g.get("path"), "title": g.get("title")}
                for g in guide_docs
                if g.get("collection") == "runtime"
            ],
            "recent_changes": recent_changes,
            "pending_proposals": pending,
        }
