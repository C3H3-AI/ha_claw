# Automation - Manage Automations

## Actions

| Action | Purpose | Params |
|--------|---------|--------|
| list | List all automations | - |
| get | Get automation config | entity_id or automation_id |
| create | Create new automation | config |
| update | Update automation | entity_id, config |
| delete | Delete automation | entity_id |
| trigger | Trigger automation | entity_id |
| enable | Enable automation | entity_id |
| disable | Disable automation | entity_id |
| traces | List execution history | entity_id |
| trace_get | Get detailed trace | entity_id, run_id |

## Config Format

```yaml
alias: "Motion Light"
trigger:
  - platform: state
    entity_id: binary_sensor.motion
    to: "on"
action:
  - service: light.turn_on
    target:
      entity_id: light.living_room
```

## Workflow

```
1. get entity_id="automation.xxx" → Get current config
2. Modify config
3. update entity_id="automation.xxx" config={...}
```

## Notes

- Always use this tool for automation CRUD
- Do NOT use HAControl shell or ConfigFile for automations
- traces/trace_get for debugging execution history
