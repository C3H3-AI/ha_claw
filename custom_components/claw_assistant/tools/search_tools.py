from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

from ..runtime import mark_tool_called
from ..services.web_formatter import format_search_results_text, prepare_web_text_for_ai
from ..services.web_search import WebSearch
from ..services.stock_api import StockAPI, format_stock_data

_LOGGER = logging.getLogger(__name__)


class WebSearchTool(llm.Tool):
    name = "WebSearch"
    description = "General-purpose web search for real-time information: news, finance flashes, weather, entertainment, tech, sports, etc. Queries both Baidu and Bing and merges the results. Use this for ALL news and current-event lookups."
    parameters = vol.Schema({
        vol.Required("query"): str,
        vol.Optional("num_results", default=3): int,
        vol.Optional("engine", default=""): str,
    })

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> JsonObjectType:
        query = tool_input.tool_args.get("query", "")
        num = tool_input.tool_args.get("num_results", 3)
        engine = tool_input.tool_args.get("engine", "")
        mark_tool_called(hass, "WebSearch")
        try:
            async with WebSearch() as ws:
                results = await ws.search(query, num, engine=engine)
                if not results:
                    return {"success": False, "error": "No search results found"}

                return {
                    "success": True,
                    "count": len(results),
                    "results": format_search_results_text(
                        query,
                        results[:num],
                        engine_label=engine or "merged",
                        max_total_chars=3200,
                        max_chars_per_result=900,
                    ),
                }
        except Exception as e:
            _LOGGER.error(f"WebSearchTool error: {e}")
            return {"success": False, "error": str(e)}


class UrlFetchTool(llm.Tool):
    name = "UrlFetch"
    description = "Fetch URL content. Use this to read web pages, APIs, and similar resources."
    parameters = vol.Schema({
        vol.Required("url"): str,
        vol.Optional("max_length", default=2000): int,
    })

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> JsonObjectType:
        url = tool_input.tool_args.get("url", "")
        max_len = tool_input.tool_args.get("max_length", 2000)
        mark_tool_called(hass, "UrlFetch")
        try:
            async with WebSearch() as ws:
                result = await ws.fetch_url_content(url)
                if result and result.content:
                    processed = prepare_web_text_for_ai(
                        result.content,
                        max_chars=max_len,
                    )
                    return {
                        "success": True,
                        "title": result.title,
                        "content": processed,
                        "compressed": len(processed) < len(result.content),
                        "ratio": (
                            f"{len(processed) / len(result.content):.1%}"
                            if result.content
                            else "100.0%"
                        ),
                    }
                return {"success": False, "error": "Failed to fetch URL"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class StockQueryTool(llm.Tool):
    name = "StockQuery"
    description = """Use this tool for stocks, funds, China A-shares, US equities, and Hong Kong market quotes. Do not use WebSearch for quote lookup.

Typical triggers: stock, quote, market, A-shares, US stocks, Hong Kong stocks, funds, gain/loss, Tesla, Apple, Tencent, and similar.

Common code examples:
- China A-shares: 600519, 000001, 600036
- US stocks: TSLA, AAPL, NVDA, MSFT
- Hong Kong stocks: 00700, 09988
- Funds: 6-digit code

Returns real-time price, change, change percent, open, previous close, high, low, volume, P/E ratio, and related data."""
    parameters = vol.Schema({
        vol.Required("codes"): str,
    })

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> JsonObjectType:
        codes_str = tool_input.tool_args.get("codes", "")
        codes = [c.strip() for c in codes_str.replace("，", ",").split(",") if c.strip()]

        if not codes:
            return {"success": False, "error": "Please provide one or more stock or fund codes"}

        mark_tool_called(hass, "StockQuery")

        _LOGGER.info(f"StockQueryTool: querying {codes}")

        try:
            async with StockAPI() as api:
                if len(codes) == 1:
                    data = await api.query_stock(codes[0])
                    if data:
                        return {
                            "success": True,
                            "count": 1,
                            "data": format_stock_data(data),
                            "raw": {
                                "code": data.code,
                                "name": data.name,
                                "price": data.price,
                                "change": data.change,
                                "change_percent": data.change_percent,
                                "market": data.market,
                            }
                        }
                    return {"success": False, "error": f"Stock or fund not found: {codes[0]}"}
                else:
                    results = await api.query_stocks(codes)
                    if results:
                        formatted = [format_stock_data(d) for d in results]
                        return {
                            "success": True,
                            "count": len(results),
                            "data": "\n\n---\n\n".join(formatted),
                        }
                    return {"success": False, "error": "No stock or fund data found"}
        except Exception as e:
            _LOGGER.error(f"StockQueryTool error: {e}")
            return {"success": False, "error": str(e)}
