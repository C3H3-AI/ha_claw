# FrontendInspect Tool Guide

Control and inspect the Home Assistant frontend like a real user.

## Actions

| Action | Purpose | Required Params |
|--------|---------|-----------------|
| snapshot | Get page structure, interactables list | - |
| exec_js | Run JavaScript, get rendered content | js_code |
| search_cache | Search cached results | query |
| navigate | Go to path | path |
| tap | Click element | idx OR selector OR text |
| type | Type into input | idx OR selector OR text, value |
| key | Send keyboard event | key |
| scroll | Scroll page | direction, amount |

## Mandatory Workflow

1. **snapshot** first — get DOM structure, interactables with idx
2. **exec_js** second — get actual rendered text content
3. Use **idx** from snapshot for precise targeting

## Element Targeting

Prefer `idx=N` from snapshot interactables. It works across shadow DOM.

Fallback: `selector` (CSS) or `text` (visible text).

## Dialog Handling

snapshot returns `active_dialogs` with structured data:
- type, title, body (inputs with labels/values/hints), buttons
- Use hint field to know how to interact

## Works With DashboardCard

- FrontendInspect = SEE and INTERACT (view, click, scroll)
- DashboardCard = MODIFY config (create/edit/delete cards)
- Workflow: FrontendInspect → DashboardCard → FrontendInspect (verify)

## exec_js Best Practices

**DO NOT manually traverse shadow DOM!** Use these helper patterns:

```javascript
// Get all visible text on page (recommended)
(() => {
  const roots = [document];
  const texts = [];
  const seen = new Set();
  while (roots.length) {
    const r = roots.pop();
    if (seen.has(r)) continue;
    seen.add(r);
    r.querySelectorAll('*').forEach(el => {
      if (el.shadowRoot) roots.push(el.shadowRoot);
      const t = el.textContent?.trim();
      if (t && t.length < 500) texts.push(t);
    });
  }
  return [...new Set(texts)].join('\n').substring(0, 3000);
})()

// Get specific element by visible text
(() => {
  const roots = [document];
  const seen = new Set();
  while (roots.length) {
    const r = roots.pop();
    if (seen.has(r)) continue;
    seen.add(r);
    for (const el of r.querySelectorAll('*')) {
      if (el.shadowRoot) roots.push(el.shadowRoot);
      if (el.textContent?.includes('TARGET_TEXT')) return el.outerHTML.substring(0, 1000);
    }
  }
  return 'not found';
})()
```

## Common Patterns

```
# See what's on screen
snapshot → exec_js

# Click a button
snapshot → tap idx=N

# Fill a form
snapshot → type idx=N value="..."

# Navigate
navigate path="/config/integrations"
```
