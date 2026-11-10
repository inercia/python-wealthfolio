"""Typed response models for the Wealthfolio REST client's activity import
surface.

Endpoint/DTO confirmed against
`apps/server/src/api/activities.rs` and
`crates/core/src/activities/activities_model.rs`. A real two-step REST
flow, not an adaptation: `WealthfolioClient.prepare_activity_import` hits
`POST /api/v1/activities/import/check` (validates/dedups a batch without
persisting -- populates `.errors`/`.warnings`/`.duplicateOfId` per row),
`WealthfolioClient.commit_activity_import` hits
`POST /api/v1/activities/import` (actually persists). Both take/return the
same `ActivityImport`-shaped rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import _get, _get_float, _get_list, _parse_items, _parse_nested


@dataclass
class ActivityImportRow:
    """One row of the `ActivityImport` wire shape -- both the input echo
    and the validated/imported output of `prepare_activity_import`/
    `commit_activity_import`. `is_draft`/`is_valid` have no server-side
    default (unlike most other fields here) -- always send them
    explicitly when building a request row."""

    id: Optional[str] = None
    date: Optional[str] = None
    symbol: Optional[str] = None
    activity_type: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    fee: Optional[float] = None
    tax: Optional[float] = None
    amount: Optional[float] = None
    comment: Optional[str] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    symbol_name: Optional[str] = None
    exchange_mic: Optional[str] = None
    quote_ccy: Optional[str] = None
    instrument_type: Optional[str] = None
    quote_mode: Optional[str] = None
    provider_id: Optional[str] = None
    provider_symbol: Optional[str] = None
    errors: Dict[str, List[str]] = _field(default_factory=dict)
    warnings: Dict[str, List[str]] = _field(default_factory=dict)
    duplicate_of_id: Optional[str] = None
    duplicate_of_line_number: Optional[int] = None
    is_draft: Optional[bool] = None
    is_valid: Optional[bool] = None
    line_number: Optional[int] = None
    fx_rate: Optional[float] = None
    subtype: Optional[str] = None
    asset_id: Optional[str] = None
    isin: Optional[str] = None
    force_import: Optional[bool] = None
    is_external: Optional[bool] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ActivityImportRow":
        data = data if isinstance(data, dict) else {}
        errors = _get(data, "errors", {})
        warnings = _get(data, "warnings", {})
        return cls(
            id=_get(data, "id"),
            date=_get(data, "date"),
            symbol=_get(data, "symbol"),
            activity_type=_get(data, "activityType"),
            quantity=_get_float(data, "quantity"),
            unit_price=_get_float(data, "unitPrice"),
            currency=_get(data, "currency"),
            fee=_get_float(data, "fee"),
            tax=_get_float(data, "tax"),
            amount=_get_float(data, "amount"),
            comment=_get(data, "comment"),
            account_id=_get(data, "accountId"),
            account_name=_get(data, "accountName"),
            symbol_name=_get(data, "symbolName"),
            exchange_mic=_get(data, "exchangeMic"),
            quote_ccy=_get(data, "quoteCcy"),
            instrument_type=_get(data, "instrumentType"),
            quote_mode=_get(data, "quoteMode"),
            provider_id=_get(data, "providerId"),
            provider_symbol=_get(data, "providerSymbol"),
            errors=errors if isinstance(errors, dict) else {},
            warnings=warnings if isinstance(warnings, dict) else {},
            duplicate_of_id=_get(data, "duplicateOfId"),
            duplicate_of_line_number=_get(data, "duplicateOfLineNumber"),
            is_draft=_get(data, "isDraft"),
            is_valid=_get(data, "isValid"),
            line_number=_get(data, "lineNumber"),
            fx_rate=_get_float(data, "fxRate"),
            subtype=_get(data, "subtype"),
            asset_id=_get(data, "assetId"),
            isin=_get(data, "isin"),
            force_import=_get(data, "forceImport"),
            is_external=_get(data, "isExternal"),
            raw=data,
        )


@dataclass
class PrepareActivityImportResult:
    """Client-side convenience wrapper around
    `POST /api/v1/activities/import/check`'s bare array response --
    powers `WealthfolioClient.prepare_activity_import` (see
    `AccountsResult` for the same envelope-wrapping pattern)."""

    rows: List[ActivityImportRow] = _field(default_factory=list)
    count: Optional[int] = None
    raw: Any = None

    @classmethod
    def from_dict(cls, data) -> "PrepareActivityImportResult":
        items = _parse_items(ActivityImportRow, data) if isinstance(data, list) else []
        return cls(rows=items, count=len(items), raw=data)


@dataclass
class ImportActivitiesSummary:
    total: Optional[int] = None
    imported: Optional[int] = None
    skipped: Optional[int] = None
    duplicates: Optional[int] = None
    assets_created: Optional[int] = None
    success: Optional[bool] = None
    error_message: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ImportActivitiesSummary":
        data = data if isinstance(data, dict) else {}
        return cls(
            total=_get(data, "total"),
            imported=_get(data, "imported"),
            skipped=_get(data, "skipped"),
            duplicates=_get(data, "duplicates"),
            assets_created=_get(data, "assetsCreated"),
            success=_get(data, "success"),
            error_message=_get(data, "errorMessage"),
            raw=data,
        )


@dataclass
class ImportActivitiesResult:
    """`POST /api/v1/activities/import`'s response
    (`ImportActivitiesResult`) -- powers
    `WealthfolioClient.commit_activity_import`. Unlike
    `prepare_activity_import`, this is a real committed write --
    `import_run_id` identifies the batch (also stamped onto each created
    `Activity.import_run_id`)."""

    activities: List[ActivityImportRow] = _field(default_factory=list)
    import_run_id: Optional[str] = None
    summary: Optional[ImportActivitiesSummary] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ImportActivitiesResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            activities=_parse_items(ActivityImportRow, _get_list(data, "activities")),
            import_run_id=_get(data, "importRunId"),
            summary=_parse_nested(ImportActivitiesSummary, data, "summary"),
            raw=data,
        )


@dataclass
class ImportMappingResult:
    """`GET/POST /api/v1/activities/import/mapping`'s response
    (`ImportMappingData`) -- powers `WealthfolioClient.get_import_mapping`.
    `field_mappings` values are left as raw JSON (either a plain column
    name string or a fallback-column-list -- `FieldMappingValue`'s
    untagged wire shape) rather than typed, since callers only ever
    round-trip them back into a save call. `symbol_mapping_meta` is
    similarly left as raw per-symbol dicts."""

    account_id: Optional[str] = None
    context_kind: Optional[str] = None
    name: Optional[str] = None
    template_id: Optional[str] = None
    field_mappings: Dict[str, Any] = _field(default_factory=dict)
    activity_mappings: Dict[str, List[str]] = _field(default_factory=dict)
    symbol_mappings: Dict[str, str] = _field(default_factory=dict)
    account_mappings: Dict[str, str] = _field(default_factory=dict)
    symbol_mapping_meta: Dict[str, Any] = _field(default_factory=dict)
    parse_config: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ImportMappingResult":
        data = data if isinstance(data, dict) else {}
        field_mappings = _get(data, "fieldMappings", {})
        activity_mappings = _get(data, "activityMappings", {})
        symbol_mappings = _get(data, "symbolMappings", {})
        account_mappings = _get(data, "accountMappings", {})
        symbol_mapping_meta = _get(data, "symbolMappingMeta", {})
        parse_config = _get(data, "parseConfig")
        return cls(
            account_id=_get(data, "accountId"),
            context_kind=_get(data, "contextKind"),
            name=_get(data, "name"),
            template_id=_get(data, "templateId"),
            field_mappings=field_mappings if isinstance(field_mappings, dict) else {},
            activity_mappings=activity_mappings if isinstance(activity_mappings, dict) else {},
            symbol_mappings=symbol_mappings if isinstance(symbol_mappings, dict) else {},
            account_mappings=account_mappings if isinstance(account_mappings, dict) else {},
            symbol_mapping_meta=(
                symbol_mapping_meta if isinstance(symbol_mapping_meta, dict) else {}
            ),
            parse_config=parse_config if isinstance(parse_config, dict) else None,
            raw=data,
        )
