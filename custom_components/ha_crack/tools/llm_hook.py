from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Dict, Any
import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

from .search_tools import (
    WebSearchTool, UrlFetchTool, NewsSearchTool, DeepWebSearchTool, ZhihuHotTool, StockQueryTool
)
from .ha_tools import (
    EntityQueryTool, ServiceCallTool, GetLiveContextTool, ListServicesTool, 
    AutomationTool, ScriptExecuteTool, HistoryQueryTool, AreaDevicesTool, 
    BatchControlTool, NotifyTool, FireEventTool, InjectJSTool, HAControlTool, FrontendControlTool,
    DashboardTool, HACSTool, GetSystemIndexTool, SetConversationStateTool, ValidateServiceTool,
    ServiceHelpTool, SmartDiscoveryTool
)
from .misc_tools import (
    AgentLoopTool, RolePlayTool, ExecutePythonTool, SystemControlTool,
    ConversationMemoryTool, TextCompressTool, ThinkContinueTool, ParallelToolCallTool,
    ExecuteChainTool, AnalyzeIntentTool, GetConversationHistoryTool
)

_LOGGER = logging.getLogger(__name__)


TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "ServiceCall": {"category": "device", "desc": "调用HA服务控制设备。参数:domain(如light),service(如turn_on),data(如{entity_id:'light.xxx',brightness:255})", "priority": 1},
    "EntityQuery": {"category": "query", "desc": "查询单个实体状态。参数:entity_id(支持模糊匹配如'客厅灯')", "priority": 1},
    "GetLiveContext": {"category": "query", "desc": "获取所有暴露实体的实时状态列表(直接调用无需参数)", "priority": 1},
    "ThinkContinue": {"category": "core", "desc": "记录思考过程(必须首先调用!)。参数:thought(思考内容),next_action(下一步)", "priority": 0},
    "StockQuery": {"category": "search", "desc": "股票/基金行情查询。参数:codes(如'茅台'或'TSLA,AAPL'逗号分隔)", "priority": 1},
    "WebSearch": {"category": "search", "desc": "通用联网搜索(天气/娱乐/体育/科技/一般新闻)。参数:query,num_results(默认3),engine(baidu/bing)", "priority": 2},
    "BatchControl": {"category": "device", "desc": "批量控制多个设备。参数:entity_ids(列表),action(turn_on/turn_off/toggle),data", "priority": 2},
    "AreaDevices": {"category": "query", "desc": "获取指定区域内所有设备。参数:area(区域名如'客厅')", "priority": 2},
    "HistoryQuery": {"category": "query", "desc": "查询实体历史状态。参数:entity_id,hours(默认24小时)", "priority": 2},
    "Automation": {"category": "system", "desc": "管理自动化(不支持创建!)。参数:action(list/trigger/enable/disable),entity_id", "priority": 2},
    "ExecutePython": {"category": "system", "desc": "执行Python代码(可访问hass对象)。参数:code(Python代码字符串)", "priority": 2},
    "NewsSearch": {"category": "search", "desc": "仅金十财经新闻(股票/外汇/期货/贵金属)!娱乐/体育/科技请用WebSearch。参数:category(all/stock/forex/futures/gold),limit,query", "priority": 2},
    "DeepWebSearch": {"category": "search", "desc": "深度搜索并提取网页正文内容。参数:query,num_results", "priority": 3},
    "UrlFetch": {"category": "search", "desc": "获取指定URL内容并压缩。参数:url,max_length(默认2000)", "priority": 3},
    "ZhihuHot": {"category": "search", "desc": "获取知乎热榜。参数:limit(默认20)", "priority": 3},
    "ListServices": {"category": "query", "desc": "列出指定域的可用服务。参数:domain(如light/switch/climate)", "priority": 2},
    "ScriptExecute": {"category": "system", "desc": "执行HA脚本。参数:script_id(如my_script),variables(可选字典)", "priority": 2},
    "Notify": {"category": "device", "desc": "发送通知。参数:message,title(默认'AI助手'),target(默认persistent_notification或notify.xxx)", "priority": 2},
    "FireEvent": {"category": "system", "desc": "触发HA事件。参数:event_type(事件名),event_data(数据字典)", "priority": 3},
    "InjectJS": {"category": "frontend", "desc": "注入JS到前端执行(特效/DOM操作)。参数:code(使用HACrack.toast/navigate/click等API)", "priority": 2},
    "FrontendControl": {"category": "frontend", "desc": "前端控制。参数:action(navigate/click/get_clickables/click_by_text),target", "priority": 2},
    "Dashboard": {"category": "frontend", "desc": "仪表盘管理。参数:action(list/get/create/add_card),dashboard_id,card_config", "priority": 3},
    "HAControl": {"category": "system", "desc": "HA高级控制。参数:action(restart/reload_config/get_integrations/check_config)", "priority": 3},
    "HACS": {"category": "system", "desc": "HACS商店管理。参数:action(github_search/install/update/list),repository。安装前必须先github_search!", "priority": 3},
    "SystemControl": {"category": "system", "desc": "系统控制。参数:action(set_global_inject/clear_role/set_output_mode)", "priority": 3},
    "ConversationMemory": {"category": "misc", "desc": "对话记忆管理。参数:action(save/get/delete/list),key,value", "priority": 3},
    "TextCompress": {"category": "misc", "desc": "压缩长文本节省token。参数:text,max_length(默认1000)", "priority": 3},
    "ParallelToolCall": {"category": "misc", "desc": "记录需要并行调用的工具(实际需依次调用)。参数:tools([{name,args}])", "priority": 3},
    "AgentLoop": {"category": "misc", "desc": "启动迭代式Agent循环。参数:task,max_iterations(默认30)", "priority": 3},
    "RolePlay": {"category": "misc", "desc": "切换角色扮演模式。参数:role(角色名如:猫娘/傲娇/女友/管家/海盗/侦探/机器人/吸血鬼/女王/萝莉/霸总/黑客等)", "priority": 3},
    "ExecuteChain": {"category": "core", "desc": "智能工具链执行器(根据意图自动选择并执行工具链)。参数:intent(用户意图描述)", "priority": 1},
    "AnalyzeIntent": {"category": "core", "desc": "分析用户意图并推荐工具链(不执行只建议)。参数:user_input", "priority": 2},
    "GetConversationHistory": {"category": "core", "desc": "获取当前对话历史记录。参数:limit(默认10)", "priority": 1},
    "GetSystemIndex": {"category": "query", "desc": "获取系统结构索引(区域/域/设备类/人员/自动化/脚本概览)。参数:force_refresh(默认false)", "priority": 2},
    "SetConversationState": {"category": "core", "desc": "设置对话状态。参数:expecting_response(bool),reason", "priority": 2},
    "ValidateService": {"category": "query", "desc": "验证服务调用参数。参数:domain,service,data。返回是否有效/错误/建议", "priority": 2},
    "ServiceHelp": {"category": "query", "desc": "获取域/服务帮助信息。参数:domain(必填),service(可选)", "priority": 2},
    "SmartDiscovery": {"category": "query", "desc": "智能发现实体。参数:area/domain/state/name_contains/name_pattern/device_class/inferred_type/person_name/pet_name/limit", "priority": 2},
}

CORE_TOOLS = ["ThinkContinue", "ServiceCall", "EntityQuery", "GetLiveContext", "StockQuery", "WebSearch", "ExecuteChain"]


class GetToolIndexTool(llm.Tool):
    """查询可用工具索引"""
    name = "GetToolIndex"
    description = "查询可用工具列表。参数: category(分类), keyword(关键词)"
    parameters = vol.Schema({
        vol.Optional("category", default=""): str,
        vol.Optional("keyword", default=""): str,
    })

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> JsonObjectType:
        category = tool_input.tool_args.get("category", "")
        keyword = tool_input.tool_args.get("keyword", "").lower()
        
        results = []
        for name, info in TOOL_REGISTRY.items():
            if category and info["category"] != category:
                continue
            if keyword and keyword not in name.lower() and keyword not in info["desc"].lower():
                continue
            results.append({
                "name": name,
                "category": info["category"],
                "description": info["desc"],
                "type": "tool",
            })
        
        from homeassistant.helpers import intent as intent_module
        for handler in intent_module.async_get(hass):
            intent_name = handler.intent_type
            intent_desc = handler.description or f"Intent: {intent_name}"
            if category and category != "intent":
                continue
            if keyword and keyword not in intent_name.lower() and keyword not in intent_desc.lower():
                continue
            
            params = []
            if hasattr(handler, 'slot_schema') and handler.slot_schema:
                for slot_name, slot_info in handler.slot_schema.items():
                    if hasattr(slot_info, 'description'):
                        params.append(f"{slot_name}")
                    else:
                        params.append(str(slot_name))
            
            results.append({
                "name": intent_name,
                "category": "intent",
                "description": intent_desc,
                "params": params[:5] if params else ["name", "domain"],
                "type": "intent",
            })
        
        results.sort(key=lambda x: (x["category"], x["name"]))
        
        categories = {}
        for r in results:
            cat = r["category"]
            if cat not in categories:
                categories[cat] = []
            if r.get("params"):
                categories[cat].append(f"{r['name']}({','.join(r['params'][:3])}): {r['description']}")
            else:
                categories[cat].append(f"{r['name']}: {r['description']}")
        
        return {
            "success": True,
            "total": len(results),
            "categories": categories,
            "hint": "工具和意图都可通过ExecuteTool调用"
        }


class ExecuteToolTool(llm.Tool):
    """万能工具执行器 - 通过此工具调用任何已注册的工具"""
    name = "ExecuteTool"
    description = "执行指定工具。先用GetToolIndex查询可用工具，然后用此工具执行。参数: tool_name(工具名), args(工具参数字典)"
    parameters = vol.Schema({
        vol.Required("tool_name"): str,
        vol.Optional("args", default={}): dict,
    })

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> JsonObjectType:
        tool_name = tool_input.tool_args.get("tool_name", "")
        args = tool_input.tool_args.get("args", {})
        
        tool_map = {
            "ServiceCall": ServiceCallTool,
            "EntityQuery": EntityQueryTool,
            "StockQuery": StockQueryTool,
            "WebSearch": WebSearchTool,
            "BatchControl": BatchControlTool,
            "AreaDevices": AreaDevicesTool,
            "HistoryQuery": HistoryQueryTool,
            "Automation": AutomationTool,
            "ExecutePython": ExecutePythonTool,
            "NewsSearch": NewsSearchTool,
            "DeepWebSearch": DeepWebSearchTool,
            "UrlFetch": UrlFetchTool,
            "ZhihuHot": ZhihuHotTool,
            "ListServices": ListServicesTool,
            "ScriptExecute": ScriptExecuteTool,
            "Notify": NotifyTool,
            "FireEvent": FireEventTool,
            "InjectJS": InjectJSTool,
            "FrontendControl": FrontendControlTool,
            "Dashboard": DashboardTool,
            "HAControl": HAControlTool,
            "HACS": HACSTool,
            "ThinkContinue": ThinkContinueTool,
            "ExecuteChain": ExecuteChainTool,
            "AnalyzeIntent": AnalyzeIntentTool,
            "SystemControl": SystemControlTool,
            "ConversationMemory": ConversationMemoryTool,
            "TextCompress": TextCompressTool,
            "RolePlay": RolePlayTool,
            "GetConversationHistory": GetConversationHistoryTool,
            "ParallelToolCall": ParallelToolCallTool,
            "AgentLoop": AgentLoopTool,
            "GetSystemIndex": GetSystemIndexTool,
            "SetConversationState": SetConversationStateTool,
            "ValidateService": ValidateServiceTool,
            "ServiceHelp": ServiceHelpTool,
            "SmartDiscovery": SmartDiscoveryTool,
            "GetLiveContext": GetLiveContextTool,
        }
        
        if tool_name in tool_map:
            try:
                tool_instance = tool_map[tool_name]()
                fake_input = llm.ToolInput(
                    tool_name=tool_name,
                    tool_args=args,
                )
                result = await tool_instance.async_call(hass, fake_input, llm_context)
                _LOGGER.info(f"ExecuteTool: {tool_name} 执行成功")
                return result
            except Exception as e:
                import traceback
                _LOGGER.error(f"ExecuteTool: {tool_name} 执行失败: {e}\n{traceback.format_exc()}")
                return {"success": False, "error": str(e), "tool_name": tool_name}
        
        from homeassistant.helpers import intent as intent_module
        registered_intents = {h.intent_type: h for h in intent_module.async_get(hass)}
        
        if tool_name in registered_intents:
            try:
                slots = {k: {"value": v} for k, v in args.items()}
                intent_obj = intent_module.Intent(
                    hass=hass,
                    platform="ha_crack",
                    intent_type=tool_name,
                    slots=slots,
                    text_input=f"ExecuteTool: {tool_name}",
                    context=None,
                    language="zh",
                    assistant=llm_context.assistant if llm_context else "conversation",
                )
                handler = registered_intents[tool_name]
                response = await handler.async_handle(intent_obj)
                speech = response.speech.get("plain", {}).get("speech", "") if response.speech else ""
                _LOGGER.info(f"ExecuteTool: Intent {tool_name} 执行成功")
                return {"success": True, "response": speech, "intent": tool_name}
            except Exception as e:
                import traceback
                _LOGGER.error(f"ExecuteTool: Intent {tool_name} 执行失败: {e}\n{traceback.format_exc()}")
                return {"success": False, "error": str(e), "intent": tool_name}
        
        all_available = list(tool_map.keys()) + list(registered_intents.keys())
        return {
            "success": False,
            "error": f"未知工具/意图: {tool_name}",
            "available_tools": list(tool_map.keys())[:10],
            "available_intents": list(registered_intents.keys())[:10],
            "hint": "使用 GetToolIndex 查询所有可用工具"
        }

CUSTOM_API_ID = "ha_crack_enhanced"


@dataclass(slots=True, kw_only=True)
class EnhancedAPI(llm.API):
    id: str = CUSTOM_API_ID
    name: str = "HA Crack Enhanced API"

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        from ..const import HASS_LLM_SYSTEM_PROMPT
        from datetime import datetime, timezone, timedelta
        
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        current_datetime = now.strftime("今天是 %Y年%m月%d日 %A，当前时间 %H:%M:%S (北京时间)")
        
        minimal_tools = [
            ThinkContinueTool(),
            GetToolIndexTool(),
            ExecuteToolTool(),
            GetLiveContextTool(),
        ]
        
        prompt = f"""{HASS_LLM_SYSTEM_PROMPT.format(current_datetime=current_datetime)}

{current_datetime}

## 工具使用流程
1. 用 GetToolIndex 查询可用工具
2. 用 ExecuteTool 执行具体工具
3. GetLiveContext 可直接调用获取设备状态
"""
        return llm.APIInstance(api=self, api_prompt=prompt, llm_context=llm_context, tools=minimal_tools)


_unregister_api = None


@callback
def async_register_enhanced_api(hass: HomeAssistant) -> None:
    global _unregister_api
    if _unregister_api:
        return
    try:
        api = EnhancedAPI(hass=hass)
        _unregister_api = llm.async_register_api(hass, api)
        _LOGGER.info(f"Registered enhanced LLM API: {CUSTOM_API_ID}")
    except Exception as e:
        _LOGGER.error(f"Failed to register enhanced LLM API: {e}")


@callback
def async_unregister_enhanced_api() -> None:
    global _unregister_api
    if _unregister_api:
        _unregister_api()
        _unregister_api = None
        _LOGGER.info("Unregistered enhanced LLM API")


async def async_setup_llm_hook(hass: HomeAssistant) -> None:
    async_register_enhanced_api(hass)
    hass.data.setdefault("ha_crack", {})["llm_api_id"] = CUSTOM_API_ID
    _patch_assist_api_prompt(hass)
    _patch_tool_call_tracking(hass)


def _patch_assist_api_prompt(hass: HomeAssistant) -> None:
    from homeassistant.helpers import llm as llm_module
    from ..const import HASS_LLM_SYSTEM_PROMPT
    
    if hasattr(llm_module, '_ha_crack_patched'):
        return
    
    original_get_api_prompt = llm_module.AssistAPI._async_get_api_prompt
    original_get_tools = llm_module.AssistAPI._async_get_tools
    
    @callback
    def patched_get_api_prompt(self, llm_context, exposed_entities):
        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        current_datetime = now.strftime("今天是 %Y年%m月%d日 %A，当前时间 %H:%M:%S (北京时间)")
        
        ha_crack_prompt = f"""{HASS_LLM_SYSTEM_PROMPT.format(current_datetime=current_datetime)}"""
        original_prompt = original_get_api_prompt(self, llm_context, exposed_entities)
        
        return ha_crack_prompt + "\n" + original_prompt
    
    @callback
    def patched_get_tools(self, llm_context, exposed_entities):
        original_tools = original_get_tools(self, llm_context, exposed_entities)
        
        minimal_tools = [
            ThinkContinueTool(),
            GetToolIndexTool(),
            ExecuteToolTool(),
        ]
        
        live_context = [t for t in original_tools if t.name == "GetLiveContext"]
        
        final_tools = minimal_tools + live_context
        
        _LOGGER.info(f"极简工具模式: {len(final_tools)} 个工具 (原始: {len(original_tools)})")
        
        return final_tools
    
    llm_module.AssistAPI._async_get_api_prompt = patched_get_api_prompt
    llm_module.AssistAPI._async_get_tools = patched_get_tools
    llm_module._ha_crack_patched = True
    _LOGGER.info("已彻底劫持AssistAPI系统提示词和工具列表")


def _patch_tool_call_tracking(hass: HomeAssistant) -> None:
    """Hook工具调用，追踪每次调用的success状态，用于智能fallback"""
    from homeassistant.helpers import llm as llm_module
    
    if hasattr(llm_module.APIInstance, '_ha_crack_tool_tracking'):
        return
    
    original_async_call_tool = llm_module.APIInstance.async_call_tool
    
    async def tracked_async_call_tool(self, tool_input):
        """包装工具调用，追踪结果"""
        tool_results = hass.data.setdefault("ha_crack_tool_results", [])
        
        try:
            result = await original_async_call_tool(self, tool_input)
            
            success = True
            error = None
            result_summary = None
            
            if isinstance(result, dict):
                if "success" in result:
                    success = result.get("success", True)
                    error = result.get("error")
                elif "response_type" in result:
                    success = result.get("response_type") != "error"
                    if result.get("data", {}).get("failed"):
                        success = False
                        error = f"Failed targets: {result['data']['failed']}"
                
                result_summary = {k: v for k, v in result.items() if k in ["success", "message", "response", "state", "count", "response_type"]}
                if len(str(result_summary)) > 300:
                    result_summary = str(result_summary)[:300] + "..."
            
            tool_record = {
                "tool_name": tool_input.tool_name,
                "tool_args": tool_input.tool_args,
                "success": success,
                "error": error,
                "result": result_summary,
            }
            tool_results.append(tool_record)
            
            if not success:
                _LOGGER.debug(f"工具调用失败: {tool_input.tool_name} - {error or 'unknown'}")
            
            return result
        except Exception as e:
            tool_results.append({
                "tool_name": tool_input.tool_name,
                "tool_args": tool_input.tool_args,
                "success": False,
                "error": str(e),
                "result": None,
            })
            raise
    
    llm_module.APIInstance.async_call_tool = tracked_async_call_tool
    llm_module.APIInstance._ha_crack_tool_tracking = True
    _LOGGER.info("已启用工具调用追踪")
