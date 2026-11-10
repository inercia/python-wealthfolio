"""Typed response models for the Wealthfolio REST client's income surface.

Field names sourced from `crates/core/src/portfolio/income/income_model.rs`
and `apps/server/src/api/performance.rs` (income endpoints live in that
file server-side, not a separate `income.rs`).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, Optional

from .common import _get, _get_dict, _get_float, _get_float_dict, _parse_dict_items


@dataclass
class IncomeByAsset:
    asset_id: Optional[str] = None
    kind: Optional[str] = None
    symbol: Optional[str] = None
    name: Optional[str] = None
    income: Optional[float] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "IncomeByAsset":
        data = data if isinstance(data, dict) else {}
        return cls(
            asset_id=_get(data, "assetId"),
            kind=_get(data, "kind"),
            symbol=_get(data, "symbol"),
            name=_get(data, "name"),
            income=_get_float(data, "income"),
            raw=data,
        )


@dataclass
class IncomeByAccount:
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    by_month: Dict[str, float] = _field(default_factory=dict)
    total: Optional[float] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "IncomeByAccount":
        data = data if isinstance(data, dict) else {}
        return cls(
            account_id=_get(data, "accountId"),
            account_name=_get(data, "accountName"),
            by_month=_get_float_dict(data, "byMonth"),
            total=_get_float(data, "total"),
            raw=data,
        )


@dataclass
class IncomeSummary:
    """One entry of the bare `IncomeSummary[]` array returned by both
    `GET /api/v1/income/summary` and `POST /api/v1/income/summary/query`
    -- despite the singular name, the endpoint can return more than one
    summary only in the sense that a caller could union results across
    scopes themselves; the server always emits exactly one aggregated
    summary per call."""

    period: Optional[str] = None
    by_month: Dict[str, float] = _field(default_factory=dict)
    by_type: Dict[str, float] = _field(default_factory=dict)
    by_asset: Dict[str, IncomeByAsset] = _field(default_factory=dict)
    by_currency: Dict[str, float] = _field(default_factory=dict)
    by_account: Dict[str, IncomeByAccount] = _field(default_factory=dict)
    total_income: Optional[float] = None
    currency: Optional[str] = None
    monthly_average: Optional[float] = None
    yoy_growth: Optional[float] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "IncomeSummary":
        data = data if isinstance(data, dict) else {}
        return cls(
            period=_get(data, "period"),
            by_month=_get_float_dict(data, "byMonth"),
            by_type=_get_float_dict(data, "byType"),
            by_asset=_parse_dict_items(IncomeByAsset, _get_dict(data, "byAsset")),
            by_currency=_get_float_dict(data, "byCurrency"),
            by_account=_parse_dict_items(IncomeByAccount, _get_dict(data, "byAccount")),
            total_income=_get_float(data, "totalIncome"),
            currency=_get(data, "currency"),
            monthly_average=_get_float(data, "monthlyAverage"),
            yoy_growth=_get_float(data, "yoyGrowth"),
            raw=data,
        )
