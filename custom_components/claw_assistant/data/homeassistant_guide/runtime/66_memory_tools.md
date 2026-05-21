# Memory Tools

## ConversationMemory - Simple Key-Value

For user preferences and short facts. Auto-injected into prompt.

| Action | Params |
|--------|--------|
| save | key, value |
| get | key |
| list | - |
| clear | - |

```json
{"action": "save", "key": "user_name", "value": "张三"}
{"action": "get", "key": "user_name"}
```

## MemoryGraph - Knowledge Graph

For decisions, bug fixes, causal links needing graph traversal.

| Action | Params |
|--------|--------|
| recall | query, kinds?, limit?, expand? |
| remember | kind, title, body, source_doc?, confidence?, pinned? |
| link | src_id, dst_id, relation, weight? |
| pin | id, pinned? |
| forget | id |
| get | id |
| stats | - |
| cleanup | - (dedup + remove junk) |

```json
{"action": "remember", "kind": "decision", "title": "选择方案A", "body": "因为性能更好"}
{"action": "recall", "query": "方案", "limit": 5}
{"action": "link", "src_id": 1, "dst_id": 2, "relation": "caused_by"}
```

## Notes

- Do NOT use both tools for the same fact
- ConversationMemory: simple preferences
- MemoryGraph: complex relationships
