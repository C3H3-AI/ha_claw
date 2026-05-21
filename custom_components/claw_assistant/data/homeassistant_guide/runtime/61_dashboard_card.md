# DashboardCard Tool Guide

Create and manage Lovelace dashboard views and cards.

## Actions

| Action | Purpose | Required Params |
|--------|---------|-----------------|
| check_dependency | Verify html-card-pro installed | - |
| list_dashboards | List all dashboards | - |
| get_dashboard | Get dashboard config | dashboard |
| get_card | Get specific card | dashboard, view_index, card_index |
| add_view | Add new view | dashboard, title |
| add_card | Add card to view | dashboard, view_index, card_config |
| update_card | Replace card | dashboard, view_index, card_index, card_config |
| patch_card | Partial update | dashboard, view_index, card_index, patch |
| remove_card | Delete card | dashboard, view_index, card_index |
| remove_view | Delete view | dashboard, view_index |
| verify_card | Check card renders | dashboard, view_index, card_index |
| get_doc | Get html-card-pro docs | feature (style/js_api/data_binding) |

## Mandatory Workflow

1. **check_dependency** — ensure html-card-pro installed
2. **get_doc** — read docs for features you'll use
3. **list_dashboards** — find target dashboard
4. **add_card** or **update_card** — write content
5. **verify_card** — confirm it renders

## Card Config Format

```yaml
type: custom:html-pro-card
content: |
  <div>Your HTML here</div>
css: |
  div { color: red; }
```

## Works With FrontendInspect

- Use FrontendInspect to SEE current cards
- Use DashboardCard to MODIFY config
- Use FrontendInspect to VERIFY changes rendered
