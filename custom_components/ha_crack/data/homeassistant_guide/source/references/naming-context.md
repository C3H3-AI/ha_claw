# Home Assistant Naming Context

Use naming context to keep stable user-facing aliases mapped to real entities.

Purpose:

- resolve phrases like "living room light" consistently
- keep preferred aliases stable across turns
- reduce guessing when multiple similar entities exist

Recommended approach:

1. Prefer user-confirmed aliases.
2. Keep one canonical entity target per alias.
3. Store only stable naming facts.

Examples:

- living room light => light.example_living_room_main
- office light => switch.example_office_light
- bedroom main light => switch.example_bedroom_main_light
