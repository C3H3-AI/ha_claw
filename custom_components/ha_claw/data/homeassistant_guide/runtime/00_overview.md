# Home Assistant Runtime Guide Overview

This guide bundle migrates the external `homeassistant` skill package into `kadermanager`.

## What Was Preserved
- The original README, SKILL, and `references/*.md` teaching material are preserved under `source/`.
- The practical workflows, safety policy, checklists, and naming-context guidance are retained.
- Topic coverage includes device control, automation triage, dashboard work, integrations, calendars, backups, diagnostics, and ESPHome.

## What Changed For Kadermanager
- `kadermanager` must not depend on external connection credentials or shell helper scripts.
- All permissions come from the running Home Assistant integration context.
- Prefer Home Assistant native intents, entity state APIs, registries, services, and frontend APIs already available inside this integration.
- When a source document shows a shell command, treat it as historical reference, then map it to internal tools and APIs.

## Recommended Tooling Inside Kadermanager
- `HomeAssistantGuideSkill`: read bundled guides and workflows.
- `DeviceSkill`: common device control and state queries through native intents.
- `EntityQuery` and `SmartDiscovery`: entity lookup and fuzzy discovery.
- `ServiceCall` and `ListServices`: direct Home Assistant service access.
- `GetSystemIndex`: quick topology overview for areas, domains, automations, scripts, and people.

## Decision Rule
- Need operating instructions or troubleshooting playbooks: open this guide bundle first.
- Need to act on Home Assistant: use internal tools, not external shell setup.
