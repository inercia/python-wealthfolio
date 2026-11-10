"""Typed response models for the Wealthfolio REST client's accounts surface.

Field names were sourced directly from the live OpenAPI schema
(`GET /api/v1/openapi.json` on a live Wealthfolio instance) --
`components.schemas.Account` / `NewAccount` / `AccountUpdate`.
Confirmed live:

  * `GET /api/v1/accounts` returns a **bare JSON array** of `Account`
    objects, not `{"accounts": [...]}`. `AccountsResult` is a client-side
    convenience wrapper only -- it never reflects an actual server envelope
    -- so `from_list`/`from_dict` accept either shape.
  * `Account` has more fields than the MCP SDK's version: `isDefault`,
    `isArchived`, `trackingMode`, `accountNumber`, `group`, `meta`,
    `platformId`, `provider`, `providerAccountId`, `createdAt`, `updatedAt`.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import _get, _get_list, _parse_items


@dataclass
class Account:
    id: Optional[str] = None
    name: Optional[str] = None
    account_type: Optional[str] = None
    currency: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None
    tracking_mode: Optional[str] = None
    account_number: Optional[str] = None
    group: Optional[str] = None
    meta: Optional[str] = None
    platform_id: Optional[str] = None
    provider: Optional[str] = None
    provider_account_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            name=_get(data, "name"),
            account_type=_get(data, "accountType"),
            currency=_get(data, "currency"),
            is_default=_get(data, "isDefault"),
            is_active=_get(data, "isActive"),
            is_archived=_get(data, "isArchived"),
            tracking_mode=_get(data, "trackingMode"),
            account_number=_get(data, "accountNumber"),
            group=_get(data, "group"),
            meta=_get(data, "meta"),
            platform_id=_get(data, "platformId"),
            provider=_get(data, "provider"),
            provider_account_id=_get(data, "providerAccountId"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )


@dataclass
class AccountsResult:
    """Client-side convenience wrapper around `GET /api/v1/accounts`'s bare
    array response -- see module docstring. `count` is always derived from
    `len(accounts)`, never sourced from the server (there is no envelope)."""

    accounts: List[Account] = _field(default_factory=list)
    count: Optional[int] = None
    raw: Any = None

    @classmethod
    def from_dict(cls, data) -> "AccountsResult":
        """Accepts either the real server shape (a bare list) or a dict
        with an `accounts` key, so callers never need to special-case
        which one they were handed."""
        if isinstance(data, list):
            items = _parse_items(Account, data)
        else:
            items = _parse_items(Account, _get_list(data, "accounts"))
        return cls(accounts=items, count=len(items), raw=data)
