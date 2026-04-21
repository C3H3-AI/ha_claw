## Context Routing

- Save only durable user preferences, environment facts, and stable conventions with `ConversationMemory`.
- If the user wants a reminder, follow-up, or later re-check, use `HeartbeatManager` / `HeartbeatSkill` instead of long-term memory.
- If content is just current task progress, temporary reasoning, or this-turn status, keep it in the conversation history and do not store it as long-term memory.
- Prefer the smallest correct memory surface: conversation history first, heartbeat for follow-up tasks, long-term memory for durable facts.
