"""Shared helpers and cross-domain value types for the Wealthfolio REST
client's typed response models.

This module is the foundation the domain-specific model modules
(`accounts.py`, `activities.py`, `holdings.py`, `performance.py`,
`net_worth.py`, `income.py`, `goals.py`, `limits.py`, `health.py`,
`portfolios.py`, `taxonomies.py`, `assets.py`, `imports.py`) build on: the
lenient dict-access helpers below, plus the two genuinely cross-cutting
value types (`MonetaryValue`, `Instrument`) referenced from more than one
domain (e.g. `Holding` in `holdings.py`).

Field names throughout this `models/` subpackage were sourced directly
from the live OpenAPI schema (`GET /api/v1/openapi.json` on a live
Wealthfolio instance) and, for several domains, the `wealthfolio`
server's own Rust source. See each domain module's own header comment
for its specific source references.

Design rules:
  * Lenient parsing: every field is `Optional`, defaults to `None`.
    `from_dict` never does a bare `data[key]` lookup and never raises on
    missing/extra keys or non-dict input; the original dict is always kept
    on `.raw`.
  * No currency coercion: monetary/date fields are passed through exactly
    as the server sent them.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, Optional


def _get(data, key, default=None):
    """Lenient dict access: `default` (never a raised error) for a missing
    key, an explicit `None` value, or non-dict input."""
    if not isinstance(data, dict):
        return default
    value = data.get(key, default)
    return default if value is None else value


def _get_list(data, key):
    value = _get(data, key, [])
    return value if isinstance(value, list) else []


def _get_float(data, key, default=None):
    """Lenient numeric access: the live activities API serializes decimal
    fields (`quantity`, `unitPrice`, `fee`, `tax`, `amount`, `fxRate`) as
    JSON *strings*, not numbers -- coerce to `float`, falling back to
    `default` (never raising) for `None`, missing keys, or an unparsable
    value."""
    value = _get(data, key, default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_items(item_cls, items):
    """Parse a list of raw dicts into a list of `item_cls` instances,
    silently skipping any entry that isn't itself a dict."""
    return [item_cls.from_dict(item) for item in items if isinstance(item, dict)]


def _get_dict(data, key):
    value = _get(data, key, {})
    return value if isinstance(value, dict) else {}


def _get_float_dict(data, key):
    """Lenient dict-of-decimal-strings access (e.g. `IncomeSummary.byMonth`)
    -- coerces every value to `float` via the same string-vs-number
    tolerance as `_get_float`, silently dropping any entry that doesn't
    parse instead of raising."""
    result = {}
    for k, v in _get_dict(data, key).items():
        try:
            result[k] = float(v)
        except (TypeError, ValueError):
            continue
    return result


def _parse_dict_items(item_cls, raw_dict):
    """Parse a dict of raw dicts into a dict of `item_cls` instances (e.g.
    `IncomeSummary.byAsset`/`byAccount`), keyed the same, silently skipping
    any value that isn't itself a dict."""
    if not isinstance(raw_dict, dict):
        return {}
    return {k: item_cls.from_dict(v) for k, v in raw_dict.items() if isinstance(v, dict)}


def _parse_nested(item_cls, data, key):
    """Parse a single nested-object field into `item_cls`, or `None` if the
    raw value is missing, explicitly `null`, or not itself a dict (mirrors
    `wealthfolio_mcp.models._parse_optional`, renamed here to avoid
    ambiguity with Python's own `Optional` typing import)."""
    value = _get(data, key)
    return item_cls.from_dict(value) if isinstance(value, dict) else None


# ---- Cross-domain value types ---------------------------------------------
#
# `MonetaryValue` and `Instrument` are referenced from more than one domain
# module (e.g. `holdings.Holding`), so they live here rather than in any
# single domain file. Field names sourced from
# `crates/core/src/portfolio/holdings/holdings_model.rs`.


@dataclass
class MonetaryValue:
    """A local-currency/base-currency pair -- `Holding`'s market value, cost
    basis, gains, etc. are all this shape rather than a single number."""

    local: Optional[float] = None
    base: Optional[float] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "MonetaryValue":
        data = data if isinstance(data, dict) else {}
        return cls(local=_get_float(data, "local"), base=_get_float(data, "base"), raw=data)


@dataclass
class Instrument:
    id: Optional[str] = None
    symbol: Optional[str] = None
    name: Optional[str] = None
    currency: Optional[str] = None
    notes: Optional[str] = None
    pricing_mode: Optional[str] = None
    preferred_provider: Optional[str] = None
    exchange_mic: Optional[str] = None
    instrument_type: Optional[str] = None
    classifications: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Instrument":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            symbol=_get(data, "symbol"),
            name=_get(data, "name"),
            currency=_get(data, "currency"),
            notes=_get(data, "notes"),
            pricing_mode=_get(data, "pricingMode"),
            preferred_provider=_get(data, "preferredProvider"),
            exchange_mic=_get(data, "exchangeMic"),
            instrument_type=_get(data, "instrumentType"),
            classifications=_get(data, "classifications"),
            raw=data,
        )
