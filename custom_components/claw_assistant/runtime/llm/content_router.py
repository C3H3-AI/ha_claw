from __future__ import annotations

from enum import Enum
import json


class ContentType(str, Enum):
    JSON = "json"
    CODE = "code"
    LOG = "log"
    TEXT = "text"
    UNKNOWN = "unknown"


_CODE_INDICATORS = (
    "def ", "class ", "function ", "import ", "const ", "let ",
    "var ", "func ", "fn ", "pub ", "package ", "#include", "=>",
)
_LOG_INDICATORS = ("ERROR", "WARN", "INFO", "DEBUG", "FATAL", "Traceback")


def detect_content_type(text: str) -> ContentType:
    if not text or not text.strip():
        return ContentType.UNKNOWN
    stripped = text.strip()

    if stripped.startswith(("{", "[")):
        try:
            json.loads(stripped)
            return ContentType.JSON
        except (json.JSONDecodeError, ValueError):
            pass

    lines = stripped.splitlines()
    probe = "\n".join(lines[:40] + lines[-20:])
    if any(ind in probe for ind in _LOG_INDICATORS):
        return ContentType.LOG
    if any(ind in probe for ind in _CODE_INDICATORS):
        return ContentType.CODE
    return ContentType.TEXT


def extract_json_schema(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: extract_json_schema(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [extract_json_schema(obj[0])] if obj else []
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, int):
        return "int"
    if isinstance(obj, float):
        return "float"
    if isinstance(obj, str):
        return "str"
    if obj is None:
        return "null"
    return "unknown"


class SmartCrusher:

    def __init__(
        self,
        *,
        sample_items: int = 3,
        str_max: int = 80,
        max_depth: int = 4,
    ) -> None:
        self.sample_items = sample_items
        self.str_max = str_max
        self.max_depth = max_depth

    def can_handle(self, text: str) -> bool:
        return detect_content_type(text) == ContentType.JSON

    def compress(self, text: str) -> str | None:
        stripped = (text or "").strip()
        try:
            data = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(data, list):
            return self._crush_list(data)
        if isinstance(data, dict):
            return self._crush_dict(data)
        return self._dumps(self._shrink(data, 0))

    def _crush_list(self, data: list) -> str:
        n = len(data)
        if n == 0:
            return "JSON array: empty"
        dict_items = [x for x in data if isinstance(x, dict)]
        header = f"JSON array: {n} item(s)"
        if dict_items and len(dict_items) == n:
            keys: list[str] = []
            seen: set[str] = set()
            for item in dict_items[: self.sample_items * 2]:
                for k in item:
                    if k not in seen:
                        seen.add(k)
                        keys.append(str(k))
            header += f", object keys=[{', '.join(keys)}]"
        samples = [self._shrink(x, 1) for x in data[: self.sample_items]]
        body = self._dumps(samples)
        remaining = n - min(self.sample_items, n)
        suffix = f"\n... +{remaining} more item(s)" if remaining > 0 else ""
        return f"{header}\nsamples: {body}{suffix}"

    def _crush_dict(self, data: dict) -> str:
        keys = [str(k) for k in data]
        header = f"JSON object: keys=[{', '.join(keys)}]"
        body = self._dumps(self._shrink(data, 0))
        return f"{header}\n{body}"

    def _shrink(self, obj: object, depth: int) -> object:
        if depth >= self.max_depth:
            if isinstance(obj, dict):
                return f"{{...{len(obj)} keys...}}"
            if isinstance(obj, list):
                return f"[...{len(obj)} items...]"
        if isinstance(obj, str):
            if len(obj) > self.str_max:
                return obj[: self.str_max] + f"…(+{len(obj) - self.str_max} chars)"
            return obj
        if isinstance(obj, dict):
            return {k: self._shrink(v, depth + 1) for k, v in obj.items()}
        if isinstance(obj, list):
            if len(obj) > self.sample_items:
                head = [self._shrink(v, depth + 1) for v in obj[: self.sample_items]]
                head.append(f"...+{len(obj) - self.sample_items} more")
                return head
            return [self._shrink(v, depth + 1) for v in obj]
        return obj

    @staticmethod
    def _dumps(obj: object) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(obj)


def _crush_text(text: str, max_chars: int, *, tail_bias: bool) -> str:
    if len(text) <= max_chars:
        return text
    if tail_bias:
        head = max_chars // 3
        tail = max_chars - head
    else:
        head = (max_chars * 2) // 3
        tail = max_chars - head
    omitted = len(text) - head - tail
    return f"{text[:head]}\n...[{omitted:,} chars omitted]...\n{text[-tail:]}"


class ContentRouter:

    def __init__(self, *, smart_crusher: SmartCrusher | None = None) -> None:
        self.smart_crusher = smart_crusher or SmartCrusher()

    def compress(self, text: str, *, max_chars: int = 800) -> tuple[str, dict]:
        original = text or ""
        ctype = detect_content_type(original)
        meta: dict[str, object] = {
            "content_type": ctype.value,
            "original_chars": len(original),
        }

        if ctype == ContentType.JSON:
            crushed = self.smart_crusher.compress(original)
            if crushed is not None:
                if len(crushed) > max_chars:
                    crushed = _crush_text(crushed, max_chars, tail_bias=False)
                meta["compressed_chars"] = len(crushed)
                return crushed, meta

        tail_bias = ctype == ContentType.LOG
        out = _crush_text(original, max_chars, tail_bias=tail_bias)
        meta["compressed_chars"] = len(out)
        return out, meta


_router: ContentRouter | None = None


def get_content_router() -> ContentRouter:
    global _router
    if _router is None:
        _router = ContentRouter()
    return _router
