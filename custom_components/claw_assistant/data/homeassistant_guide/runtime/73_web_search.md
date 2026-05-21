# Web Search Tools

## WebSearch

Search the web.

| Param | Description |
|-------|-------------|
| query | Search query |
| num_results | Max results (default 5) |
| engine | google/bing/baidu/bing_cn (auto if empty) |

```json
{"query": "Home Assistant automation examples"}
```

Returns titles + snippets. Use UrlFetch for full page.

## UrlFetch

Fetch URL content (chunk 0).

```json
{"url": "https://example.com/page"}
```

Returns doc_id for WebReadChunk.

## WebReadChunk

Read more chunks of fetched page.

```json
{"doc_id": "xxx", "position": 1}
```

## StockQuery

Query stock/fund quotes.

```json
{"codes": "TSLA,AAPL"}
{"codes": "600519,000858"}
```

## Workflow

```
1. WebSearch query="..."
   → Get titles, snippets, URLs

2. UrlFetch url="interesting_url"
   → Get chunk 0, doc_id

3. WebReadChunk doc_id="xxx" position=1
   → Get more content
```
