# Claw Assistant Token Optimization Plan

## Goal

Reduce token waste in Claw Assistant without breaking existing Home Assistant conversation behavior.

The first rule is to make the runtime observable before making invasive changes. The second rule is to cut repeated fixed overhead before compressing history. Bigger context windows are not a fix for a bloated loop.

## Current Main Line

```text
async_setup_runtime
  -> async_setup_internal_llm
  -> install_conversation_hook
  -> hooked async_converse
  -> execute_conversation_turn
  -> _execute_conversation_turn_inner
```

`orchestrator.py` is the real main controller. It owns input cleanup, attachment routing, activity injection, first-turn prompt construction, runtime config resolution, and dispatch to kernel, summary, or fallback.

## Runtime Side Lines

### Kernel line

```text
execute_kernel_turn
  -> build per-step planner prompt
  -> original_async_converse with tool_mode=kernel
  -> parse step protocol
  -> execute_kernel_tool
  -> append step and observation to chat log
```

This line is expensive because every step re-injects the step contract, full allowed tool catalog, completed steps, and planner rules.

### Fallback line

```text
run_agent_fallback_chain
  -> internal Home Assistant/native pass
  -> external fallback agent queue
  -> per-agent fallback prompt
  -> context preflight compression
  -> tool pair sanitation
```

This line is expensive because the external agent path asks for `minimal` tool mode, but the current implementation returns the full runtime tool list.

### Summary line

```text
process_ai_summary
  -> call each processing agent
  -> collect candidate responses
  -> optionally call summary agent
```

This line is inherently expensive. It should remain opt-in and should not carry unnecessary tool schemas.

## Hook And Patch Surface

- `hook.py` replaces Home Assistant conversation entry points.
- `internal_llm.py` patches AssistAPI prompt and tools.
- `internal_llm.py` patches `APIInstance.async_call_tool` for tracking.
- `internal_llm.py` patches `ChatLog.async_update_llm_data` and swaps external AI tools to the registry surface.
- `hook.py` patches Assist pipeline final-content injection.
- `orchestrator.py` installs a ChatLog attachment hook only when needed.

## Lessons Borrowed From Claude Code Architecture

Claude Code separates stable runtime layers:

```text
entry layer
  -> execution kernel
  -> tool runtime
  -> memory/context runtime
  -> sidechain/subagent runtime
```

The useful ideas to copy are:

- keep main loop and side lines distinct;
- make prompt sections observable;
- keep stable prompt prefix separate from dynamic sections;
- route tools by task and agent instead of exposing every tool every turn;
- store detailed sidechain state outside the main transcript and reinject only summaries.

The target reference is `/Users/knoopnu/Downloads/claude-code-analysis/`. The relevant lessons from that analysis are:

- `01-architecture-overview.md`: keep entry, initialization, execution kernel, tool runtime, memory/context, and extension layers separate.
- `04f-context-management.md`: reserve context budget, compact before failure, and use circuit breakers instead of retrying bloated requests forever.
- `04g-prompt-management.md`: system prompt should be section-based, observable, cache-aware, and split into stable and dynamic regions.
- `04b-tool-call-implementation.md`: tool runtime should be a protocol layer, not a raw function bag; tool selection must be explicit and safe by default.
- `04-agent-memory.md`: memory should use index-first recall; detailed memories should be fetched on demand instead of injected every turn.
- `04h-multi-agent.md`: side agents need sidechain state and bounded handoff summaries; their transcripts should not blindly pollute the main active context.

The first implementation target is not a full rewrite. It is to make the existing Claw runtime obey the same separation at the cheapest cut point: external fallback already asks for a minimal tool surface, so the patch layer must actually honor that request.

## First Fixes

### 1. Add token-cost observability

Log character estimates for:

- internal full prompt;
- native full prompt;
- base prompt after appended sections;
- runtime tool list count;
- minimal tool list count.

This is low risk and tells us what actually changed.

### 2. Make minimal tool mode real

`build_minimal_tool_list` must stop returning the full runtime tool list.

Both tool injection paths must honor this:

- `AssistAPI._async_get_tools` through `build_assist_api_tools`.
- `ChatLog.async_update_llm_data` through the patched chat log tool surface.

Initial minimal set:

- `ServiceCall`
- `EntityQuery`
- `GetLiveContext`
- `StockQuery`
- `WebSearch`
- `UrlFetch`
- `WebReadChunk`
- `ReadFile`
- `MemoryGraph`
- `GetWorkspaceDoc`
- `HomeAssistantGuide`

This keeps normal home control, query, search, file-output reading, memory recall, and guide lookup. Heavy write/config/front-end/dashboard/self-edit tools stay out of fallback by default.

### 3. Keep full tools where compatibility requires them

The internal native pass and kernel tool executor can remain broad first. The first saving target is external fallback, because it already asks for `minimal` and currently does not get it.

## Later Fixes

- Data-driven tool routing for kernel catalog. Do not hardcode language keyword tables. Use tool metadata, registry categories, explicit runtime profiles, or a searchable tool index.
- Short tool descriptions for planner mode.
- Workspace startup index-first mode.
- Bootstrap injection removal once bootstrap is inactive.
- Separate sidechain transcript for kernel step progress instead of replaying every step into the main active context.
- Prompt section cache boundary: stable policy first, dynamic history/activity/tool result blocks last.

## Safety Constraints

- Do not break existing Home Assistant native intents.
- Do not remove full runtime tools globally.
- Do not change destructive tool permissions in this pass.
- Do not delete conversation history.
- Do not change user-visible response formatting in this pass.
