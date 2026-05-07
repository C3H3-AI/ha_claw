from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
import random
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from bs4 import BeautifulSoup
from urllib.parse import unquote

from .web_fetcher import WebPageFetcher
from .web_formatter import format_search_results_text

_LOGGER = logging.getLogger(__name__)

@dataclass
class SearchResult:
    title: str = ""
    url: str = ""
    snippet: str = ""
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

_CN_TIMEZONES = {"Asia/Shanghai", "Asia/Chongqing", "Asia/Urumqi", "Asia/Harbin", "PRC"}

ENGINES = {
    "bing": {"url": "https://www.bing.com/search", "param": "q", "sel": ".b_algo", "title": "h2 a", "link": "h2 a", "desc": ".b_caption p"},
    "baidu": {"url": "https://www.baidu.com/s", "param": "wd", "sel": ".result.c-container, .c-container", "title": "h3 a, .t a", "link": "h3 a, .t a", "desc": ".c-abstract, .c-span-last"},
    "bing_cn": {"url": "https://cn.bing.com/search", "param": "q", "sel": ".b_algo", "title": "h2 a", "link": "h2 a", "desc": ".b_caption p"},
}
_ALL_ENGINES = {"google", *ENGINES}
SEARCH_ENGINES = list(_ALL_ENGINES)


def _is_cn(hass=None) -> bool:
    if hass is None:
        return False
    tz = str(getattr(hass.config, "time_zone", "") or "")
    return tz in _CN_TIMEZONES


def _default_engines(hass=None) -> list[str]:
    if _is_cn(hass):
        return ["baidu", "bing_cn"]
    return ["google", "bing"]

BLOCKED_DOMAINS = {"zhihu.com", "zhihu.cn"}
UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
]


def _extract_required_domains(query: str) -> set[str]:
    matches = re.findall(r"site:([^\s]+)", query, flags=re.IGNORECASE)
    domains: set[str] = set()
    for match in matches:
        domain = match.strip().lower().rstrip("/.")
        if domain.startswith("www."):
            domain = domain[4:]
        if domain:
            domains.add(domain)
    return domains


def _matches_required_domains(url: str, required_domains: set[str]) -> bool:
    if not required_domains:
        return True
    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        return False
    if domain.startswith("www."):
        domain = domain[4:]
    return any(domain == required or domain.endswith(f".{required}") for required in required_domains)

class RateLimiter:
    def __init__(self, max_calls: int = 50, period: int = 60):
        self.max_calls, self.period, self.calls, self.lock = max_calls, period, [], asyncio.Lock()

    async def acquire(self):
        while True:
            async with self.lock:
                now = datetime.now()
                self.calls = [
                    timestamp
                    for timestamp in self.calls
                    if (now - timestamp).total_seconds() < self.period
                ]
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return
                wait_seconds = max(
                    self.period - (now - min(self.calls)).total_seconds(),
                    0,
                ) + 0.1

            await asyncio.sleep(wait_seconds)

class WebSearch:
    def __init__(self, api_key: Optional[str] = None, hass=None):
        self.api_key = api_key
        self._hass = hass
        self.timeout = ClientTimeout(total=30, connect=10, sock_read=10)
        self.connector: TCPConnector | None = None
        self.session = None
        self.cache = {}
        self.cache_ttl = 3600
        self.blocked_domains = BLOCKED_DOMAINS.copy()
        self.rate_limiters = {e: RateLimiter() for e in ENGINES}
        self.page_fetcher: WebPageFetcher | None = None

    def add_blocked_domain(self, domain: str) -> None:
        self.blocked_domains.add(domain.lower())

    def remove_blocked_domain(self, domain: str) -> None:
        self.blocked_domains.discard(domain.lower())

    def is_domain_blocked(self, url: str) -> bool:
        if not url:
            return True
        try:
            domain = urlparse(url).netloc.lower()
            return any(blocked in domain for blocked in self.blocked_domains)
        except:
            return True

    async def __aenter__(self):
        if self.session is None or self.session.closed:
            self.connector = TCPConnector(limit=10, force_close=True, ssl=False)
            self.session = ClientSession(
                timeout=self.timeout,
                connector=self.connector,
                headers=self._get_headers()
            )
        self.page_fetcher = WebPageFetcher(
            self.session,
            blocked_domains=self.blocked_domains,
            get_headers=self._get_headers,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.session.closed:
            await self.session.close()
            await asyncio.sleep(0.25)
        self.session = None
        self.page_fetcher = None
        self.connector = None

    def _get_headers(self) -> Dict[str, str]:
        lang = "zh-CN,zh;q=0.9,en;q=0.8" if _is_cn(self._hass) else "en-US,en;q=0.9"
        return {
            "User-Agent": self._get_random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": lang,
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }

    def _get_random_ua(self) -> str:
        return random.choice(UA_LIST)

    async def close(self):
        await self.__aexit__(None, None, None)

    def _get_cache_key(self, query: str, engine: str) -> str:
        return f"{engine}:{query}"

    def _get_cached_results(self, query: str, engine: str) -> Optional[List[SearchResult]]:
        key = self._get_cache_key(query, engine)
        if key in self.cache:
            ts, results = self.cache[key]
            if (datetime.now() - ts).seconds < self.cache_ttl: return results
            del self.cache[key]
        return None

    def _cache_results(self, query: str, engine: str, results: List[SearchResult]):
        self.cache[self._get_cache_key(query, engine)] = (datetime.now(), results)

    async def _search_google(self, query: str, num: int = 5) -> List[SearchResult]:
        await self.rate_limiters.get("google", RateLimiter()).acquire()
        cached = self._get_cached_results(query, "google")
        if cached:
            return cached
        results = []
        required_domains = _extract_required_domains(query)
        try:
            from requests import get as sync_get
            lang = "zh-CN,zh;q=0.9,en;q=0.8" if _is_cn(self._hass) else "en-US,en;q=0.9"
            resp = await asyncio.to_thread(
                lambda: sync_get(
                    url="https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={
                        "User-Agent": self._get_random_ua(),
                        "Accept": "text/html",
                        "Accept-Language": lang,
                    },
                    timeout=30,
                )
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.select(".result"):
                title_el = item.select_one(".result__a")
                desc_el = item.select_one(".result__snippet")
                if not title_el:
                    continue
                href = title_el.get("href", "")
                if href.startswith("//duckduckgo.com/l/?uddg="):
                    href = unquote(href.split("uddg=")[1].split("&")[0])
                if not href or href.startswith("/"):
                    continue
                if self.page_fetcher and self.page_fetcher.is_domain_blocked(href):
                    continue
                if not _matches_required_domains(href, required_domains):
                    continue
                title = title_el.get_text(strip=True)
                desc = desc_el.get_text(strip=True) if desc_el else ""
                results.append(SearchResult(
                    title=title, url=href, snippet=desc,
                    metadata={"engine": "google", "timestamp": datetime.now().isoformat()},
                ))
                if len(results) >= num:
                    break
            if results:
                self._cache_results(query, "google", results)
                _LOGGER.debug("Google(startpage): %d results", len(results))
        except Exception as e:
            _LOGGER.error("Google search error: %s", e, exc_info=True)
        return results

    async def _search_engine(self, query: str, engine: str, num: int = 5) -> List[SearchResult]:
        if engine == "google":
            return await self._search_google(query, num)
        cfg = ENGINES.get(engine)
        if not cfg: return []
        await self.rate_limiters.get(engine, RateLimiter()).acquire()
        cached = self._get_cached_results(query, engine)
        if cached: return cached
        results = []
        required_domains = _extract_required_domains(query)
        try:
            from urllib.parse import quote
            url = f"{cfg['url']}?{cfg['param']}={quote(query)}"
            _LOGGER.debug("Search engine request: %s - %s", engine, url)
            page = await self.page_fetcher.make_request(url, headers=self._get_headers())
            if not page:
                return []
            _LOGGER.debug("%s response length: %s", engine, len(page.text))
            soup = BeautifulSoup(page.text, "html.parser")

            for selector in cfg["sel"].split(", "):
                items = soup.select(selector)[:num]
                if items:
                    _LOGGER.debug("%s found %d results with selector %s", engine, len(items), selector)
                    break
            else:
                items = []

            for item in items:
                title_el = None
                for ts in cfg["title"].split(", "):
                    title_el = item.select_one(ts)
                    if title_el: break

                link_el = None
                for ls in cfg["link"].split(", "):
                    link_el = item.select_one(ls)
                    if link_el: break

                desc_el = None
                for ds in cfg["desc"].split(", "):
                    desc_el = item.select_one(ds)
                    if desc_el: break

                if not title_el or not link_el: continue
                href = link_el.get("href", "")
                if not href: continue
                if href.startswith("/"): href = f"https://{urlparse(cfg['url']).netloc}{href}"
                if self.page_fetcher.is_domain_blocked(href): continue
                if not _matches_required_domains(href, required_domains):
                    continue

                title = title_el.get_text(strip=True)
                snippet = desc_el.get_text(strip=True) if desc_el else ""

                if title and href:
                    results.append(SearchResult(
                        title=title,
                        url=href,
                        snippet=snippet,
                        metadata={"engine": engine, "timestamp": datetime.now().isoformat()}
                    ))
                    _LOGGER.debug("Found result: %s... -> %s...", title[:30], href[:50])

            if results:
                self._cache_results(query, engine, results)
                _LOGGER.debug("%s successfully fetched %d results", engine, len(results))
        except Exception as e:
            _LOGGER.error(f"{engine} search error: {e}", exc_info=True)
        return results

    async def fetch_url_content(self, url: str) -> Optional[SearchResult]:
        return await self.page_fetcher.fetch_url_content(url, SearchResult)

    async def process_direct_urls(self, query: str) -> List[SearchResult]:
        urls = self.page_fetcher.extract_urls_from_query(query)
        if not urls:
            return []

        _LOGGER.debug("Extracted URLs from query: %s", urls)
        results = []

        for url in urls:
            result = await self.fetch_url_content(url)
            if result:
                results.append(result)

        return results

    async def _search_with_open_session(
        self,
        query: str,
        num_results: int,
        engine: str,
        fetch_content: bool = True,
    ) -> List[SearchResult]:
        try:
            direct_url_results = await self.process_direct_urls(query)
            if direct_url_results:
                _LOGGER.debug("Successfully processed direct URLs, got %d results", len(direct_url_results))
                return direct_url_results
        except Exception as e:
            _LOGGER.error("Failed to process direct URLs: %s", e)

        if engine and engine in _ALL_ENGINES:
            engines_to_try = [engine]
        else:
            engines_to_try = _default_engines(self._hass)
        _LOGGER.debug("Search: %s (engines: %s)", query, engines_to_try)
        engine_tasks = [
            self._search_engine(query, eng, num_results) for eng in engines_to_try
        ]
        engine_outputs = await asyncio.gather(*engine_tasks, return_exceptions=True)
        seen_urls: set[str] = set()
        all_results: List[SearchResult] = []
        for eng, output in zip(engines_to_try, engine_outputs):
            if isinstance(output, Exception):
                _LOGGER.error("%s search error: %s", eng, output)
                continue
            for result in output or []:
                key = result.url or result.title
                if not key or key in seen_urls:
                    continue
                seen_urls.add(key)
                all_results.append(result)

        if not all_results and engine and engine in _ALL_ENGINES:
            fallback = [e for e in _default_engines(self._hass) if e != engine]
            if fallback:
                _LOGGER.debug("Fallback from %s to %s", engine, fallback)
                fb_tasks = [self._search_engine(query, e, num_results) for e in fallback]
                fb_outputs = await asyncio.gather(*fb_tasks, return_exceptions=True)
                for eng, output in zip(fallback, fb_outputs):
                    if isinstance(output, Exception):
                        continue
                    for result in output or []:
                        key = result.url or result.title
                        if not key or key in seen_urls:
                            continue
                        seen_urls.add(key)
                        all_results.append(result)

        if fetch_content and all_results:
            content_tasks = []
            valid_results = []
            for result in all_results:
                if result.url:
                    content_tasks.append(self.page_fetcher.extract_content_with_response(result.url))
                    valid_results.append(result)

            if content_tasks:
                contents = await asyncio.gather(*content_tasks, return_exceptions=True)
                for result, content_tuple in zip(valid_results, contents):
                    try:
                        if isinstance(content_tuple, tuple):
                            _, extracted = content_tuple
                            result.metadata["extraction_strategy"] = extracted.strategy
                            if extracted.metadata.get("requires_browser"):
                                result.metadata["requires_browser"] = True
                            if extracted.content:
                                result.content = extracted.content
                                result.metadata["has_content"] = True
                            else:
                                result.metadata["has_content"] = False
                        else:
                            result.metadata["has_content"] = False
                    except Exception:
                        result.metadata["has_content"] = False

        return all_results

    async def search(self, query: str, num_results: int = 5, engine: str = "", fetch_content: bool = True, **_legacy: Any) -> List[SearchResult]:
        if self.session is not None and not self.session.closed and self.page_fetcher is not None:
            return await self._search_with_open_session(query, num_results, engine, fetch_content=fetch_content)

        async with self:
            return await self._search_with_open_session(query, num_results, engine, fetch_content=fetch_content)

    async def get_search_results_text(self, query: str, num_results: int = 10, **_legacy: Any) -> str:
        results = await self.search(query, num_results)
        engine_label = "manual"
        for result in results:
            engine_label = str(result.metadata.get("engine") or result.metadata.get("source") or engine_label)
            if engine_label:
                break
        return format_search_results_text(query, results, engine_label=engine_label)
