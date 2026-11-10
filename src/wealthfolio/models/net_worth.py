"""Typed response models for the Wealthfolio REST client's net worth
surface.

Field names sourced from `crates/core/src/portfolio/net_worth/net_worth_model.rs`
and `apps/server/src/api/net_worth.rs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import _get, _get_float, _get_float_dict, _get_list, _parse_items, _parse_nested


@dataclass
class BreakdownItem:
    """One entry in `NetWorthResult.assets.breakdown`/`liabilities.breakdown`
    -- recursive via `children` (empty for leaf items and for the
    Investments category, per the Rust doc comment)."""

    category: Optional[str] = None
    name: Optional[str] = None
    value: Optional[float] = None
    asset_id: Optional[str] = None
    children: List["BreakdownItem"] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "BreakdownItem":
        data = data if isinstance(data, dict) else {}
        return cls(
            category=_get(data, "category"),
            name=_get(data, "name"),
            value=_get_float(data, "value"),
            asset_id=_get(data, "assetId"),
            children=_parse_items(BreakdownItem, _get_list(data, "children")),
            raw=data,
        )


@dataclass
class AssetsSection:
    total: Optional[float] = None
    breakdown: List[BreakdownItem] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "AssetsSection":
        data = data if isinstance(data, dict) else {}
        return cls(
            total=_get_float(data, "total"),
            breakdown=_parse_items(BreakdownItem, _get_list(data, "breakdown")),
            raw=data,
        )


@dataclass
class LiabilitiesSection:
    total: Optional[float] = None
    breakdown: List[BreakdownItem] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "LiabilitiesSection":
        data = data if isinstance(data, dict) else {}
        return cls(
            total=_get_float(data, "total"),
            breakdown=_parse_items(BreakdownItem, _get_list(data, "breakdown")),
            raw=data,
        )


@dataclass
class StaleAssetInfo:
    asset_id: Optional[str] = None
    name: Optional[str] = None
    valuation_date: Optional[str] = None
    days_stale: Optional[int] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "StaleAssetInfo":
        data = data if isinstance(data, dict) else {}
        return cls(
            asset_id=_get(data, "assetId"),
            name=_get(data, "name"),
            valuation_date=_get(data, "valuationDate"),
            days_stale=_get(data, "daysStale"),
            raw=data,
        )


@dataclass
class NetWorthResult:
    """`GET /api/v1/net-worth`'s response (`NetWorthResponse` in Rust) --
    a balance-sheet snapshot for one date, not a time series (see
    `NetWorthHistoryPoint`/`WealthfolioClient.get_net_worth_history` for
    that)."""

    date: Optional[str] = None
    assets: Optional[AssetsSection] = None
    liabilities: Optional[LiabilitiesSection] = None
    net_worth: Optional[float] = None
    currency: Optional[str] = None
    oldest_valuation_date: Optional[str] = None
    stale_assets: List[StaleAssetInfo] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "NetWorthResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            date=_get(data, "date"),
            assets=_parse_nested(AssetsSection, data, "assets"),
            liabilities=_parse_nested(LiabilitiesSection, data, "liabilities"),
            net_worth=_get_float(data, "netWorth"),
            currency=_get(data, "currency"),
            oldest_valuation_date=_get(data, "oldestValuationDate"),
            stale_assets=_parse_items(StaleAssetInfo, _get_list(data, "staleAssets")),
            raw=data,
        )


@dataclass
class NetWorthHistoryPoint:
    """One point from `GET /api/v1/net-worth/history` -- a bare
    `NetWorthHistoryPoint[]` array, parsed directly by
    `WealthfolioClient.get_net_worth_history` (no wrapper needed, unlike
    `HoldingsResult`, since there is no request-echo worth preserving)."""

    date: Optional[str] = None
    portfolio_value: Optional[float] = None
    alternative_assets_value: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_assets: Optional[float] = None
    net_worth: Optional[float] = None
    net_contribution: Optional[float] = None
    breakdown: Dict[str, float] = _field(default_factory=dict)
    currency: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "NetWorthHistoryPoint":
        data = data if isinstance(data, dict) else {}
        return cls(
            date=_get(data, "date"),
            portfolio_value=_get_float(data, "portfolioValue"),
            alternative_assets_value=_get_float(data, "alternativeAssetsValue"),
            total_liabilities=_get_float(data, "totalLiabilities"),
            total_assets=_get_float(data, "totalAssets"),
            net_worth=_get_float(data, "netWorth"),
            net_contribution=_get_float(data, "netContribution"),
            breakdown=_get_float_dict(data, "breakdown"),
            currency=_get(data, "currency"),
            raw=data,
        )
