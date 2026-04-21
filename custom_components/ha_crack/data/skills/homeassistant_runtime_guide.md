# Home Assistant Runtime Guide

Primary operating guide for Home Assistant work inside `kadermanager`. Read first, act after.

## Usage Order
1. Understand: `GetSystemIndex`, `GetLiveContext`
2. Resolve entity: `SmartDiscovery`, `EntityQuery`
3. Act: `DeviceSkill`, `ServiceCall`
4. Troubleshoot: `HomeAssistantGuideSkill`

## Rules
- Verify live state before claiming HA results.
- Look up uncertain entities, areas, or services instead of guessing.
- Use native intents, services, and registries. Do not route users to external MCP, CLI wrappers, `ha.sh`, or shell scripts when internal tools can do the job.
- For dashboards, automations, integrations, repairs, calendars, backups, diagnostics, or ESPHome questions, consult `HomeAssistantGuideSkill` first, then act.

## Execution Power Tools
Highest-priority execution surface. Use when native tools cannot complete the task.

### `HAControl(action="shell")`
Runs a shell command in the HA process.
- Params: `command` (req), `timeout` (s, default 30, max 600), `cwd` (default: HA config dir).
- Returns: `success`, `returncode`, `stdout`, `stderr`, `elapsed`, `cwd`. Streams truncated at 64KB.
- Use for: log inspection, file probing, git/system status, bundled helper scripts.
- Refuse: `rm -rf`, `dd`, `mkfs`, chmod on system paths, fork bombs, writing to `/dev/*`.

### `ExecutePython` — inline
Runs Python in the HA event loop with direct `hass` access. No subprocess.
- Params: `code` (req). Set `result = ...` to return a value.
- Example: `result = [s.entity_id for s in hass.states.async_all() if s.state == "unavailable"]`
- Never block the loop: no `time.sleep`, no network I/O, no long loops.

### `ExecutePython` — sandbox
Isolated child venv via subprocess. Triggered by `sandbox=true` or non-empty `requirements`.
- Params: `code`, `sandbox`, `requirements` (pip specs), `timeout`.
- Use for: computations needing extra packages (`pandas`, `numpy`, `lxml`) or heavy/blocking work.
- No `hass` access. Cached at `<config>/kadermanager_sandbox/`.

## Tool Selection Order
1. Native HA tool (`SmartDiscovery`, `EntityQuery`, `ServiceCall`, `GetLiveContext`, `GetSystemIndex`).
2. `ExecutePython` inline — native tool missing but data lives in `hass`.
3. `HAControl(action="shell")` — needs filesystem or a shell utility.
4. `ExecutePython` sandbox — extra pip packages or isolation required.
