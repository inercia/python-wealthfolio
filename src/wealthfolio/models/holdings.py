"""Typed response models for the Wealthfolio REST client's holdings
surface.

Field names sourced from `crates/core/src/portfolio/holdings/holdings_model.rs`
and `apps/server/src/api/holdings/{mod,dto,handlers}.rs` on
`github.com/wealthfolio/wealthfolio@main`. `Holding` is
the rich per-position view model (`GET /holdings` / `POST /holdings/query`),
not the lighter `HoldingListItem` (`GET /holdings/list`, not implemented by
this client). Every Decimal-typed field is JSON-string-encoded on the wire
(same `rust_decimal` convention already confirmed for activities) --
`_get_float` handles that here too. Two fields are
deliberately NOT surfaced as typed sub-structures (still present in
`.raw` for any caller who needs them): `lots` (a `VecDeque<Lot>`, an
internal FIFO-lot breakdown) and
`instrument.classifications` (a taxonomy-assignment blob, left as a plain
dict).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import Instrument, MonetaryValue, _get, _get_float, _get_list, _parse_items, _parse_nested


@dataclass
class Holding:
    """One position's view model, as returned by `GET /api/v1/holdings` and
    `POST /api/v1/holdings/query` -- see module note above for the two
    fields intentionally left out of the typed shape."""

    id: Optional[str] = None
    account_id: Optional[str] = None
    holding_type: Optional[str] = None
    is_closed: Optional[bool] = None
    instrument: Optional[Instrument] = None
    asset_kind: Optional[str] = None
    quantity: Optional[float] = None
    open_date: Optional[str] = None
    contract_multiplier: Optional[float] = None
    local_currency: Optional[str] = None
    base_currency: Optional[str] = None
    fx_rate: Optional[float] = None
    market_value: Optional[MonetaryValue] = None
    cost_basis: Optional[MonetaryValue] = None
    price: Optional[float] = None
    purchase_price: Optional[float] = None
    unrealized_gain: Optional[MonetaryValue] = None
    unrealized_gain_pct: Optional[float] = None
    realized_gain: Optional[MonetaryValue] = None
    realized_gain_pct: Optional[float] = None
    total_gain: Optional[MonetaryValue] = None
    total_gain_pct: Optional[float] = None
    income: Optional[MonetaryValue] = None
    total_return: Optional[MonetaryValue] = None
    total_return_pct: Optional[float] = None
    return_basis: Optional[MonetaryValue] = None
    day_change: Optional[MonetaryValue] = None
    day_change_pct: Optional[float] = None
    prev_close_value: Optional[MonetaryValue] = None
    weight: Optional[float] = None
    as_of_date: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    source_account_ids: List[str] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Holding":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            account_id=_get(data, "accountId"),
            holding_type=_get(data, "holdingType"),
            is_closed=_get(data, "isClosed"),
            instrument=_parse_nested(Instrument, data, "instrument"),
            asset_kind=_get(data, "assetKind"),
            quantity=_get_float(data, "quantity"),
            open_date=_get(data, "openDate"),
            contract_multiplier=_get_float(data, "contractMultiplier"),
            local_currency=_get(data, "localCurrency"),
            base_currency=_get(data, "baseCurrency"),
            fx_rate=_get_float(data, "fxRate"),
            market_value=_parse_nested(MonetaryValue, data, "marketValue"),
            cost_basis=_parse_nested(MonetaryValue, data, "costBasis"),
            price=_get_float(data, "price"),
            purchase_price=_get_float(data, "purchasePrice"),
            unrealized_gain=_parse_nested(MonetaryValue, data, "unrealizedGain"),
            unrealized_gain_pct=_get_float(data, "unrealizedGainPct"),
            realized_gain=_parse_nested(MonetaryValue, data, "realizedGain"),
            realized_gain_pct=_get_float(data, "realizedGainPct"),
            total_gain=_parse_nested(MonetaryValue, data, "totalGain"),
            total_gain_pct=_get_float(data, "totalGainPct"),
            income=_parse_nested(MonetaryValue, data, "income"),
            total_return=_parse_nested(MonetaryValue, data, "totalReturn"),
            total_return_pct=_get_float(data, "totalReturnPct"),
            return_basis=_parse_nested(MonetaryValue, data, "returnBasis"),
            day_change=_parse_nested(MonetaryValue, data, "dayChange"),
            day_change_pct=_get_float(data, "dayChangePct"),
            prev_close_value=_parse_nested(MonetaryValue, data, "prevCloseValue"),
            weight=_get_float(data, "weight"),
            as_of_date=_get(data, "asOfDate"),
            metadata=_get(data, "metadata"),
            source_account_ids=_get_list(data, "sourceAccountIds"),
            raw=data,
        )


@dataclass
class HoldingsResult:
    """Client-side wrapper around `POST /api/v1/holdings/query`'s bare
    `Holding[]` response. `account_id`/`portfolio_id`/`account_ids`/
    `include_closed` echo the request scope for caller convenience (the
    response body itself carries no scope echo) -- set by
    `WealthfolioClient.get_holdings`, not parsed from the response."""

    holdings: List[Holding] = _field(default_factory=list)
    count: Optional[int] = None
    account_id: Optional[str] = None
    portfolio_id: Optional[str] = None
    account_ids: Optional[List[str]] = None
    include_closed: Optional[bool] = None
    raw: Any = None

    @classmethod
    def from_dict(
        cls, data, *, account_id=None, portfolio_id=None, account_ids=None, include_closed=None
    ) -> "HoldingsResult":
        items = _parse_items(Holding, data) if isinstance(data, list) else []
        return cls(
            holdings=items,
            count=len(items),
            account_id=account_id,
            portfolio_id=portfolio_id,
            account_ids=account_ids,
            include_closed=include_closed,
            raw=data,
        )
