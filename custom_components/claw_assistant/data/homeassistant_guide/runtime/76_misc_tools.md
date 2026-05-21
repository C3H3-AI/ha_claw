# Misc Tools

## ParallelToolCall

Run 2+ independent tools in parallel.

```json
{
  "tools": [
    {"name": "EntityQuery", "args": {"entity_id": "light.a"}},
    {"name": "EntityQuery", "args": {"entity_id": "light.b"}}
  ]
}
```

## Notify

Send notification.

| Param | Default |
|-------|---------|
| message | (required) |
| title | "AI Assistant" |
| target | persistent_notification |

```json
{"message": "任务完成", "title": "通知"}
{"message": "Hello", "target": "notify.mobile_app"}
```

## AgentHandoff

Consult another AI agent.

```json
{
  "agent_id": "conversation.other_agent",
  "question": "How to do X?",
  "context": "Background info",
  "intent": "consult"
}
```

intent: consult / request / review

## NextAgentHandoff

Shortcut for next available agent.

```json
{"question": "Help with X", "context": "..."}
```

## SetConversationState

Set conversation state (complex multi-turn only).

```json
{"expecting_response": true, "reason": "Waiting for user choice"}
```

Do NOT use for simple queries.

## HeartbeatManager

Manage follow-up tasks.

| Action | Params |
|--------|--------|
| list | - |
| upsert | slug, title, schedule, objective, steps |
| delete | slug |
| record | slug, note |
| clear_state | slug |

```json
{
  "action": "upsert",
  "slug": "daily-check",
  "title": "Daily Check",
  "schedule": "0 9 * * *",
  "objective": "Check system status"
}
```

## ReadFile

Read temp/output file.

| Action | Params |
|--------|--------|
| read | path, offset, max_chars |
| search | path, query, context_chars |
| search_fuzzy | path, query |
| info | path |

```json
{"action": "read", "path": "/tmp/output.txt"}
{"action": "search", "path": "/tmp/log.txt", "query": "error"}
```
