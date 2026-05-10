from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

_LOGGER = logging.getLogger(__name__)

_FRONTEND_SNAPSHOT_KEY = "claw_frontend_snapshot"
_FRONTEND_EXEC_QUEUE = "claw_frontend_exec_queue"
_FRONTEND_EXEC_RESULTS = "claw_frontend_exec_results"
_FRONTEND_TEXT_CACHE = "claw_frontend_text_cache"

_SNAPSHOT_TTL = 5


def _domain_data(hass: HomeAssistant) -> dict:
    return hass.data.setdefault("claw_assistant", {})


def store_frontend_snapshot(hass: HomeAssistant, snapshot: dict) -> None:
    _domain_data(hass)[_FRONTEND_SNAPSHOT_KEY] = {
        "ts": time.time(),
        "data": snapshot,
    }


def get_frontend_snapshot(hass: HomeAssistant) -> dict | None:
    entry = _domain_data(hass).get(_FRONTEND_SNAPSHOT_KEY)
    if not entry:
        return None
    if time.time() - entry["ts"] > _SNAPSHOT_TTL:
        return None
    return entry["data"]


def queue_frontend_exec(hass: HomeAssistant, exec_id: str, js_code: str) -> None:
    q = _domain_data(hass).setdefault(_FRONTEND_EXEC_QUEUE, [])
    q.append({"id": exec_id, "code": js_code})
    hass.bus.async_fire("claw_frontend_exec", {"id": exec_id, "code": js_code})


def store_frontend_exec_result(hass: HomeAssistant, exec_id: str, result: Any) -> None:
    results = _domain_data(hass).setdefault(_FRONTEND_EXEC_RESULTS, {})
    results[exec_id] = {"ts": time.time(), "result": result}


def store_frontend_text_cache(hass: HomeAssistant, source: str, value: Any) -> None:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    if not text:
        return
    cache = _domain_data(hass).setdefault(_FRONTEND_TEXT_CACHE, [])
    cache.append({"ts": time.time(), "source": source, "text": text[:200000]})
    del cache[:-10]


def search_frontend_text_cache(hass: HomeAssistant, query: str, limit: int = 5000) -> dict:
    cache = _domain_data(hass).get(_FRONTEND_TEXT_CACHE, [])
    q = query.casefold()
    remaining = limit
    matches = []
    for entry in reversed(cache):
        text = entry.get("text", "")
        hay = text.casefold()
        start = 0
        while remaining > 0:
            idx = hay.find(q, start)
            if idx < 0:
                break
            radius = min(700, max(120, remaining // 2))
            a = max(0, idx - radius)
            b = min(len(text), idx + len(query) + radius)
            snippet = text[a:b]
            matches.append({
                "source": entry.get("source", ""),
                "offset": idx,
                "text": snippet,
            })
            remaining -= len(snippet)
            start = idx + len(query)
    return {
        "query": query,
        "matches": matches,
        "truncated": remaining <= 0,
        "cache_entries": len(cache),
    }


def pop_frontend_exec_result(hass: HomeAssistant, exec_id: str, timeout: float = 10.0) -> Any:
    results = _domain_data(hass).setdefault(_FRONTEND_EXEC_RESULTS, {})
    if exec_id in results:
        return results.pop(exec_id)["result"]
    return None


async def async_wait_frontend_exec_result(hass: HomeAssistant, exec_id: str, timeout: float = 15.0) -> Any:
    results = _domain_data(hass).setdefault(_FRONTEND_EXEC_RESULTS, {})
    deadline = time.time() + timeout
    while time.time() < deadline:
        if exec_id in results:
            return results.pop(exec_id)["result"]
        await asyncio.sleep(0.3)
    return {"error": "timeout", "message": f"Frontend did not respond within {timeout}s"}


class FrontendInspectTool(llm.Tool):
    name = "FrontendInspect"
    description = (
        "Control and inspect the ENTIRE Home Assistant frontend like a real user — see screen, click buttons, fill forms, scroll, navigate. "
        "Works on ANY page: dashboards, settings, integrations, automations, device config, add-ons, logs, dialogs, popups, modals, etc. "
        "This is for UI interaction — NOT for device control or entity state queries. "
        "\n\n"
        "MANDATORY WORKFLOW - You MUST complete BOTH steps before answering about UI content: "
        "1) FIRST action=snapshot → Get DOM structure, card types, entity bindings. "
        "2) SECOND action=exec_js → Get rendered content. Do NOT blindly truncate with slice(); return full text and this tool will split long strings into chunks. "
        "For large pages, exec_js stores full results in an internal text cache; use action=search_cache with query=function/card/dialog/label name to get precise snippets under 5000 chars. "
        "DO NOT stop after snapshot alone — snapshot gives structure, exec_js gives ACTUAL CONTENT. You need BOTH. "
        "If user asks about cards/UI/screen, you MUST call snapshot THEN exec_js before responding. "
        "\n\n"
        "WHAT YOU CAN DO: "
        "- View ANY page content: dashboards, cards, settings panels, integration configs, automation editors, system logs, add-on pages. "
        "- Click ANY element: buttons, links, menu items, cards, icons, toggles, tabs, dialog buttons, popup options. "
        "- Fill ANY form: input fields, textareas, search boxes, config forms, automation conditions, entity selectors. "
        "- Use safe keyboard actions: Enter, Escape, Tab, Arrow keys, Backspace/Delete, repeated navigation key presses. Avoid global shortcut keys. "
        "- Handle dialogs/popups: confirmation dialogs, edit dialogs, more-info popups, config wizards, modal windows. "
        "- Scroll ANY container: page scroll, card lists, long forms, log viewers, dropdown menus. "
        "- Navigate to ANY path: /lovelace, /config, /config/integrations, /config/automation/edit/xxx, /developer-tools, etc. "
        "\n\n"
        "USER INTENT EXAMPLES: "
        "- 'What's on my screen' → snapshot + exec_js, describe ALL visible content. "
        "- 'Check this page for issues' → Look for errors, empty areas, broken layouts, missing data. "
        "- 'Click the add button' / 'Open settings' → tap action with text or selector. "
        "- 'Fill in the name field' → type action with selector/text and value. "
        "- 'Go to integrations' → navigate to /config/integrations. "
        "- 'Scroll down' → scroll action. "
        "- 'Close this popup' → tap the X button or outside the dialog. "
        "- 'What does this dialog say' → snapshot or exec_js to read dialog content. "
        "- 'Help me configure this integration' → Navigate, read forms, fill fields, click submit. "
        "\n\n"
        "WORKS WITH DashboardCard TOOL: "
        "- FrontendInspect = SEE and INTERACT with UI (view cards, click, scroll, read rendered content). "
        "- DashboardCard = MODIFY Lovelace config (create/edit/delete cards, change YAML). "
        "- Typical workflow: Use FrontendInspect to see current dashboard → Use DashboardCard to modify config → Use FrontendInspect to verify changes. "
        "- FrontendInspect shows what user SEES; DashboardCard changes what will be RENDERED. "
        "- If FrontendInspect sees a card type (for example html-pro-card) but cannot read its actual content, DO NOT ask user to paste YAML; call DashboardCard to inspect the current dashboard/card config. "
        "- If user asks 'optimize this card', use FrontendInspect to identify the visible card, then DashboardCard to read/edit the card config, then FrontendInspect again to verify the rendered result. "
        "\n\n"
        "HA FRONTEND DOM STRUCTURE (shadow DOM chain, each → means .shadowRoot): "
        "document → home-assistant → home-assistant-main → ha-drawer → .mdc-drawer-app-content → partial-panel-resolver → "
        "  Dashboard: ha-panel-lovelace → hui-root → hui-view/hui-masonry-view/hui-sections-view → hui-card/hui-* → ha-card → content "
        "  Settings: ha-panel-config → ha-config-* (e.g. ha-config-integrations, ha-config-automation) "
        "  Developer: ha-panel-developer-tools → developer-tools-* "
        "Sidebar: home-assistant-main → ha-sidebar → a.sidebar-list-item "
        "Dialogs float at home-assistant level: home-assistant → ha-more-info-dialog / ha-dialog / ha-voice-command-dialog "
        "Key exec_js patterns: "
        "`document.querySelector('home-assistant').shadowRoot.querySelector('home-assistant-main').shadowRoot` as entry. "
        "`entry.querySelector('ha-drawer').shadowRoot.querySelector('.mdc-drawer-app-content').querySelector('partial-panel-resolver')` for content root. "
        "For cards: continue into `.shadowRoot.querySelector('ha-panel-lovelace').shadowRoot.querySelector('hui-root').shadowRoot.querySelector('hui-view,hui-masonry-view,hui-sections-view')` "
        "For dialogs: `document.querySelector('home-assistant').shadowRoot.querySelector('ha-more-info-dialog,ha-dialog')` "
        "\n\n"
        "DIALOG AUTO-DETECTION: "
        "- When ANY dialog/popup opens in HA, its structure is AUTO-CAPTURED and included in snapshot results as 'active_dialogs'. "
        "- Each dialog snapshot contains: type (host component), title, body (inputs with labels/values/hints), list_items, buttons (with text/role/hints). "
        "- Use the 'hint' field in inputs/buttons to know exactly how to interact: e.g. hint='FrontendInspect type text=\"Name\" value=\"...\"' "
        "- ALWAYS check active_dialogs in snapshot results BEFORE using exec_js to interact with dialogs. "
        "- Do NOT guess dialog DOM structure with exec_js — use the structured active_dialogs data instead. "
        "\n\n"
        "CRITICAL: "
        "- snapshot returns CONTENT AREA (not sidebar). Use it to understand page structure. "
        "- exec_js can run ANY JavaScript — use it to extract text, check element states, get computed values. Full results are cached for search. "
        "- Prefer search_cache for precise targeting inside cached large results: query a selector/card/dialog/function name and inspect matching context only. "
        "- tap works on buttons, links, icons, cards — anything clickable. Use visible text or CSS selector. "
        "- Do NOT call device control tools based on entities seen in UI — user asks about the UI, not device control. "
        "\n\n"
        "ACTIONS: "
        "snapshot - Get current page DOM structure and displayed data. Call FIRST. "
        "exec_js - Run JavaScript code (js_code required). Call SECOND for detailed text. Results are cached for search_cache. "
        "search_cache - Search cached exec_js/snapshot text. Use query to find exact card/function/dialog/label text; returns <=5000 chars of context. "
        "navigate - Go to a page by path (e.g. /config/integrations). "
        "tap - Click element by selector or visible text. Works on any clickable element. "
        "type - Type into input/textarea. Use selector or text to find, value for content, clear=true to clear first. "
        "key - Send safe keyboard events. Use key='Enter'/'Escape'/'Tab'/'ArrowDown', repeat for continuous press. Do NOT use global shortcuts like Ctrl+A. "
        "scroll - Scroll direction (up/down/left/right), amount in px (default 300)."
    )

    parameters = vol.Schema({
        vol.Required("action"): vol.In(["snapshot", "navigate", "tap", "type", "key", "scroll", "exec_js", "search_cache"]),
        vol.Optional("js_code"): str,
        vol.Optional("selector"): str,
        vol.Optional("text"): str,
        vol.Optional("path"): str,
        vol.Optional("value"): str,
        vol.Optional("query"): str,
        vol.Optional("key"): str,
        vol.Optional("repeat", default=1): int,
        vol.Optional("ctrl", default=False): bool,
        vol.Optional("shift", default=False): bool,
        vol.Optional("alt", default=False): bool,
        vol.Optional("meta", default=False): bool,
        vol.Optional("clear", default=False): bool,
        vol.Optional("direction", default="down"): vol.In(["up", "down", "left", "right"]),
        vol.Optional("amount", default=300): int,
        vol.Optional("depth", default=8): int,
    })

    _DEEP_QUERY = """
    function _collectRoots(node, out, visited) {
        if (!node || visited.has(node)) return out;
        visited.add(node);
        out.push(node);
        var els = node.querySelectorAll('*');
        for (var i = 0; i < els.length; i++) {
            var e = els[i];
            if (e.shadowRoot && !visited.has(e.shadowRoot)) {
                _collectRoots(e.shadowRoot, out, visited);
            }
            if (e.tagName === 'SLOT') {
                var assigned = e.assignedElements ? e.assignedElements({flatten:true}) : [];
                for (var j = 0; j < assigned.length; j++) {
                    if (assigned[j].shadowRoot && !visited.has(assigned[j].shadowRoot)) {
                        _collectRoots(assigned[j].shadowRoot, out, visited);
                    }
                }
            }
        }
        return out;
    }
    function deepQuery(root, sel) {
        var start = root === document ? document : (root.shadowRoot || root);
        var vis = new Set();
        var roots = _collectRoots(start, [], vis);
        if (root === document) {
            var bodyKids = document.body.children;
            for (var k = 0; k < bodyKids.length; k++) {
                if (bodyKids[k].shadowRoot) _collectRoots(bodyKids[k].shadowRoot, roots, vis);
            }
        }
        for (var i = 0; i < roots.length; i++) {
            try { var r = roots[i].querySelector(sel); if (r) return r; } catch(_) {}
        }
        var parts = sel.split(/\\s+/).filter(Boolean);
        if (parts.length > 1) {
            var ancestor = deepQuery(root, parts[0]);
            if (ancestor) {
                var sub = parts.slice(1).join(' ');
                var vis2 = new Set();
                var subRoots = _collectRoots(ancestor.shadowRoot || ancestor, [], vis2);
                for (var si = 0; si < subRoots.length; si++) {
                    try { var sr = subRoots[si].querySelector(sub); if (sr) return sr; } catch(_) {}
                }
            }
        }
        return null;
    }
    """

    _FIND_BY_TEXT = """
    function findByText(root, text) {
        var lc = text.toLowerCase();
        var best = null;
        var bestLen = Infinity;
        var vis = new Set();
        var start = root === document ? document : (root.shadowRoot || root);
        var roots = _collectRoots(start, [], vis);
        if (root === document) {
            var bodyKids = document.body.children;
            for (var bk = 0; bk < bodyKids.length; bk++) {
                if (bodyKids[bk].shadowRoot) _collectRoots(bodyKids[bk].shadowRoot, roots, vis);
            }
        }
        for (var ri = 0; ri < roots.length; ri++) {
            var els = roots[ri].querySelectorAll('*');
            for (var i = 0; i < els.length; i++) {
                var el = els[i];
                var tag = el.tagName.toLowerCase();
                if (tag === 'script' || tag === 'style' || tag === 'svg') continue;
                var al = el.getAttribute('aria-label');
                if (al) {
                    var alc = al.toLowerCase();
                    if (alc.indexOf(lc) !== -1 && al.length < bestLen) {
                        best = el; bestLen = al.length; continue;
                    }
                }
                var lb = el.getAttribute('label');
                if (lb) {
                    var lbc = lb.toLowerCase();
                    if (lbc.indexOf(lc) !== -1 && lb.length < bestLen) {
                        best = el; bestLen = lb.length; continue;
                    }
                }
                var ph = el.getAttribute('placeholder');
                if (ph) {
                    var plc = ph.toLowerCase();
                    if (plc.indexOf(lc) !== -1 && ph.length < bestLen) {
                        best = el; bestLen = ph.length; continue;
                    }
                }
                var ti = el.getAttribute('title');
                if (ti) {
                    var tlc = ti.toLowerCase();
                    if (tlc.indexOf(lc) !== -1 && ti.length < bestLen) {
                        best = el; bestLen = ti.length; continue;
                    }
                }
                var ct = (el.textContent || '').trim();
                if (ct.length > 0 && ct.length < 500) {
                    var ctlc = ct.toLowerCase();
                    if (ctlc === lc) { return el; }
                    if (ctlc.indexOf(lc) !== -1 && ct.length < bestLen) {
                        best = el; bestLen = ct.length;
                    }
                }
            }
        }
        return best;
    }
    """

    @staticmethod
    def _clean(val):
        if isinstance(val, str):
            v = val.strip()
            if not v or v in ('.', '#', '*', '>', '+', '~'):
                return None
            return v
        return val

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> JsonObjectType:
        args = tool_input.tool_args
        for k in ("selector", "text", "path", "js_code", "value", "query"):
            if k in args:
                args[k] = self._clean(args[k])
        action = args["action"]

        if action == "snapshot":
            _domain_data(hass).pop(_FRONTEND_SNAPSHOT_KEY, None)
            exec_id = f"snap_{int(time.time()*1000)}"
            depth = args.get("depth", 15)
            selector = args.get("selector")
            js = self._build_snapshot_js(depth, selector)
            queue_frontend_exec(hass, exec_id, js)
            result = await async_wait_frontend_exec_result(hass, exec_id)
            if result and not isinstance(result, dict):
                result = {"raw": str(result)}
            if result and "error" not in result:
                store_frontend_snapshot(hass, result)
                store_frontend_text_cache(hass, "snapshot", result)
            if isinstance(result, dict):
                nav = result.pop("nav", None)
                active_dialogs = _domain_data(hass).get("claw_active_dialogs")
                if active_dialogs:
                    result["active_dialogs"] = active_dialogs
                out = {"success": True, "snapshot": result}
                if nav:
                    out["nav_hint"] = f"Sidebar has {len(nav)} items. Use navigate action to switch pages."
                return out
            return {"success": "error" not in (result or {}), "snapshot": result}

        elif action == "navigate":
            path = args.get("path")
            if not path:
                return {"error": "path is required for navigate action"}
            if not path.startswith("/"):
                path = "/" + path
            exec_id = f"nav_{int(time.time()*1000)}"
            js = f"""(function(){{history.pushState(null,'',{json.dumps(path)});window.dispatchEvent(new CustomEvent('location-changed'));return {{navigated:{json.dumps(path)}}};}})()"""
            queue_frontend_exec(hass, exec_id, js)
            result = await async_wait_frontend_exec_result(hass, exec_id)
            _domain_data(hass).pop(_FRONTEND_SNAPSHOT_KEY, None)
            await asyncio.sleep(1.5)
            return {"success": True, "result": result}

        elif action == "tap":
            return await self._do_tap(hass, tool_input)

        elif action == "type":
            return await self._do_type(hass, tool_input)

        elif action == "key":
            return await self._do_key(hass, tool_input)

        elif action == "scroll":
            return await self._do_scroll(hass, tool_input)

        elif action == "exec_js":
            js_code = args.get("js_code")
            if not js_code:
                return {"error": "js_code is required for exec_js action"}
            exec_id = f"exec_{int(time.time()*1000)}"
            queue_frontend_exec(hass, exec_id, js_code)
            result = await async_wait_frontend_exec_result(hass, exec_id)
            if result and "error" not in (result if isinstance(result, dict) else {}):
                store_frontend_text_cache(hass, "exec_js", result)
            if isinstance(result, str) and len(result) > 4000:
                size = 4000
                chunks = [result[i:i + size] for i in range(0, len(result), size)]
                result = {
                    "chunked": True,
                    "total_parts": len(chunks),
                    "parts": [
                        {
                            "part": idx + 1,
                            "final": idx == len(chunks) - 1,
                            "text": chunk,
                        }
                        for idx, chunk in enumerate(chunks[:5])
                    ],
                    "has_more": len(chunks) > 5,
                }
            return {"success": "error" not in (result or {}), "result": result}

        elif action == "search_cache":
            query = args.get("query")
            if not query:
                return {"error": "query is required for search_cache action"}
            return {"success": True, "result": search_frontend_text_cache(hass, query)}

        return {"error": f"Unknown action: {action}"}

    async def _do_tap(self, hass, tool_input):
        args = tool_input.tool_args
        selector = args.get("selector")
        text = args.get("text")
        if not selector and not text:
            return {"error": "tap requires selector or text to find the element"}
        exec_id = f"tap_{int(time.time()*1000)}"
        find_code = self._build_find_element_js(selector, text)
        js = f"""(function(){{
            {find_code}
            if (!el) return {{error:'element not found',selector:{json.dumps(selector)},text:{json.dumps(text)}}};

            function deepEFP(x, y) {{
                var e = document.elementFromPoint(x, y);
                if (!e) return null;
                while (e && e.shadowRoot) {{
                    var deeper = e.shadowRoot.elementFromPoint(x, y);
                    if (!deeper || deeper === e) break;
                    e = deeper;
                }}
                return e;
            }}

            function showRipple(cx, cy) {{
                var overlay = document.getElementById('__claw_tap_overlay');
                if (!overlay) {{
                    overlay = document.createElement('div');
                    overlay.id = '__claw_tap_overlay';
                    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;'
                        + 'pointer-events:none;z-index:2147483647;overflow:visible;';
                    document.documentElement.appendChild(overlay);
                }}
                var dot = document.createElement('div');
                dot.style.cssText = 'position:fixed;pointer-events:none;border-radius:50%;'
                    + 'width:28px;height:28px;left:'+(cx-14)+'px;top:'+(cy-14)+'px;'
                    + 'background:rgba(3,169,244,0.5);box-shadow:0 0 12px 4px rgba(3,169,244,0.3);'
                    + 'transition:transform .4s cubic-bezier(.2,.8,.3,1),opacity .4s ease-out;transform:scale(1);';
                overlay.appendChild(dot);
                requestAnimationFrame(function(){{requestAnimationFrame(function(){{
                    dot.style.transform='scale(2.8)';dot.style.opacity='0';
                }})}});
                setTimeout(function(){{dot.remove()}},450);
            }}

            var ISEL = 'button,a,input,select,textarea,[role=button],[role=menuitem],[role=option],[role=tab],[role=link],[role=switch],ha-icon-button,mwc-icon-button,ha-button,mwc-button,ha-list-item,mwc-list-item,ha-check-list-item,ha-clickable-list-item,ha-dropdown-item';

            function drillDown(node) {{
                if (!node) return null;
                if (node.matches && node.matches(ISEL)) return node;
                var found = deepQuery(node, ISEL);
                if (found) return found;
                return null;
            }}

            function climbUp(node) {{
                if (!node) return null;
                var walk = node;
                var visited = new Set();
                while (walk && !visited.has(walk)) {{
                    visited.add(walk);
                    if (walk.matches && walk.matches(ISEL)) return walk;
                    if (walk.matches && walk.matches('ha-card,ha-integration-card,ha-config-flow-card')) {{
                        var inner = deepQuery(walk, ISEL);
                        if (inner) return inner;
                    }}
                    var next = walk.parentElement;
                    if (!next) {{
                        var rn = walk.getRootNode && walk.getRootNode();
                        next = (rn && rn !== walk && rn.host) ? rn.host : null;
                    }}
                    walk = next;
                }}
                return null;
            }}

            var rect = el.getBoundingClientRect();
            if (rect.width === 0 && rect.height === 0) {{
                var inner = deepQuery(el, ISEL);
                if (inner) {{ el = inner; rect = el.getBoundingClientRect(); }}
            }}
            var cx = rect.left + rect.width/2, cy = rect.top + rect.height/2;
            showRipple(cx, cy);

            var deep = deepEFP(cx, cy);
            var target = drillDown(el) || climbUp(deep) || drillDown(deep) || el;
            var targetTag = (target.tagName||'').toLowerCase();

            target.click();

            if (target.focus) target.focus();
            return {{tapped:true,tag:el.tagName.toLowerCase(),targetTag:targetTag,id:el.id||'',rect:{{x:Math.round(rect.x),y:Math.round(rect.y),w:Math.round(rect.width),h:Math.round(rect.height)}}}};
        }})()"""
        queue_frontend_exec(hass, exec_id, js)
        result = await async_wait_frontend_exec_result(hass, exec_id)
        _domain_data(hass).pop(_FRONTEND_SNAPSHOT_KEY, None)
        out = {"success": result and "error" not in result, "result": result}
        await asyncio.sleep(0.5)
        active_dialogs = _domain_data(hass).get("claw_active_dialogs")
        if active_dialogs:
            out["opened_dialog"] = active_dialogs
            out["dialog_hint"] = "A dialog is now open. Use the 'hint' fields in body/buttons to interact. Do NOT use exec_js to find dialog elements."
        return out

    async def _do_type(self, hass, tool_input):
        args = tool_input.tool_args
        selector = args.get("selector")
        text = args.get("text")
        value = args.get("value") or ""
        clear = args.get("clear", False)
        if not selector and not text:
            return {"error": "type requires selector or text to find the input field"}
        exec_id = f"type_{int(time.time()*1000)}"
        find_code = self._build_find_element_js(selector, text)
        js = f"""(function(){{
            {find_code}
            if (!el) return {{error:'input not found',selector:{json.dumps(selector)},text:{json.dumps(text)}}};
            var value = {json.dumps(value)};
            var clear = {json.dumps(clear)};
            function allDeep(root, sel, out, seen) {{
                if (!root || seen.has(root)) return out;
                seen.add(root);
                try {{ root.querySelectorAll && root.querySelectorAll(sel).forEach(function(x){{out.push(x);}}); }} catch(_) {{}}
                var nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
                for (var i = 0; i < nodes.length; i++) {{
                    var n = nodes[i];
                    if (n.shadowRoot) allDeep(n.shadowRoot, sel, out, seen);
                    if (n.tagName === 'SLOT') {{
                        var a = n.assignedElements ? n.assignedElements({{flatten:true}}) : [];
                        for (var j = 0; j < a.length; j++) allDeep(a[j], sel, out, seen);
                    }}
                }}
                return out;
            }}
            function editableScore(x) {{
                if (!x) return -1;
                var tag = (x.tagName || '').toLowerCase();
                if (tag === 'textarea') return 100;
                if (tag === 'input') return 95;
                if (x.isContentEditable || (x.getAttribute && x.getAttribute('contenteditable') != null)) return 90;
                if (x.classList && (x.classList.contains('cm-content') || x.classList.contains('monaco-editor'))) return 80;
                return -1;
            }}
            function findInput(host) {{
                var direct = editableScore(host) >= 0 ? host : null;
                var found = allDeep(host.shadowRoot || host, 'input,textarea,[contenteditable=true],[contenteditable=""],.cm-content,.monaco-editor textarea', [], new Set());
                var best = direct, bs = editableScore(direct);
                for (var i = 0; i < found.length; i++) {{
                    var s = editableScore(found[i]);
                    if (s > bs) {{ best = found[i]; bs = s; }}
                }}
                return best || host;
            }}
            function fire(x, type) {{
                x.dispatchEvent(new Event(type, {{bubbles:true, composed:true}}));
            }}
            function key(x, k) {{
                x.dispatchEvent(new KeyboardEvent('keydown', {{key:k,bubbles:true,cancelable:true,composed:true}}));
                if (k.length === 1) x.dispatchEvent(new KeyboardEvent('keypress', {{key:k,bubbles:true,cancelable:true,composed:true}}));
                x.dispatchEvent(new KeyboardEvent('keyup', {{key:k,bubbles:true,cancelable:true,composed:true}}));
            }}
            var inp = findInput(el);
            inp.focus && inp.focus();
            if (inp.select && clear) inp.select();
            var tag = (inp.tagName || '').toLowerCase();
            var isEditable = inp.isContentEditable || (inp.getAttribute && inp.getAttribute('contenteditable') != null) || (inp.classList && inp.classList.contains('cm-content'));
            if (isEditable) {{
                inp.focus();
                var sel = window.getSelection();
                if (clear && sel) {{
                    var r = document.createRange();
                    r.selectNodeContents(inp);
                    sel.removeAllRanges();
                    sel.addRange(r);
                }}
                document.execCommand('insertText', false, value);
                fire(inp, 'beforeinput');
                fire(inp, 'input');
                fire(inp, 'change');
                return {{typed:true,mode:'contenteditable',tag:tag,value:(inp.innerText||inp.textContent||'').slice(0,100)}};
            }}
            if ('value' in inp) {{
                var proto = tag === 'textarea' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
                var nativeSet = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                if (clear) {{
                    if (nativeSet) nativeSet.call(inp, '');
                    else inp.value = '';
                    fire(inp, 'input');
                }}
                if (nativeSet) nativeSet.call(inp, value);
                else inp.value = value;
                fire(inp, 'beforeinput');
                fire(inp, 'input');
                fire(inp, 'change');
                key(inp, 'Enter');
                return {{typed:true,mode:'value',tag:tag,value:(inp.value||'').slice(0,100)}};
            }}
            return {{error:'target is not editable',tag:tag,id:inp.id||''}};
        }})()"""
        queue_frontend_exec(hass, exec_id, js)
        result = await async_wait_frontend_exec_result(hass, exec_id)
        _domain_data(hass).pop(_FRONTEND_SNAPSHOT_KEY, None)
        return {"success": result and "error" not in result, "result": result}

    async def _do_key(self, hass, tool_input):
        args = tool_input.tool_args
        key = args.get("key")
        if not key:
            return {"error": "key is required for key action"}
        if args.get("ctrl") or args.get("alt") or args.get("meta"):
            return {"error": "global shortcut modifiers ctrl/alt/meta are disabled for safety; use exec_js only when explicitly necessary"}
        repeat = max(1, min(int(args.get("repeat", 1)), 50))
        selector = args.get("selector")
        text = args.get("text")
        ctrl = False
        shift = bool(args.get("shift", False))
        alt = False
        meta = False
        exec_id = f"key_{int(time.time()*1000)}"
        find_code = self._build_find_element_js(selector, text)
        js = f"""
        (function() {{
            {find_code}
            function keyCodeFor(k) {{
                var m = {{
                    Enter:13, Escape:27, Esc:27, Tab:9, Backspace:8, Delete:46,
                    ArrowUp:38, ArrowDown:40, ArrowLeft:37, ArrowRight:39,
                    Home:36, End:35, PageUp:33, PageDown:34, Space:32
                }};
                return m[k] || (k && k.length === 1 ? k.toUpperCase().charCodeAt(0) : 0);
            }}
            function targetEl() {{
                if (el && typeof el.focus === 'function') {{
                    el.focus();
                    return el;
                }}
                var a = document.activeElement;
                while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
                return a || document.body;
            }}
            var t = targetEl();
            var k = {json.dumps(key)};
            var opts = {{
                key: k,
                code: k.length === 1 ? 'Key' + k.toUpperCase() : k,
                keyCode: keyCodeFor(k),
                which: keyCodeFor(k),
                bubbles: true,
                cancelable: true,
                composed: true,
                ctrlKey: {json.dumps(ctrl)},
                shiftKey: {json.dumps(shift)},
                altKey: {json.dumps(alt)},
                metaKey: {json.dumps(meta)}
            }};
            for (var i = 0; i < {repeat}; i++) {{
                t.dispatchEvent(new KeyboardEvent('keydown', opts));
                if (k.length === 1) t.dispatchEvent(new KeyboardEvent('keypress', opts));
                t.dispatchEvent(new KeyboardEvent('keyup', opts));
            }}
            return {{pressed:k, repeat:{repeat}, target:t.tagName ? t.tagName.toLowerCase() : 'document', ctrl:{json.dumps(ctrl)}, shift:{json.dumps(shift)}, alt:{json.dumps(alt)}, meta:{json.dumps(meta)}}};
        }})()"""
        queue_frontend_exec(hass, exec_id, js)
        result = await async_wait_frontend_exec_result(hass, exec_id)
        _domain_data(hass).pop(_FRONTEND_SNAPSHOT_KEY, None)
        return {"success": result and "error" not in result, "result": result}

    async def _do_scroll(self, hass, tool_input):
        args = tool_input.tool_args
        selector = args.get("selector")
        direction = args.get("direction", "down")
        amount = args.get("amount", 300)
        exec_id = f"scr_{int(time.time()*1000)}"
        dx, dy = 0, 0
        if direction == "down": dy = amount
        elif direction == "up": dy = -amount
        elif direction == "right": dx = amount
        elif direction == "left": dx = -amount
        if selector:
            find_code = self._build_find_element_js(selector, None)
        else:
            find_code = ""
        js = f"""(function(){{
            {self._DEEP_QUERY}
            {find_code}
            if (typeof el === 'undefined' || !el) {{
                function deepEFP(x, y) {{
                    var e = document.elementFromPoint(x, y);
                    if (!e) return null;
                    while (e && e.shadowRoot) {{
                        var deeper = e.shadowRoot.elementFromPoint(x, y);
                        if (!deeper || deeper === e) break;
                        e = deeper;
                    }}
                    return e;
                }}
                function findScroller(node) {{
                    var walk = node;
                    var visited = new Set();
                    while (walk && !visited.has(walk)) {{
                        visited.add(walk);
                        var cs = window.getComputedStyle(walk);
                        var ov = cs.overflowY || cs.overflow;
                        if ((ov === 'auto' || ov === 'scroll') && walk.scrollHeight > walk.clientHeight + 10) {{
                            return walk;
                        }}
                        var next = walk.parentElement;
                        if (!next) {{
                            var rn = walk.getRootNode && walk.getRootNode();
                            next = (rn && rn !== walk && rn.host) ? rn.host : null;
                        }}
                        walk = next;
                    }}
                    return null;
                }}
                var cx = window.innerWidth / 2, cy = window.innerHeight / 2;
                var deepEl = deepEFP(cx, cy);
                var el = findScroller(deepEl) || document.scrollingElement || document.documentElement;
            }}
            el.scrollBy({{left:{dx},top:{dy},behavior:'smooth'}});
            return {{scrolled:true,direction:{json.dumps(direction)},amount:{amount},target:el.tagName ? el.tagName.toLowerCase() : 'document'}};
        }})()"""
        queue_frontend_exec(hass, exec_id, js)
        result = await async_wait_frontend_exec_result(hass, exec_id)
        return {"success": True, "result": result}

    @classmethod
    def _build_find_element_js(cls, selector: str | None, text: str | None) -> str:
        parts = [cls._DEEP_QUERY]
        if selector:
            parts.append(f"var el = deepQuery(document, {json.dumps(selector)});")
        if text:
            parts.append(cls._FIND_BY_TEXT)
            if selector:
                parts.append(f"if (!el) el = findByText(document, {json.dumps(text)});")
            else:
                parts.append(f"var el = findByText(document, {json.dumps(text)});")
        if not selector and not text:
            parts.append("var el = null;")
        return "\n".join(parts)

    @staticmethod
    def _build_snapshot_js(depth: int = 8, selector: str | None = None) -> str:
        return f"""
        (function() {{
            var SKIP = {{'claw-assist-dock':1,'claw-assist-dock-style':1,'ha-sidebar':1}};
            var SKIP_TAG = {{'script':1,'style':1,'link':1,'noscript':1,'svg':1,'path':1,'img':1,'canvas':1,'video':1,'audio':1,'br':1,'hr':1}};
            var PASS_THROUGH = {{'div':1,'span':1,'slot':1,'section':1,'article':1,'main':1,'aside':1,'header':1,'footer':1,'nav':1}};
            var HA_ATTRS = ['state','entity','entity-id','card-type','type','role','aria-label','title','placeholder','value','href','icon','name','panel'];
            var MAX_NODES = 1500;
            var nodeCount = 0;
            var MAX_CHILDREN = 30;
            function snap(el, d) {{
                if (!el) return null;
                if (el.nodeType === 1 && (d <= 0 || nodeCount >= MAX_NODES)) {{
                    var ft = (el.innerText || '').trim();
                    if (ft && ft.length > 0) {{
                        nodeCount++;
                        return {{tag: el.tagName.toLowerCase(), text: ft.slice(0,150)}};
                    }}
                    return null;
                }}
                if (el.nodeType === 3) {{
                    var t = (el.textContent || '').trim();
                    if (!t) return null;
                    nodeCount++;
                    return {{tag:'#text', text:t.slice(0,120)}};
                }}
                if (el.nodeType !== 1) return null;
                var tag = el.tagName.toLowerCase();
                if (SKIP_TAG[tag]) return null;
                if (el.id && SKIP[el.id]) return null;
                nodeCount++;
                var o = {{tag: tag}};
                if (el.id) o.id = el.id;
                if (el.className && typeof el.className === 'string') {{
                    var cls = el.className.trim();
                    if (cls && !PASS_THROUGH[tag]) o.class = cls.slice(0, 80);
                }}
                var attrs = {{}};
                for (var ai = 0; ai < HA_ATTRS.length; ai++) {{
                    var v = el.getAttribute(HA_ATTRS[ai]);
                    if (v) attrs[HA_ATTRS[ai]] = v.slice(0, 100);
                }}
                if (Object.keys(attrs).length) o.attrs = attrs;
                try {{
                    var eid = el.getAttribute && (el.getAttribute('entity-id') || el.getAttribute('entity'));
                    if (!eid && el.stateObj) eid = el.stateObj.entity_id;
                    if (eid) {{
                        var ha = document.querySelector('home-assistant');
                        var hObj = ha && ha.hass;
                        if (hObj && hObj.states && hObj.states[eid]) {{
                            var st = hObj.states[eid];
                            o.entity = eid;
                            o.state = st.state;
                            var u = st.attributes && st.attributes.unit_of_measurement;
                            if (u) o.unit = u;
                            var fn = st.attributes && st.attributes.friendly_name;
                            if (fn) o.name = fn;
                        }}
                    }}
                }} catch(_) {{}}
                if (d > 1 && nodeCount < MAX_NODES) {{
                    var children = [];
                    var sr = el.shadowRoot;
                    if (sr) {{
                        var sn = sr.childNodes;
                        for (var i = 0; i < Math.min(sn.length, MAX_CHILDREN) && nodeCount < MAX_NODES; i++) {{
                            var c = snap(sn[i], d - 1);
                            if (c) children.push(c);
                        }}
                    }}
                    var ln = el.childNodes;
                    for (var j = 0; j < Math.min(ln.length, MAX_CHILDREN) && nodeCount < MAX_NODES; j++) {{
                        var c2 = snap(ln[j], d - 1);
                        if (c2) children.push(c2);
                    }}
                    if (children.length) {{
                        if (PASS_THROUGH[tag] && !o.id && !o.attrs && !o.entity && children.length === 1) {{
                            return children[0];
                        }}
                        o.children = children;
                    }}
                    else {{
                        var vt = (el.innerText || '').trim();
                        if (vt && vt.length < 200) o.text = vt;
                    }}
                }} else if (d <= 1) {{
                    var vt2 = (el.innerText || '').trim();
                    if (vt2 && vt2.length < 200) o.text = vt2;
                }}
                if (!o.children && !o.text && !o.id && !o.attrs && !o.entity && !o.state && PASS_THROUGH[tag]) return null;
                return o;
            }}
            var sel = {json.dumps(selector) if selector else 'null'};
            var target;
            if (sel) {{
                target = document.querySelector(sel);
                if (!target) {{
                    var ha = document.querySelector('home-assistant');
                    if (ha && ha.shadowRoot) target = ha.shadowRoot.querySelector(sel);
                }}
            }}
            if (!target) {{
                function dq(root, sel) {{
                    if (!root) return null;
                    var el = root.querySelector ? root.querySelector(sel) : null;
                    if (el) return el;
                    var sr = root.shadowRoot;
                    if (sr) {{ el = dq(sr, sel); if (el) return el; }}
                    var ch = root.querySelectorAll ? root.querySelectorAll('*') : [];
                    for (var ci = 0; ci < Math.min(ch.length, 50); ci++) {{
                        if (ch[ci].shadowRoot) {{ el = dq(ch[ci].shadowRoot, sel); if (el) return el; }}
                    }}
                    return null;
                }}
                var ha = document.querySelector('home-assistant');
                var main = ha && ha.shadowRoot ? ha.shadowRoot.querySelector('home-assistant-main') : null;
                var view = dq(main, 'hui-view,hui-sections-view,hui-masonry-view,hui-panel-view,hui-sidebar-view');
                if (!view) view = dq(main, 'partial-panel-resolver');
                target = view || main || document.body;
            }}
            var navItems = [];
            try {{
                var ha2 = document.querySelector('home-assistant');
                var main2 = ha2 && ha2.shadowRoot ? ha2.shadowRoot.querySelector('home-assistant-main') : null;
                var mainSR2 = main2 && main2.shadowRoot;
                var sidebar = mainSR2 ? mainSR2.querySelector('ha-sidebar') : null;
                var sidebarSR = sidebar && sidebar.shadowRoot;
                if (sidebarSR) {{
                    var items = sidebarSR.querySelectorAll('a.sidebar-list-item');
                    for (var ni = 0; ni < items.length; ni++) {{
                        var lbl = items[ni].getAttribute('data-panel') || items[ni].getAttribute('aria-label') || (items[ni].textContent||'').trim();
                        var hr = items[ni].getAttribute('href') || '';
                        if (lbl) navItems.push({{label: lbl.slice(0,40), href: hr}});
                    }}
                }}
            }} catch(_) {{}}
            var dialogs = [];
            try {{
                var haDlg = document.querySelector('home-assistant');
                var haSR = haDlg && haDlg.shadowRoot;
                if (haSR) {{
                    var candidates = haSR.querySelectorAll('ha-dialog, ha-more-info-dialog, ha-voice-command-dialog, dialog[open]');
                    for (var di = 0; di < candidates.length; di++) {{
                        var dlgEl = candidates[di];
                        var dlgTag = dlgEl.tagName.toLowerCase();
                        var inner = dlgEl.shadowRoot || dlgEl;
                        var realDialog = inner.querySelector ? inner.querySelector('dialog[open], md-dialog[open], .dialog.open, [role="dialog"]') : null;
                        if (!realDialog && dlgEl.hasAttribute && dlgEl.hasAttribute('open')) realDialog = dlgEl;
                        if (!realDialog && dlgEl.shadowRoot) realDialog = dlgEl;
                        if (!realDialog) continue;
                        var ds = snap(realDialog, {depth});
                        if (ds) {{
                            ds._dialog_host = dlgTag;
                            dialogs.push(ds);
                        }}
                    }}
                }}
            }} catch(_) {{}}
            var result = {{
                url: location.pathname + location.search,
                title: document.title,
                viewport: {{w: window.innerWidth, h: window.innerHeight}},
                nav: navItems.length ? navItems : undefined,
                content: snap(target, {depth}),
                dialogs: dialogs.length ? dialogs : undefined
            }};
            return result;
        }})()
        """
