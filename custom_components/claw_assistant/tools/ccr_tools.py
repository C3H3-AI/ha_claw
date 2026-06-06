from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

_DEFAULT_MAX_CHARS = 8000


class RetrieveOriginalTool(llm.Tool):
    name = "RetrieveOriginal"
    description = (
        "Retrieve the full original content that context compression replaced "
        "with a compact summary. When you see a [CCR:<id>] handle in a tool "
        "result, call this with that id to get the full output back. Large "
        "originals are paginated — use offset + max_chars to read more. "
        "Params: id(required), offset(default 0), max_chars(default 8000)."
    )
    parameters = vol.Schema(
        {
            vol.Required("id"): str,
            vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0)),
            vol.Optional("max_chars", default=_DEFAULT_MAX_CHARS): vol.All(
                int, vol.Range(min=1)
            ),
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        from ..runtime.llm.ccr_store import get_ccr_store

        args = tool_input.tool_args
        cid = str(args.get("id", "")).strip()
        if cid.startswith("[CCR:") and cid.endswith("]"):
            cid = cid[5:-1].strip()
        if not cid:
            return {"success": False, "error": "id is required"}

        store = get_ccr_store()
        # get() may fall back to a disk read, so offload it off the event loop.
        content = await hass.async_add_executor_job(store.get, cid)
        if content is None:
            return {
                "success": False,
                "error": (
                    f"No cached original for id '{cid}'. It may have been "
                    "evicted (the CCR cache is bounded and keeps recent items)."
                ),
            }

        offset = int(args.get("offset", 0) or 0)
        max_chars = int(args.get("max_chars", _DEFAULT_MAX_CHARS) or _DEFAULT_MAX_CHARS)
        total = len(content)
        chunk = content[offset : offset + max_chars]
        next_offset = offset + len(chunk)
        info = store.info(cid) or {}
        return {
            "success": True,
            "id": cid,
            "tool_name": info.get("tool_name", ""),
            "total_chars": total,
            "offset": offset,
            "returned_chars": len(chunk),
            "has_more": next_offset < total,
            "next_offset": next_offset if next_offset < total else None,
            "content": chunk,
        }
