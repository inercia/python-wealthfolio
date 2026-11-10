"""Typed response models for the Wealthfolio REST client's asset taxonomy
and activity-categorization-assignment surfaces.

Endpoints/DTOs confirmed against
`apps/server/src/api/taxonomies.rs` and
`crates/core/src/taxonomies/taxonomy_model.rs` on
`github.com/wealthfolio/wealthfolio@main`.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any, Dict, List, Optional

from .common import _get, _get_list, _parse_items, _parse_nested


@dataclass
class Category:
    id: Optional[str] = None
    taxonomy_id: Optional[str] = None
    parent_id: Optional[str] = None
    name: Optional[str] = None
    key: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    icon: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Category":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            taxonomy_id=_get(data, "taxonomyId"),
            parent_id=_get(data, "parentId"),
            name=_get(data, "name"),
            key=_get(data, "key"),
            color=_get(data, "color"),
            description=_get(data, "description"),
            sort_order=_get(data, "sortOrder"),
            icon=_get(data, "icon"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )


@dataclass
class Taxonomy:
    id: Optional[str] = None
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    is_system: Optional[bool] = None
    is_single_select: Optional[bool] = None
    sort_order: Optional[int] = None
    scope: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Taxonomy":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            name=_get(data, "name"),
            color=_get(data, "color"),
            description=_get(data, "description"),
            is_system=_get(data, "isSystem"),
            is_single_select=_get(data, "isSingleSelect"),
            sort_order=_get(data, "sortOrder"),
            scope=_get(data, "scope"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )


@dataclass
class TaxonomyWithCategories:
    """`GET /api/v1/taxonomies/{id}`'s response shape -- one taxonomy plus
    its full category list, or `None` for both fields if the taxonomy was
    not found (the server returns a bare JSON `null` in that case)."""

    taxonomy: Optional[Taxonomy] = None
    categories: List[Category] = _field(default_factory=list)
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "TaxonomyWithCategories":
        data = data if isinstance(data, dict) else {}
        return cls(
            taxonomy=_parse_nested(Taxonomy, data, "taxonomy"),
            categories=_parse_items(Category, _get_list(data, "categories")),
            raw=data,
        )


@dataclass
class TaxonomiesResult:
    """Client-side aggregate for `WealthfolioClient.list_asset_taxonomies`.
    Unlike the other `*Result` wrappers in this module, this one is never
    built from a single HTTP response -- see that method's docstring for
    when `details` is populated (only for a `taxonomy_id` lookup, or when
    `include_categories=True` triggers one follow-up call per taxonomy)."""

    taxonomies: List[Taxonomy] = _field(default_factory=list)
    details: List[TaxonomyWithCategories] = _field(default_factory=list)
    count: Optional[int] = None
    raw: Any = None


@dataclass
class AssetTaxonomyAssignment:
    id: Optional[str] = None
    asset_id: Optional[str] = None
    taxonomy_id: Optional[str] = None
    category_id: Optional[str] = None
    weight: Optional[int] = None
    source: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "AssetTaxonomyAssignment":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            asset_id=_get(data, "assetId"),
            taxonomy_id=_get(data, "taxonomyId"),
            category_id=_get(data, "categoryId"),
            weight=_get(data, "weight"),
            source=_get(data, "source"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )


@dataclass
class TaxonomyAssignmentsResult:
    """Client-side convenience wrapper around
    `GET /api/v1/taxonomies/assignments/asset/{assetId}`'s bare array
    response. `asset_id` echoes the input -- the server itself never
    echoes it back (see `AccountsResult` for the same envelope-wrapping
    pattern)."""

    asset_id: Optional[str] = None
    assignments: List[AssetTaxonomyAssignment] = _field(default_factory=list)
    count: Optional[int] = None
    raw: Any = None


@dataclass
class AssignmentPreview:
    """A locally-echoed, not-yet-persisted assignment, as returned by
    `WealthfolioClient.prepare_asset_classification`. Deliberately has no
    `id`/`created_at`/`updated_at` (unlike `AssetTaxonomyAssignment`) --
    those only exist once a row has actually been written."""

    asset_id: Optional[str] = None
    taxonomy_id: Optional[str] = None
    category_id: Optional[str] = None
    weight: Optional[int] = None
    source: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "AssignmentPreview":
        data = data if isinstance(data, dict) else {}
        return cls(
            asset_id=_get(data, "assetId"),
            taxonomy_id=_get(data, "taxonomyId"),
            category_id=_get(data, "categoryId"),
            weight=_get(data, "weight"),
            source=_get(data, "source"),
            raw=data,
        )


@dataclass
class PrepareAssetClassificationResult:
    """Non-mutating preview returned by
    `WealthfolioClient.prepare_asset_classification` -- see that method's
    docstring for why this holds a real, freshly-fetched
    `current_assignments` plus a locally-echoed `proposed_assignments`
    rather than anything the server itself returned as one payload."""

    asset_id: Optional[str] = None
    taxonomy_id: Optional[str] = None
    current_assignments: List[AssetTaxonomyAssignment] = _field(default_factory=list)
    proposed_assignments: List[AssignmentPreview] = _field(default_factory=list)
    raw: Any = None


@dataclass
class ActivityTaxonomyAssignment:
    """An activity-scope category assignment (distinct wire shape from
    `AssetTaxonomyAssignment`, which is asset-scope) -- `activity_id`
    instead of `asset_id`."""

    id: Optional[str] = None
    activity_id: Optional[str] = None
    taxonomy_id: Optional[str] = None
    category_id: Optional[str] = None
    weight: Optional[int] = None
    source: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = _field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ActivityTaxonomyAssignment":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_get(data, "id"),
            activity_id=_get(data, "activityId"),
            taxonomy_id=_get(data, "taxonomyId"),
            category_id=_get(data, "categoryId"),
            weight=_get(data, "weight"),
            source=_get(data, "source"),
            created_at=_get(data, "createdAt"),
            updated_at=_get(data, "updatedAt"),
            raw=data,
        )
