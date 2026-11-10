"""Typed response models for the Wealthfolio REST client, split into
domain modules (see each submodule's own header comment for its source
references). This package re-exports every public model class so
`from wealthfolio.models import X` (and, transitively, `from wealthfolio
import X`) keeps working exactly as it did when this was a single
`models.py` file.
"""

from .accounts import Account, AccountsResult
from .activities import (
    Activity,
    ActivitiesResult,
    ActivityBulkMutationResult,
    ActivityDetails,
    ActivityMapping,
    ActivityMutationError,
)
from .assets import (
    Asset,
    AssetAllocationResult,
    AssetProfile,
    AssetsResult,
    CashActivity,
    CashActivitySearchResult,
    CashBalancesResult,
    CategorizationRule,
    CategoryAllocation,
    CheckHoldingsImportResult,
    CurrencyNet,
    CurrencyValuationSplit,
    CurrentAccountValuation,
    CurrentValuationSummary,
    ImportHoldingsCsvResult,
    NetSummary,
    SnapshotInfo,
    SnapshotsResult,
    SnapshotSymbolCheckResult,
    TaxonomyAllocation,
)
from .common import Instrument, MonetaryValue
from .goals import Goal, GoalsResult
from .health import HealthIssue, HealthStatusResult
from .holdings import Holding, HoldingsResult
from .imports import (
    ActivityImportRow,
    ImportActivitiesResult,
    ImportActivitiesSummary,
    ImportMappingResult,
    PrepareActivityImportResult,
)
from .income import IncomeByAccount, IncomeByAsset, IncomeSummary
from .limits import ContributionLimit, ContributionLimitsResult
from .net_worth import (
    AssetsSection,
    BreakdownItem,
    LiabilitiesSection,
    NetWorthHistoryPoint,
    NetWorthResult,
    StaleAssetInfo,
)
from .performance import (
    PerformanceAttribution,
    PerformanceDataQuality,
    PerformancePeriod,
    PerformanceResult,
    PerformanceReturns,
    PerformanceRisk,
    PerformanceScopeDescriptor,
    PerformanceSeriesPoint,
    PerformanceSummary,
)
from .portfolios import Portfolio, PortfoliosResult
from .taxonomies import (
    ActivityTaxonomyAssignment,
    AssetTaxonomyAssignment,
    AssignmentPreview,
    Category,
    PrepareAssetClassificationResult,
    Taxonomy,
    TaxonomiesResult,
    TaxonomyAssignmentsResult,
    TaxonomyWithCategories,
)

__all__ = [
    "Account",
    "AccountsResult",
    "Activity",
    "ActivitiesResult",
    "ActivityBulkMutationResult",
    "ActivityDetails",
    "ActivityImportRow",
    "ActivityMapping",
    "ActivityMutationError",
    "ActivityTaxonomyAssignment",
    "Asset",
    "AssetAllocationResult",
    "AssetProfile",
    "AssetsResult",
    "AssetsSection",
    "AssetTaxonomyAssignment",
    "AssignmentPreview",
    "BreakdownItem",
    "CashActivity",
    "CashActivitySearchResult",
    "CashBalancesResult",
    "CategorizationRule",
    "Category",
    "CategoryAllocation",
    "CheckHoldingsImportResult",
    "ContributionLimit",
    "ContributionLimitsResult",
    "CurrencyNet",
    "CurrencyValuationSplit",
    "CurrentAccountValuation",
    "CurrentValuationSummary",
    "Goal",
    "GoalsResult",
    "HealthIssue",
    "HealthStatusResult",
    "Holding",
    "HoldingsResult",
    "ImportActivitiesResult",
    "ImportActivitiesSummary",
    "ImportHoldingsCsvResult",
    "ImportMappingResult",
    "IncomeByAccount",
    "IncomeByAsset",
    "IncomeSummary",
    "Instrument",
    "LiabilitiesSection",
    "MonetaryValue",
    "NetSummary",
    "NetWorthHistoryPoint",
    "NetWorthResult",
    "PerformanceAttribution",
    "PerformanceDataQuality",
    "PerformancePeriod",
    "PerformanceResult",
    "PerformanceReturns",
    "PerformanceRisk",
    "PerformanceScopeDescriptor",
    "PerformanceSeriesPoint",
    "PerformanceSummary",
    "Portfolio",
    "PortfoliosResult",
    "PrepareActivityImportResult",
    "PrepareAssetClassificationResult",
    "SnapshotInfo",
    "SnapshotsResult",
    "SnapshotSymbolCheckResult",
    "StaleAssetInfo",
    "Taxonomy",
    "TaxonomiesResult",
    "TaxonomyAllocation",
    "TaxonomyAssignmentsResult",
    "TaxonomyWithCategories",
]
