"""Typed response models for the Wealthfolio REST client's assets,
transaction-categorization, cash-balance/current-valuation, asset
allocation, and holdings-snapshot surfaces.

Endpoint/DTOs confirmed against `apps/server/src/api/{spending,holdings,
assets}.rs` and their matching `crates/*` model files on
`github.com/wealthfolio/wealthfolio@main`.
There is no dedicated "cash balance" endpoint --
`WealthfolioClient.get_cash_balances` is adapted onto
`POST /api/v1/valuations/current/query`, the real live (not historical)
per-scope valuation endpoint. `get_asset_allocation` IS a real
server-computed endpoint (`POST /api/v1/allocations/query`), not a
client-side aggregation. `Asset.metadata` is the server's own structured
per-instrument-type JSON -- distinct from a host application's own
free-form namespace (if any), which lives under `provider_config` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .activities import Activity
from .common import _get, _get_float, _get_list, _parse_items, _parse_nested
from .taxonomies import ActivityTaxonomyAssignment


@dataclass
class CurrencyNet:
    currency: Optional[str] = None
    amount: Optional[float] = None

    @classmethod
    def from_dict(cls, data: dict) -> "CurrencyNet":
        data = data if isinstance(data, dict) else {}
        return cls(currency=_get(data, "currency"), amount=_get_float(data, "amount"))


@dataclass
class NetSummary:
    by_currency: List[CurrencyNet] = _field(default_factory=list)
    converted: Optional[CurrencyNet] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "NetSummary":
        data = data if isinstance(data, dict) else {}
        return cls(
            by_currency=_parse_items(CurrencyNet, _get_list(data, "byCurrency")),
            converted=_parse_nested(CurrencyNet, data, "converted"),
            raw=data,
        )


@dataclass
class CashActivity:
    """A spending-domain row: `crates/spending::cash_activities::CashActivity`
    flattens the portfolio-wide `Activity` (see `activity`, reusing the
    `activities` module's `Activity` dataclass for that shared shape) and
    adds the spending-only enrichments below. `splits` is left as raw dicts
    (the nested `ActivitySplit` shape is not modeled)."""

    activity: Optional[Activity] = None
    cash_flow_bucket: Optional[str] = None
    assignments: List[ActivityTaxonomyAssignment] = _field(default_factory=list)
    splits: List[dict] = _field(default_factory=list)
    event_id: Optional[str] = None
    transfer_link_status: Optional[str] = None
    net_amount: Optional[float] = None
    net_amount_base: Optional[float] = None
    visible_spending_amount: Optional[float] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CashActivity":
        data = data if isinstance(data, dict) else {}
        return cls(
            activity=Activity.from_dict(data),
            cash_flow_bucket=_get(data, "cashFlowBucket"),
            assignments=_parse_items(ActivityTaxonomyAssignment, _get_list(data, "assignments")),
            splits=_get_list(data, "splits"),
            event_id=_get(data, "eventId"),
            transfer_link_status=_get(data, "transferLinkStatus"),
            net_amount=_get_float(data, "netAmount"),
            net_amount_base=_get_float(data, "netAmountBase"),
            visible_spending_amount=_get_float(data, "visibleSpendingAmount"),
            raw=data,
        )


@dataclass
class CashActivitySearchResult:
    """`POST /api/v1/spending/cash-activities/search`'s response
    (`CashActivitySearchResponse`) -- powers
    `WealthfolioClient.list_categorization_context`."""

    items: List[CashActivity] = _field(default_factory=list)
    total_count: Optional[int] = None
    net: Optional[NetSummary] = None
    base_currency: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CashActivitySearchResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            items=_parse_items(CashActivity, _get_list(data, "items")),
            total_count=_get(data, "totalCount"),
            net=_parse_nested(NetSummary, data, "net"),
            base_currency=_get(data, "baseCurrency"),
            raw=data,
        )


@dataclass
class CategorizationRule:
    id: Optional[str] = None
    name: Optional[str] = None
    pattern: Optional[str] = None
    match_type: Optional[str] = None
    taxonomy_id: Optional[str] = None
    category_id: Optional[str] = None
    activity_type: Optional[str] = None
    amount_op: Optional[str] = None
    amount_value: Optional[float] = None
    amount_value2: Optional[float] = None
    priority: Optional[int] = None
    is_global: Optional[bool] = None
    account_id: Optional[str] = None
    preset_id: Optional[str] = None
    preset_rule_key: Optional[str] = None
    preset_version: Optional[str] = None
    preset_modified: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CategorizationRule":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            name=_get(data, "name"),
            pattern=_get(data, "pattern"),
            match_type=_get(data, "matchType"),
            taxonomy_id=_get(data, "taxonomyId"),
            category_id=_get(data, "categoryId"),
            activity_type=_get(data, "activityType"),
            amount_op=_get(data, "amountOp"),
            amount_value=_get_float(data, "amountValue"),
            amount_value2=_get_float(data, "amountValue2"),
            priority=_get(data, "priority"),
            is_global=_get(data, "isGlobal"),
            account_id=_get(data, "accountId"),
            preset_id=_get(data, "presetId"),
            preset_rule_key=_get(data, "presetRuleKey"),
            preset_version=_get(data, "presetVersion"),
            preset_modified=_get(data, "presetModified"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )


@dataclass
class CurrencyValuationSplit:
    """One entry of `CurrentValuationSummary.currencySplit`/
    `cashCurrencySplit` -- how much of the total (or of cash alone) sits
    in one currency."""

    currency: Optional[str] = None
    value_base: Optional[float] = None
    value_local: Optional[float] = None
    percentage: Optional[float] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CurrencyValuationSplit":
        data = data if isinstance(data, dict) else {}
        return cls(
            currency=_get(data, "currency"),
            value_base=_get_float(data, "valueBase"),
            value_local=_get_float(data, "valueLocal"),
            percentage=_get_float(data, "percentage"),
            raw=data,
        )


@dataclass
class CurrentAccountValuation:
    """One account's row in `CurrentValuationResponse.accounts` -- only
    populated when `get_cash_balances(include_accounts=True)`."""

    account_id: Optional[str] = None
    account_currency: Optional[str] = None
    base_currency: Optional[str] = None
    fx_rate_to_base: Optional[float] = None
    cash_balance: Optional[float] = None
    investment_market_value: Optional[float] = None
    total_value: Optional[float] = None
    cash_balance_base: Optional[float] = None
    investment_market_value_base: Optional[float] = None
    total_value_base: Optional[float] = None
    source_data_as_of: Optional[str] = None
    calculated_at: Optional[str] = None
    warnings: List[str] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CurrentAccountValuation":
        data = data if isinstance(data, dict) else {}
        warnings = _get(data, "warnings", [])
        return cls(
            account_id=_get(data, "accountId"),
            account_currency=_get(data, "accountCurrency"),
            base_currency=_get(data, "baseCurrency"),
            fx_rate_to_base=_get_float(data, "fxRateToBase"),
            cash_balance=_get_float(data, "cashBalance"),
            investment_market_value=_get_float(data, "investmentMarketValue"),
            total_value=_get_float(data, "totalValue"),
            cash_balance_base=_get_float(data, "cashBalanceBase"),
            investment_market_value_base=_get_float(data, "investmentMarketValueBase"),
            total_value_base=_get_float(data, "totalValueBase"),
            source_data_as_of=_get(data, "sourceDataAsOf"),
            calculated_at=_get(data, "calculatedAt"),
            warnings=warnings if isinstance(warnings, list) else [],
            raw=data,
        )


@dataclass
class CurrentValuationSummary:
    scope_id: Optional[str] = None
    base_currency: Optional[str] = None
    cash_balance_base: Optional[float] = None
    investment_market_value_base: Optional[float] = None
    total_value_base: Optional[float] = None
    holdings_count: Optional[int] = None
    account_count: Optional[int] = None
    currency_split: List[CurrencyValuationSplit] = _field(default_factory=list)
    cash_currency_split: List[CurrencyValuationSplit] = _field(default_factory=list)
    source_data_as_of: Optional[str] = None
    calculated_at: Optional[str] = None
    warnings: List[str] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CurrentValuationSummary":
        data = data if isinstance(data, dict) else {}
        warnings = _get(data, "warnings", [])
        return cls(
            scope_id=_get(data, "scopeId"),
            base_currency=_get(data, "baseCurrency"),
            cash_balance_base=_get_float(data, "cashBalanceBase"),
            investment_market_value_base=_get_float(data, "investmentMarketValueBase"),
            total_value_base=_get_float(data, "totalValueBase"),
            holdings_count=_get(data, "holdingsCount"),
            account_count=_get(data, "accountCount"),
            currency_split=_parse_items(CurrencyValuationSplit, _get_list(data, "currencySplit")),
            cash_currency_split=_parse_items(
                CurrencyValuationSplit, _get_list(data, "cashCurrencySplit")
            ),
            source_data_as_of=_get(data, "sourceDataAsOf"),
            calculated_at=_get(data, "calculatedAt"),
            warnings=warnings if isinstance(warnings, list) else [],
            raw=data,
        )


@dataclass
class CashBalancesResult:
    """`POST /api/v1/valuations/current/query`'s response
    (`CurrentValuationResponse`) -- powers
    `WealthfolioClient.get_cash_balances`. `.summary.cash_currency_split`
    is the per-currency cash breakdown; `.accounts` is only populated
    when the call passed `include_accounts=True`."""

    summary: Optional[CurrentValuationSummary] = None
    accounts: List[CurrentAccountValuation] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CashBalancesResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            summary=_parse_nested(CurrentValuationSummary, data, "summary"),
            accounts=_parse_items(CurrentAccountValuation, _get_list(data, "accounts")),
            raw=data,
        )


@dataclass
class CategoryAllocation:
    """One taxonomy category's slice of the portfolio. `children` is only
    populated for rolled-up parent categories (drill-down); a synthetic
    `is_residual` child holds the part of a parent with no sub-category
    assignment."""

    category_id: Optional[str] = None
    category_name: Optional[str] = None
    color: Optional[str] = None
    value: Optional[float] = None
    percentage: Optional[float] = None
    children: List["CategoryAllocation"] = _field(default_factory=list)
    is_residual: Optional[bool] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CategoryAllocation":
        data = data if isinstance(data, dict) else {}
        return cls(
            category_id=_get(data, "categoryId"),
            category_name=_get(data, "categoryName"),
            color=_get(data, "color"),
            value=_get_float(data, "value"),
            percentage=_get_float(data, "percentage"),
            children=_parse_items(CategoryAllocation, _get_list(data, "children")),
            is_residual=_get(data, "isResidual"),
            raw=data,
        )


@dataclass
class TaxonomyAllocation:
    """A full taxonomy's category breakdown (e.g. "Asset Classes",
    "Sectors") -- one of the fixed fields on `AssetAllocationResult`, or
    one entry of its `custom_groups`."""

    taxonomy_id: Optional[str] = None
    taxonomy_name: Optional[str] = None
    color: Optional[str] = None
    categories: List[CategoryAllocation] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "TaxonomyAllocation":
        data = data if isinstance(data, dict) else {}
        return cls(
            taxonomy_id=_get(data, "taxonomyId"),
            taxonomy_name=_get(data, "taxonomyName"),
            color=_get(data, "color"),
            categories=_parse_items(CategoryAllocation, _get_list(data, "categories")),
            raw=data,
        )


@dataclass
class AssetAllocationResult:
    """`POST /api/v1/allocations/query`'s response (`PortfolioAllocations`)
    -- powers `WealthfolioClient.get_asset_allocation`. Five fixed
    taxonomy breakdowns (asset class, sector, region, risk category,
    security type) plus any user-defined custom taxonomy groups."""

    asset_classes: Optional[TaxonomyAllocation] = None
    sectors: Optional[TaxonomyAllocation] = None
    regions: Optional[TaxonomyAllocation] = None
    risk_category: Optional[TaxonomyAllocation] = None
    security_types: Optional[TaxonomyAllocation] = None
    custom_groups: List[TaxonomyAllocation] = _field(default_factory=list)
    total_value: Optional[float] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "AssetAllocationResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            asset_classes=_parse_nested(TaxonomyAllocation, data, "assetClasses"),
            sectors=_parse_nested(TaxonomyAllocation, data, "sectors"),
            regions=_parse_nested(TaxonomyAllocation, data, "regions"),
            risk_category=_parse_nested(TaxonomyAllocation, data, "riskCategory"),
            security_types=_parse_nested(TaxonomyAllocation, data, "securityTypes"),
            custom_groups=_parse_items(TaxonomyAllocation, _get_list(data, "customGroups")),
            total_value=_get_float(data, "totalValue"),
            raw=data,
        )


@dataclass
class Asset:
    """`Asset` (`crates/core/src/assets/assets_model.rs`) -- powers
    `WealthfolioClient.list_assets`/`create_asset`/`update_asset_profile`,
    and is embedded inside `AssetProfile` for `get_asset`."""

    id: Optional[str] = None
    kind: Optional[str] = None
    name: Optional[str] = None
    display_code: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    quote_mode: Optional[str] = None
    quote_ccy: Optional[str] = None
    instrument_type: Optional[str] = None
    instrument_symbol: Optional[str] = None
    instrument_exchange_mic: Optional[str] = None
    instrument_key: Optional[str] = None
    provider_config: Optional[Dict[str, Any]] = None
    exchange_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Asset":
        data = data if isinstance(data, dict) else {}
        metadata = _get(data, "metadata")
        provider_config = _get(data, "providerConfig")
        return cls(
            id=_get(data, "id"),
            kind=_get(data, "kind"),
            name=_get(data, "name"),
            display_code=_get(data, "displayCode"),
            notes=_get(data, "notes"),
            metadata=metadata if isinstance(metadata, dict) else None,
            is_active=_get(data, "isActive"),
            quote_mode=_get(data, "quoteMode"),
            quote_ccy=_get(data, "quoteCcy"),
            instrument_type=_get(data, "instrumentType"),
            instrument_symbol=_get(data, "instrumentSymbol"),
            instrument_exchange_mic=_get(data, "instrumentExchangeMic"),
            instrument_key=_get(data, "instrumentKey"),
            provider_config=provider_config if isinstance(provider_config, dict) else None,
            exchange_name=_get(data, "exchangeName"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )


@dataclass
class AssetsResult:
    """Client-side convenience wrapper around `GET /api/v1/assets`'s bare
    array response -- see `Asset`'s module comment above and
    `AccountsResult`'s identical convention. `count` is always derived
    from `len(assets)`, never sourced from the server (there is no
    envelope)."""

    assets: List[Asset] = _field(default_factory=list)
    count: Optional[int] = None
    raw: Any = None

    @classmethod
    def from_dict(cls, data) -> "AssetsResult":
        """Accepts either the real server shape (a bare list) or a dict
        with an `assets` key, so callers never need to special-case which
        one they were handed."""
        if isinstance(data, list):
            items = _parse_items(Asset, data)
        else:
            items = _parse_items(Asset, _get_list(data, "assets"))
        return cls(assets=items, count=len(items), raw=data)


@dataclass
class AssetProfile:
    """`GET /api/v1/assets/profile?assetId=...`'s response
    (`AssetProfile`) -- powers `WealthfolioClient.get_asset`. The Rust
    struct `#[serde(flatten)]`s every `Asset` field into the JSON object's
    top level and adds two derived valuation fields alongside them;
    `asset` here reparses that same top-level object through
    `Asset.from_dict` (harmless -- the two extra keys below are simply
    ignored by `Asset.from_dict`)."""

    asset: Optional[Asset] = None
    valuation_market_price: Optional[float] = None
    valuation_market_currency: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "AssetProfile":
        data = data if isinstance(data, dict) else {}
        return cls(
            asset=Asset.from_dict(data),
            valuation_market_price=_get_float(data, "valuationMarketPrice"),
            valuation_market_currency=_get(data, "valuationMarketCurrency"),
            raw=data,
        )


@dataclass
class SnapshotInfo:
    """One entry of `GET /snapshots`'s bare `SnapshotInfo[]` response --
    metadata about a stored snapshot, not its actual holdings/cash detail
    (use `WealthfolioClient.get_holdings` or the (unimplemented) `GET
    /snapshots/holdings` for that)."""

    id: Optional[str] = None
    snapshot_date: Optional[str] = None
    is_date_valid: Optional[bool] = None
    source: Optional[str] = None
    position_count: Optional[int] = None
    cash_currency_count: Optional[int] = None
    cash_total_account_currency: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "SnapshotInfo":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            snapshot_date=_get(data, "snapshotDate"),
            is_date_valid=_get(data, "isDateValid"),
            source=_get(data, "source"),
            position_count=_get(data, "positionCount"),
            cash_currency_count=_get(data, "cashCurrencyCount"),
            cash_total_account_currency=_get(data, "cashTotalAccountCurrency"),
            raw=data,
        )


@dataclass
class SnapshotsResult:
    """Client-side wrapper around `GET /snapshots`'s bare `SnapshotInfo[]`
    response -- same convention as `AccountsResult`. `account_id`/
    `date_from`/`date_to` echo the request scope for caller convenience,
    set by `WealthfolioClient.get_snapshots`, not parsed from the
    response."""

    snapshots: List[SnapshotInfo] = _field(default_factory=list)
    count: Optional[int] = None
    account_id: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    raw: Any = None

    @classmethod
    def from_dict(cls, data, *, account_id=None, date_from=None, date_to=None) -> "SnapshotsResult":
        items = _parse_items(SnapshotInfo, data) if isinstance(data, list) else []
        return cls(
            snapshots=items,
            count=len(items),
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
            raw=data,
        )


@dataclass
class SnapshotSymbolCheckResult:
    """One entry of `CheckHoldingsImportResult.symbols` -- per-symbol
    resolution status for the positions across every checked snapshot
    (deduplicated by symbol server-side). Empty for cash-only snapshots
    (no `positions`, e.g. a HOLDINGS-mode account with no securities)."""

    symbol: Optional[str] = None
    found: Optional[bool] = None
    asset_name: Optional[str] = None
    asset_id: Optional[str] = None
    currency: Optional[str] = None
    exchange_mic: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "SnapshotSymbolCheckResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            symbol=_get(data, "symbol"),
            found=_get(data, "found"),
            asset_name=_get(data, "assetName"),
            asset_id=_get(data, "assetId"),
            currency=_get(data, "currency"),
            exchange_mic=_get(data, "exchangeMic"),
            raw=data,
        )


@dataclass
class CheckHoldingsImportResult:
    """`POST /snapshots/import/check`'s response -- validates a batch of
    holdings snapshots without persisting anything. `existing_dates` is
    informational (re-importing overwrites, see module note above), and
    `valid_snapshot_dates`/`invalid_snapshot_dates` partition every
    submitted snapshot's date by whether it passed validation."""

    existing_dates: List[str] = _field(default_factory=list)
    symbols: List[SnapshotSymbolCheckResult] = _field(default_factory=list)
    validation_errors: List[str] = _field(default_factory=list)
    valid_snapshot_dates: List[str] = _field(default_factory=list)
    invalid_snapshot_dates: List[str] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CheckHoldingsImportResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            existing_dates=_get_list(data, "existingDates"),
            symbols=_parse_items(SnapshotSymbolCheckResult, _get_list(data, "symbols")),
            validation_errors=_get_list(data, "validationErrors"),
            valid_snapshot_dates=_get_list(data, "validSnapshotDates"),
            invalid_snapshot_dates=_get_list(data, "invalidSnapshotDates"),
            raw=data,
        )


@dataclass
class ImportHoldingsCsvResult:
    """`POST /snapshots/import`'s response -- actually persists the batch.
    Each snapshot is imported independently: a per-date failure is
    reflected here (`snapshots_failed`/`errors`), not raised as a
    whole-request `WealthfolioAPIError`."""

    snapshots_imported: Optional[int] = None
    snapshots_failed: Optional[int] = None
    errors: List[str] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ImportHoldingsCsvResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            snapshots_imported=_get(data, "snapshotsImported"),
            snapshots_failed=_get(data, "snapshotsFailed"),
            errors=_get_list(data, "errors"),
            raw=data,
        )
