"""Typed response models for the Wealthfolio REST client's portfolios
surface.

Endpoint/DTO confirmed against
`apps/server/src/api/portfolios.rs` (plural) and
`crates/core/src/portfolios/portfolios_model.rs`.

`GET /portfolios` returns a **bare JSON array** of `PortfolioWithAccounts`
-- this is the real equivalent of `wealthfolio_mcp`'s `get_portfolios`/
`PortfoliosResult`. The *singular* `apps/server/src/api/portfolio.rs` is
an unrelated module -- it only exposes portfolio-wide recalculation-job
triggers (`POST /portfolio/update`, `POST /portfolio/recalculate`) and an
SSE event stream (`GET /events/stream`), no data read at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import _get, _get_list, _parse_items


@dataclass
class Portfolio:
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    account_ids: List[str] = _field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Portfolio":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            name=_get(data, "name"),
            description=_get(data, "description"),
            sort_order=_get(data, "sortOrder"),
            account_ids=_get_list(data, "accountIds"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )


@dataclass
class PortfoliosResult:
    """Client-side convenience wrapper around `GET /api/v1/portfolios`'s
    bare array response -- see `AccountsResult` for the same pattern."""

    portfolios: List[Portfolio] = _field(default_factory=list)
    count: Optional[int] = None
    raw: Any = None

    @classmethod
    def from_dict(cls, data) -> "PortfoliosResult":
        if isinstance(data, list):
            items = _parse_items(Portfolio, data)
        else:
            items = _parse_items(Portfolio, _get_list(data, "portfolios"))
        return cls(portfolios=items, count=len(items), raw=data)
