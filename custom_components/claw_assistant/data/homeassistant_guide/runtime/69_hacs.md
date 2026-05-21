# HACS - Manage HACS Store

## Actions

| Action | Purpose | Params |
|--------|---------|--------|
| list | List installed repos | category |
| search | Search HACS store | query, category |
| github_search | Search GitHub | query |
| info | Get repo info | repository |
| install | Install repo | repository, category |
| update | Update repo | repository |
| uninstall | Uninstall repo | repository |
| remove | Remove repo | repository |
| manage | Manage repo | repository, params |
| edit | Edit repo settings | repository, params |
| open_add_integration | Open add dialog | - |

## Categories

- integration
- plugin (Lovelace)
- theme
- python_script
- appdaemon
- netdaemon

## Examples

```json
// Search for card
{"action": "search", "query": "mushroom", "category": "plugin"}

// Install integration
{"action": "install", "repository": "hacs/integration", "category": "integration"}

// List installed
{"action": "list", "category": "integration"}
```

## Notes

- Use search to find repos before install
- category is required for install
- After install, may need to add integration via ConfigEntries
