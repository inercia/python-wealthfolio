"""Typed response models for the Wealthfolio REST client's activities
surface.

Field names sourced from `apps/server/src/api/activities.rs` and
`crates/core/src/activities/activities_model.rs` on
`github.com/wealthfolio/wealthfolio@main`. Two real
API asymmetries to keep in mind everywhere below:

  1. `ActivityDetails` (returned by `POST /activities/search`) names its
     free-text notes field `comment`. `Activity` (returned by
     create/update/delete) names the *same* semantic field `notes`
     instead (though `NewActivity`/`ActivityUpdate` also accept `comment`
     as a write-side alias). These are genuinely different wire field
     names on different DTOs -- `ActivityDetails.comment` and
     `Activity.notes` are intentionally NOT unified into one name.
  2. `metadata` is a JSON **string** on write (`NewActivity.metadata` /
     `ActivityUpdate.metadata` are `Option<String>` in Rust) but a JSON
     **object** on read (`Activity.metadata` / `ActivityDetails.metadata`
     are `Option<Value>`). Both model classes below simply pass through
     whatever the server sent for `metadata` (already-parsed dict on
     read) -- the string-encoding-on-write side of this asymmetry is
     `WealthfolioClient`'s job (`client.py`), not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import _get, _get_float, _get_list, _parse_items


@dataclass
class ActivityDetails:
    """The `POST /api/v1/activities/search` result shape: an activity
    enriched with joined account/asset display fields. Uses `comment` for
    the notes field -- see the asymmetry note above `Activity`."""

    id: Optional[str] = None
    account_id: Optional[str] = None
    asset_id: Optional[str] = None
    activity_type: Optional[str] = None
    subtype: Optional[str] = None
    status: Optional[str] = None
    date: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    fee: Optional[float] = None
    tax: Optional[float] = None
    amount: Optional[float] = None
    needs_review: Optional[bool] = None
    comment: Optional[str] = None
    fx_rate: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    account_name: Optional[str] = None
    account_currency: Optional[str] = None
    asset_symbol: Optional[str] = None
    asset_name: Optional[str] = None
    exchange_mic: Optional[str] = None
    asset_pricing_mode: Optional[str] = None
    instrument_type: Optional[str] = None
    asset_contract_multiplier: Optional[float] = None
    source_system: Optional[str] = None
    source_record_id: Optional[str] = None
    source_group_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    import_run_id: Optional[str] = None
    is_user_modified: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ActivityDetails":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            account_id=_get(data, "accountId"),
            asset_id=_get(data, "assetId"),
            activity_type=_get(data, "activityType"),
            subtype=_get(data, "subtype"),
            status=_get(data, "status"),
            date=_get(data, "date"),
            quantity=_get_float(data, "quantity"),
            unit_price=_get_float(data, "unitPrice"),
            currency=_get(data, "currency"),
            fee=_get_float(data, "fee"),
            tax=_get_float(data, "tax"),
            amount=_get_float(data, "amount"),
            needs_review=_get(data, "needsReview"),
            comment=_get(data, "comment"),
            fx_rate=_get_float(data, "fxRate"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            account_name=_get(data, "accountName"),
            account_currency=_get(data, "accountCurrency"),
            asset_symbol=_get(data, "assetSymbol"),
            asset_name=_get(data, "assetName"),
            exchange_mic=_get(data, "exchangeMic"),
            asset_pricing_mode=_get(data, "assetPricingMode"),
            instrument_type=_get(data, "instrumentType"),
            asset_contract_multiplier=_get_float(data, "assetContractMultiplier"),
            source_system=_get(data, "sourceSystem"),
            source_record_id=_get(data, "sourceRecordId"),
            source_group_id=_get(data, "sourceGroupId"),
            idempotency_key=_get(data, "idempotencyKey"),
            import_run_id=_get(data, "importRunId"),
            is_user_modified=_get(data, "isUserModified"),
            metadata=_get(data, "metadata"),
            raw=data,
        )


@dataclass
class ActivitiesResult:
    """Client-side wrapper around `POST /api/v1/activities/search`'s
    `{data: ActivityDetails[], meta: {totalRowCount}}` response. `page` /
    `page_size` are the request values echoed back for caller convenience
    (the server response itself carries no paging echo beyond
    `totalRowCount`) -- set by `WealthfolioClient.search_activities`, not
    parsed from the response body."""

    activities: List[ActivityDetails] = _field(default_factory=list)
    total_row_count: Optional[int] = None
    page: Optional[int] = None
    page_size: Optional[int] = None
    raw: Any = None

    @classmethod
    def from_dict(cls, data, *, page=None, page_size=None) -> "ActivitiesResult":
        data = data if isinstance(data, dict) else {}
        meta = _get(data, "meta")
        return cls(
            activities=_parse_items(ActivityDetails, _get_list(data, "data")),
            total_row_count=_get(meta, "totalRowCount") if isinstance(meta, dict) else None,
            page=page,
            page_size=page_size,
            raw=data,
        )


@dataclass
class Activity:
    """The create/update/delete result shape (`Activity` in
    `activities_model.rs`) -- a plainer row than `ActivityDetails`, with no
    joined account/asset display fields. Uses `notes` for the free-text
    field -- see the asymmetry note above `ActivityDetails`. Do not conflate
    the two: `Activity` never carries `accountName`/`assetSymbol`/etc."""

    id: Optional[str] = None
    account_id: Optional[str] = None
    asset_id: Optional[str] = None
    activity_type: Optional[str] = None
    activity_type_override: Optional[str] = None
    source_type: Optional[str] = None
    subtype: Optional[str] = None
    status: Optional[str] = None
    activity_date: Optional[str] = None
    settlement_date: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    fee: Optional[float] = None
    tax: Optional[float] = None
    currency: Optional[str] = None
    fx_rate: Optional[float] = None
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    source_system: Optional[str] = None
    source_record_id: Optional[str] = None
    source_group_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    import_run_id: Optional[str] = None
    is_user_modified: Optional[bool] = None
    needs_review: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Activity":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            account_id=_get(data, "accountId"),
            asset_id=_get(data, "assetId"),
            activity_type=_get(data, "activityType"),
            activity_type_override=_get(data, "activityTypeOverride"),
            source_type=_get(data, "sourceType"),
            subtype=_get(data, "subtype"),
            status=_get(data, "status"),
            activity_date=_get(data, "activityDate"),
            settlement_date=_get(data, "settlementDate"),
            quantity=_get_float(data, "quantity"),
            unit_price=_get_float(data, "unitPrice"),
            amount=_get_float(data, "amount"),
            fee=_get_float(data, "fee"),
            tax=_get_float(data, "tax"),
            currency=_get(data, "currency"),
            fx_rate=_get_float(data, "fxRate"),
            notes=_get(data, "notes"),
            metadata=_get(data, "metadata"),
            source_system=_get(data, "sourceSystem"),
            source_record_id=_get(data, "sourceRecordId"),
            source_group_id=_get(data, "sourceGroupId"),
            idempotency_key=_get(data, "idempotencyKey"),
            import_run_id=_get(data, "importRunId"),
            is_user_modified=_get(data, "isUserModified"),
            needs_review=_get(data, "needsReview"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )


@dataclass
class ActivityMapping:
    """One `{tempId, activityId}` entry from
    `ActivityBulkMutationResult.createdMappings` -- lets a caller who
    submitted `creates` with client-generated temporary ids find the real
    server-assigned id for each created row."""

    temp_id: Optional[str] = None
    activity_id: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ActivityMapping":
        data = data if isinstance(data, dict) else {}
        return cls(
            temp_id=_get(data, "tempId"),
            activity_id=_get(data, "activityId"),
            raw=data,
        )


@dataclass
class ActivityMutationError:
    """One `{id, action, message}` entry from
    `ActivityBulkMutationResult.errors` -- a single failed item within an
    otherwise-successful bulk mutation (the endpoint does not roll back the
    whole batch on a per-item failure)."""

    id: Optional[str] = None
    action: Optional[str] = None
    message: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ActivityMutationError":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            action=_get(data, "action"),
            message=_get(data, "message"),
            raw=data,
        )


@dataclass
class ActivityBulkMutationResult:
    """`POST /api/v1/activities/bulk`'s response: `created`/`updated`/
    `deleted` are full `Activity` rows (the `notes`/`metadata`-shape, same
    as single create/update/delete), `created_mappings` resolves any
    client-supplied temporary ids in `creates`, and `errors` lists any
    individual items that failed without aborting the rest of the batch."""

    created: List[Activity] = _field(default_factory=list)
    updated: List[Activity] = _field(default_factory=list)
    deleted: List[Activity] = _field(default_factory=list)
    created_mappings: List[ActivityMapping] = _field(default_factory=list)
    errors: List[ActivityMutationError] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ActivityBulkMutationResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            created=_parse_items(Activity, _get_list(data, "created")),
            updated=_parse_items(Activity, _get_list(data, "updated")),
            deleted=_parse_items(Activity, _get_list(data, "deleted")),
            created_mappings=_parse_items(
                ActivityMapping, _get_list(data, "createdMappings")
            ),
            errors=_parse_items(ActivityMutationError, _get_list(data, "errors")),
            raw=data,
        )
