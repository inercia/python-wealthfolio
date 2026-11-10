"""Typed response models for the Wealthfolio REST client's health status
surface.

Endpoint/DTO confirmed against
`apps/server/src/api/health.rs` and `crates/core/src/health/model.rs`.

`GET /health/status` returns the cached `HealthStatus` if fresh
(`isStale=false`), else runs a fresh, synchronous check and returns that.
`health.rs` also exposes `/health/check` (force-fresh), `/health/dismiss`,
`/health/restore`, `/health/dismissed`, `/health/fix`, and `/health/config`
-- none of those are implemented here.

`HealthIssue.fixAction`/`navigateAction`/`diagnostics`/`affectedItems` are
deeply nested, internally-tagged-enum shapes (`FixAction`/`NavigateAction`/
`HealthDiagnostic`/`ActionRef`/`Evidence`/...). Modeling every one of those
as its own dataclass is not supported -- they are exposed here
as raw dicts/lists (unparsed pass-through via `.raw`-style access) rather
than typed sub-dataclasses. There is no `note` field on the wire (unlike
`wealthfolio_mcp.models.HealthStatusResult.note`, an MCP-only addition).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import _get, _get_dict, _get_list, _parse_items


@dataclass
class HealthIssue:
    id: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    title: Optional[str] = None
    message: Optional[str] = None
    code: Optional[str] = None
    params: Dict[str, Any] = _field(default_factory=dict)
    affected_count: Optional[int] = None
    affected_mv_pct: Optional[float] = None
    fix_action: Optional[dict] = None
    navigate_action: Optional[dict] = None
    details: Optional[str] = None
    affected_items: List[dict] = _field(default_factory=list)
    diagnostics: List[dict] = _field(default_factory=list)
    data_hash: Optional[str] = None
    timestamp: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "HealthIssue":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            severity=_get(data, "severity"),
            category=_get(data, "category"),
            title=_get(data, "title"),
            message=_get(data, "message"),
            code=_get(data, "code"),
            params=_get_dict(data, "params"),
            affected_count=_get(data, "affectedCount"),
            affected_mv_pct=_get(data, "affectedMvPct"),
            fix_action=_get(data, "fixAction"),
            navigate_action=_get(data, "navigateAction"),
            details=_get(data, "details"),
            affected_items=_get_list(data, "affectedItems"),
            diagnostics=_get_list(data, "diagnostics"),
            data_hash=_get(data, "dataHash"),
            timestamp=_get(data, "timestamp"),
            raw=data,
        )


@dataclass
class HealthStatusResult:
    overall_severity: Optional[str] = None
    issue_counts: Dict[str, Any] = _field(default_factory=dict)
    issues: List[HealthIssue] = _field(default_factory=list)
    checked_at: Optional[str] = None
    is_stale: Optional[bool] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "HealthStatusResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            overall_severity=_get(data, "overallSeverity"),
            issue_counts=_get_dict(data, "issueCounts"),
            issues=_parse_items(HealthIssue, _get_list(data, "issues")),
            checked_at=_get(data, "checkedAt"),
            is_stale=_get(data, "isStale"),
            raw=data,
        )
