"""Typed response models for the Wealthfolio REST client's performance
surface.

Field names sourced from
`crates/core/src/portfolio/performance/performance_model.rs` and
`apps/server/src/api/performance.rs`. Every
Decimal-typed field is JSON-string-encoded on the wire, same convention
as elsewhere (`_get_float` handles it). Enum-typed fields (`mode`,
`dataQuality.status`, `summary.method`/`basis`/`amountStatus`/
`percentStatus`, `basisStatus` at both the top level and inside
`summary`) are passed through as their raw camelCase wire strings (e.g.
`"timeWeighted"`, `"ok"`, `"marketValue"`) rather than mapped onto a
Python enum -- same lenient-string convention used for `Account.account_type`
and friends.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import _get, _get_float, _get_list, _parse_items, _parse_nested


@dataclass
class PerformanceScopeDescriptor:
    id: Optional[str] = None
    currency: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "PerformanceScopeDescriptor":
        data = data if isinstance(data, dict) else {}
        return cls(id=_get(data, "id"), currency=_get(data, "currency"), raw=data)


@dataclass
class PerformancePeriod:
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "PerformancePeriod":
        data = data if isinstance(data, dict) else {}
        return cls(start_date=_get(data, "startDate"), end_date=_get(data, "endDate"), raw=data)


@dataclass
class PerformanceReturns:
    twr: Optional[float] = None
    annualized_twr: Optional[float] = None
    irr: Optional[float] = None
    annualized_irr: Optional[float] = None
    value_return: Optional[float] = None
    annualized_value_return: Optional[float] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "PerformanceReturns":
        data = data if isinstance(data, dict) else {}
        return cls(
            twr=_get_float(data, "twr"),
            annualized_twr=_get_float(data, "annualizedTwr"),
            irr=_get_float(data, "irr"),
            annualized_irr=_get_float(data, "annualizedIrr"),
            value_return=_get_float(data, "valueReturn"),
            annualized_value_return=_get_float(data, "annualizedValueReturn"),
            raw=data,
        )


@dataclass
class PerformanceAttribution:
    contributions: Optional[float] = None
    distributions: Optional[float] = None
    income: Optional[float] = None
    realized_pnl: Optional[float] = None
    unrealized_pnl_change: Optional[float] = None
    fx_effect: Optional[float] = None
    fees: Optional[float] = None
    taxes: Optional[float] = None
    residual: Optional[float] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "PerformanceAttribution":
        data = data if isinstance(data, dict) else {}
        return cls(
            contributions=_get_float(data, "contributions"),
            distributions=_get_float(data, "distributions"),
            income=_get_float(data, "income"),
            realized_pnl=_get_float(data, "realizedPnl"),
            unrealized_pnl_change=_get_float(data, "unrealizedPnlChange"),
            fx_effect=_get_float(data, "fxEffect"),
            fees=_get_float(data, "fees"),
            taxes=_get_float(data, "taxes"),
            residual=_get_float(data, "residual"),
            raw=data,
        )


@dataclass
class PerformanceRisk:
    volatility: Optional[float] = None
    max_drawdown: Optional[float] = None
    peak_date: Optional[str] = None
    trough_date: Optional[str] = None
    recovery_date: Optional[str] = None
    drawdown_duration_days: Optional[int] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "PerformanceRisk":
        data = data if isinstance(data, dict) else {}
        return cls(
            volatility=_get_float(data, "volatility"),
            max_drawdown=_get_float(data, "maxDrawdown"),
            peak_date=_get(data, "peakDate"),
            trough_date=_get(data, "troughDate"),
            recovery_date=_get(data, "recoveryDate"),
            drawdown_duration_days=_get(data, "drawdownDurationDays"),
            raw=data,
        )


@dataclass
class PerformanceDataQuality:
    status: Optional[str] = None
    warnings: List[str] = _field(default_factory=list)
    not_applicable_reasons: List[str] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "PerformanceDataQuality":
        data = data if isinstance(data, dict) else {}
        return cls(
            status=_get(data, "status"),
            warnings=_get_list(data, "warnings"),
            not_applicable_reasons=_get_list(data, "notApplicableReasons"),
            raw=data,
        )


@dataclass
class PerformanceSummary:
    amount: Optional[float] = None
    percent: Optional[float] = None
    method: Optional[str] = None
    basis: Optional[str] = None
    quality: Optional[str] = None
    amount_status: Optional[str] = None
    percent_status: Optional[str] = None
    basis_status: Optional[str] = None
    reasons: List[str] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "PerformanceSummary":
        data = data if isinstance(data, dict) else {}
        return cls(
            amount=_get_float(data, "amount"),
            percent=_get_float(data, "percent"),
            method=_get(data, "method"),
            basis=_get(data, "basis"),
            quality=_get(data, "quality"),
            amount_status=_get(data, "amountStatus"),
            percent_status=_get(data, "percentStatus"),
            basis_status=_get(data, "basisStatus"),
            reasons=_get_list(data, "reasons"),
            raw=data,
        )


@dataclass
class PerformanceSeriesPoint:
    """One `ReturnData` entry from `PerformanceResult.series`."""

    date: Optional[str] = None
    value: Optional[float] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "PerformanceSeriesPoint":
        data = data if isinstance(data, dict) else {}
        return cls(date=_get(data, "date"), value=_get_float(data, "value"), raw=data)


@dataclass
class PerformanceResult:
    """The shared response shape of `POST /api/v1/performance/summary` and
    `POST /api/v1/performance/history` (both return this exact DTO; only
    the request body's semantics differ -- see
    `WealthfolioClient.get_performance_summary`/`get_performance_history`)."""

    scope: Optional[PerformanceScopeDescriptor] = None
    period: Optional[PerformancePeriod] = None
    mode: Optional[str] = None
    returns: Optional[PerformanceReturns] = None
    attribution: Optional[PerformanceAttribution] = None
    risk: Optional[PerformanceRisk] = None
    data_quality: Optional[PerformanceDataQuality] = None
    basis_status: Optional[str] = None
    summary: Optional[PerformanceSummary] = None
    series: List[PerformanceSeriesPoint] = _field(default_factory=list)
    is_holdings_mode: Optional[bool] = None
    is_mixed_tracking_mode: Optional[bool] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "PerformanceResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            scope=_parse_nested(PerformanceScopeDescriptor, data, "scope"),
            period=_parse_nested(PerformancePeriod, data, "period"),
            mode=_get(data, "mode"),
            returns=_parse_nested(PerformanceReturns, data, "returns"),
            attribution=_parse_nested(PerformanceAttribution, data, "attribution"),
            risk=_parse_nested(PerformanceRisk, data, "risk"),
            data_quality=_parse_nested(PerformanceDataQuality, data, "dataQuality"),
            basis_status=_get(data, "basisStatus"),
            summary=_parse_nested(PerformanceSummary, data, "summary"),
            series=_parse_items(PerformanceSeriesPoint, _get_list(data, "series")),
            is_holdings_mode=_get(data, "isHoldingsMode"),
            is_mixed_tracking_mode=_get(data, "isMixedTrackingMode"),
            raw=data,
        )
