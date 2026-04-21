

from __future__ import annotations

from typing import Any


def build_next_action(
    tool: str = "",
    action: str = "",
    *,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:

    if not tool and not action and not args:
        return {}
    return {
        "tool": tool,
        "action": action,
        "args": args or {},
    }


def build_route_envelope(
    route_kind: str,
    tool: str = "",
    action: str = "",
    *,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:

    envelope = {"route_kind": route_kind}
    next_action = build_next_action(tool, action, args=args)
    if next_action:
        envelope["next_action"] = next_action
    else:
        envelope["next_action"] = {}
    return envelope


def build_route_hint(
    route_kind: str,
    tool: str = "",
    action: str = "",
    *,
    args: dict[str, Any] | None = None,
    recommendation: str = "",
) -> dict[str, Any]:

    route_hint = {"kind": route_kind, "next_action": build_next_action(tool, action, args=args)}
    if recommendation:
        route_hint["recommendation"] = recommendation
    return route_hint
