"""Typed response models for the Wealthfolio REST client's goals surface.

Endpoint/DTO confirmed against
`apps/server/src/api/goals.rs` and `crates/core/src/goals/goals_model.rs`.

`GET /goals` returns a **bare JSON array** of `Goal` (same convention as
`GET /accounts` -- see `AccountsResult`). `goals.rs` also registers a much
larger surface with no MCP equivalent -- single-goal CRUD (`get_goal`/
`create_goal`/`update_goal`/`delete_goal`), funding rules (`/goals/{id}/
funding`), goal plans (`/goals/{id}/plan`, `/goals/plan`), summary refresh,
and retirement/save-up simulation endpoints (`/goals/retirement/...`,
`/goals/{id}/retirement/overview`, `/goals/{id}/save-up/overview`, etc.) --
those endpoints are not implemented here.

The real `Goal` wire shape is materially different from
`wealthfolio_mcp.models.Goal` (that MCP model is the tool server's own
simplification: `target_amount`/`current_amount`/`progress_percent`/
`deadline`/`is_achieved`). The REST DTO instead has `goalType`/
`statusLifecycle`/`statusHealth`/`priority`/`summaryCurrentValue`/
`summaryProgress`/`projectedCompletionDate`/`projectedValueAtTargetDate`/
`summaryTargetAmount` -- modeled here as confirmed live, not translated to
the MCP shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import _get, _get_list, _parse_items


@dataclass
class Goal:
    id: Optional[str] = None
    goal_type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    target_amount: Optional[float] = None
    status_lifecycle: Optional[str] = None
    status_health: Optional[str] = None
    priority: Optional[int] = None
    cover_image_key: Optional[str] = None
    currency: Optional[str] = None
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    summary_current_value: Optional[float] = None
    summary_progress: Optional[float] = None
    projected_completion_date: Optional[str] = None
    projected_value_at_target_date: Optional[float] = None
    summary_target_amount: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Goal":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            goal_type=_get(data, "goalType"),
            title=_get(data, "title"),
            description=_get(data, "description"),
            target_amount=_get(data, "targetAmount"),
            status_lifecycle=_get(data, "statusLifecycle"),
            status_health=_get(data, "statusHealth"),
            priority=_get(data, "priority"),
            cover_image_key=_get(data, "coverImageKey"),
            currency=_get(data, "currency"),
            start_date=_get(data, "startDate"),
            target_date=_get(data, "targetDate"),
            summary_current_value=_get(data, "summaryCurrentValue"),
            summary_progress=_get(data, "summaryProgress"),
            projected_completion_date=_get(data, "projectedCompletionDate"),
            projected_value_at_target_date=_get(data, "projectedValueAtTargetDate"),
            summary_target_amount=_get(data, "summaryTargetAmount"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )


@dataclass
class GoalsResult:
    """Client-side convenience wrapper around `GET /api/v1/goals`'s bare
    array response -- see `AccountsResult` for the same pattern. There is
    no server-side `count`/`truncated`/`originalCount` envelope here,
    unlike `wealthfolio_mcp`'s own `GoalsResult`."""

    goals: List[Goal] = _field(default_factory=list)
    count: Optional[int] = None
    raw: Any = None

    @classmethod
    def from_dict(cls, data) -> "GoalsResult":
        if isinstance(data, list):
            items = _parse_items(Goal, data)
        else:
            items = _parse_items(Goal, _get_list(data, "goals"))
        return cls(goals=items, count=len(items), raw=data)
