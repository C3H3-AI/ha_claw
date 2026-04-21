from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .web_search import SearchResult

_TRUNCATION_MARKER = "\n...[truncated]"
_NOISE_LINE_PATTERNS = (
    r"^(首页|返回首页|登录|注册|关于我们|联系我们|网站地图)$",
    r"^(首页|返回首页|登录|注册).*[|｜].*(登录|注册|首页).*$",
    r"^(上一篇|下一篇|相关推荐|热门文章|相关文章)$",
    r"^(分享|转发|收藏|点赞|评论|扫码下载|下载APP).*$",
    r"^(Copyright|版权所有|免责声明|隐私政策|Cookie).*$",
    r"^(ICP备|京公网安备|网络文化经营许可证).*$",
)


def _looks_like_noise_line(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    if len(lowered) < 4:
        return True
    if lowered.count("http") >= 2:
        return True
    if lowered.count("|") > 3 or lowered.count("/") > 6:
        return True
    if re.fullmatch(r"[\d\s:/\-\.]+", lowered):
        return True
    return any(
        re.match(pattern, text.strip(), flags=re.IGNORECASE)
        for pattern in _NOISE_LINE_PATTERNS
    )


def prepare_web_text_for_ai(text: str, *, max_chars: int) -> str:

    if not text:
        return ""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    seen: set[str] = set()
    paragraphs: list[str] = []
    for block in re.split(r"\n{2,}", normalized):
        lines: list[str] = []
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or _looks_like_noise_line(line):
                continue
            line = re.sub(r"\s{2,}", " ", line)
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
        if lines:
            paragraphs.append("\n".join(lines))

    cleaned = "\n\n".join(paragraphs).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned

    budget = max(max_chars - len(_TRUNCATION_MARKER), 0)
    selected: list[str] = []
    current_length = 0
    for paragraph in paragraphs:
        paragraph_len = len(paragraph)
        if current_length + paragraph_len + (2 if selected else 0) <= budget:
            selected.append(paragraph)
            current_length += paragraph_len + (2 if selected[:-1] else 0)
            continue

        sentences = re.split(r"(?<=[.!?。！？])\s+", paragraph)
        partial: list[str] = []
        partial_len = current_length
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            extra = len(sentence) + (1 if partial else 0)
            if partial_len + extra > budget:
                break
            partial.append(sentence)
            partial_len += extra
        if partial:
            selected.append(" ".join(partial))
        break

    result = "\n\n".join(selected).strip()
    if not result:
        result = cleaned[:budget].rstrip()
    return result + _TRUNCATION_MARKER


def format_search_results_text(
    query: str,
    results: list[SearchResult],
    *,
    engine_label: str,
    max_total_chars: int = 2800,
    max_chars_per_result: int = 800,
) -> str:

    if not results:
        return "No relevant results found."

    output: list[str] = []

    direct_url_results = [r for r in results if r.metadata.get("source") == "direct_url"]
    if direct_url_results:
        output.append("Direct URL extraction results:")
        for i, result in enumerate(direct_url_results, 1):
            output.append(f"\n[URL {i}]")
            output.append(f"Title: {result.title}")
            output.append(f"Source: {result.url}")
            if result.content:
                content = prepare_web_text_for_ai(
                    result.content,
                    max_chars=max_chars_per_result,
                )
                if content:
                    output.append(f"Content:\n{content}")
            elif result.snippet:
                note = prepare_web_text_for_ai(
                    result.snippet,
                    max_chars=min(220, max_chars_per_result),
                )
                if note:
                    output.append(f"Note: {note}")
            output.append("-" * 30)
        rendered = "\n".join(output)
        if len(rendered) > max_total_chars:
            return rendered[: max_total_chars - len(_TRUNCATION_MARKER)].rstrip() + _TRUNCATION_MARKER
        return rendered

    search_results = list(results)

    output.append(f"Search Engine: {engine_label}")
    output.append(f"Query: '{query}'")
    output.append(f"Results: {len(results)}")
    output.append("-" * 50)

    if search_results:
        output.append("\nWeb search results:")
        for i, result in enumerate(search_results, 1):
            output.append(f"\n[{i}]")
            output.append(f"Title: {result.title}")
            output.append(f"Source: {result.url}")
            if result.snippet:
                cleaned_snippet = prepare_web_text_for_ai(
                    result.snippet,
                    max_chars=min(220, max_chars_per_result // 3),
                )
                if cleaned_snippet:
                    output.append(f"Description: {cleaned_snippet}")
            if result.content:
                content = prepare_web_text_for_ai(
                    result.content,
                    max_chars=max_chars_per_result,
                )
                if content:
                    output.append(f"Content preview:\n{content}")
            output.append("-" * 50)

    rendered = "\n".join(output)
    if len(rendered) > max_total_chars:
        return rendered[: max_total_chars - len(_TRUNCATION_MARKER)].rstrip() + _TRUNCATION_MARKER
    return rendered
