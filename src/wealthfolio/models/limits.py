"""Typed response models for the Wealthfolio REST client's contribution
limits surface.

Endpoint/DTO confirmed against
`apps/server/src/api/limits.rs` and
`crates/core/src/limits/limits_model.rs`.

`GET /limits` returns a **bare JSON array** of `ContributionLimit` (same
bare-array convention as `GET /accounts`/`GET /goals`). Per-limit computed
usage (`usedAmount`/`remainingAmount`/`currency` in
`wealthfolio_mcp.models.ContributionLimit`) is NOT part of this wire shape
at all -- it is a separate, not-implemented-here endpoint,
`GET /limits/{id}/deposits` (`DepositsCalculation`: `total`, `baseCurrency`,
`byAccount`), which must be called once per limit id. `accountIds` here is
a single comma-separated **string** on the wire (`Option<String>`), not a
list -- passed through as-is, not split.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import _get, _get_list, _parse_items


@dataclass
class ContributionLimit:
    id: Optional[str] = None
    group_name: Optional[str] = None
    contribution_year: Optional[int] = None
    limit_amount: Optional[float] = None
    account_ids: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ContributionLimit":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            group_name=_get(data, "groupName"),
            contribution_year=_get(data, "contributionYear"),
            limit_amount=_get(data, "limitAmount"),
            account_ids=_get(data, "accountIds"),
            start_date=_get(data, "startDate"),
            end_date=_get(data, "endDate"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )


@dataclass
class ContributionLimitsResult:
    """Client-side convenience wrapper around `GET /api/v1/limits`'s bare
    array response -- see `AccountsResult` for the same pattern."""

    limits: List[ContributionLimit] = _field(default_factory=list)
    count: Optional[int] = None
    raw: Any = None

    @classmethod
    def from_dict(cls, data) -> "ContributionLimitsResult":
        if isinstance(data, list):
            items = _parse_items(ContributionLimit, data)
        else:
            items = _parse_items(ContributionLimit, _get_list(data, "limits"))
        return cls(limits=items, count=len(items), raw=data)
