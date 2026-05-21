# ConfigEntries - Integration Management

## Actions

| Action | Purpose | Params |
|--------|---------|--------|
| list | List all integrations | - |
| get | Get integration details | domain |
| flow/init | Start install flow | handler (domain name) |
| flow/configure | Continue flow | flow_id, user_input |
| options/init | Start options flow | entry_id |
| options/configure | Continue options | flow_id, user_input |
| delete | Remove integration | entry_id |
| reload | Reload integration | entry_id |

## Install Workflow

```
1. flow/init handler="xiaomi_miio"
   → Returns flow_id + data_schema (required fields)

2. flow/configure flow_id="xxx" user_input={"host": "192.168.1.100", "token": "..."}
   → Returns success or next step
```

## Check Before Install

```
get domain="xiaomi_miio"
→ Shows if already installed
```

## Notes

- Do NOT explore randomly — follow the workflow
- flow/init returns data_schema with required fields
- user_input must match data_schema exactly
