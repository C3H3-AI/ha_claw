# HAControl - Advanced HA Control + Shell

## Actions

| Action | Purpose | Params |
|--------|---------|--------|
| shell | Run shell command | command |
| check_config | Validate configuration.yaml | - |
| list_integrations | List all integrations | - |
| get_integration | Get integration info | domain |
| list_entities_by_integration | List entities | entry_id |
| reload_integration | Reload integration | entry_id |
| rename_entry | Rename config entry | entry_id, name |
| reload_themes | Reload themes | - |
| reload_resources | Reload Lovelace resources | - |
| reload_scripts | Reload scripts | - |
| reload_automations | Reload automations | - |
| get_system_log | Get system log | - |
| get_error_log | Get error log | - |
| get_diagnostics | Get diagnostics | domain, entry_id |

## Shell Examples

```json
{"action": "shell", "params": {"command": "ls -la /config"}}
{"action": "shell", "params": {"command": "cat /config/configuration.yaml"}}
```

## Important

- Before modifying automations.yaml/configuration.yaml, ask user confirmation
- Prefer Automation tool for automation CRUD
- Prefer ConfigFile for file operations with staging
