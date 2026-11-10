"""HTTP transport + session-cookie authentication for Wealthfolio's REST API
(`https://wealthfolio.example.com/api/v1`), plus the accounts and activities
domain surfaces.

`_RestTransport` knows how to log in, carry the resulting session cookie on
every request, and transparently re-authenticate on a 401.
`WealthfolioClient` layers typed domain methods on top: accounts (see
`get_accounts`/`create_account`/`update_account`/`delete_account`),
activities (see `search_activities`/`iter_activities`/`create_activity`/
`update_activity`/`delete_activity`/`save_activities`), holdings (see
`get_holdings`), performance (see `get_performance_summary`/
`get_performance_history`), net worth (see `get_net_worth`/
`get_net_worth_history`), income (see `get_income_summary`/
`get_income_summary_query`), goals (see `get_goals`), contribution limits
(see `get_contribution_limits`), health status (see `get_health_status`),
portfolios (see `get_portfolios`), asset taxonomies (see
`list_asset_taxonomies`/`get_asset_taxonomy_assignments`/
`prepare_asset_classification`/`commit_asset_classification_draft`),
transaction categorization (see `list_categorization_context`/
`create_categorization_rule` -- `propose_transaction_categories` has no
REST equivalent, see the "Transaction categorization" section below),
cash balances (see `get_cash_balances`, adapted onto the live
per-scope valuation endpoint), asset allocation (see
`get_asset_allocation`, a real server-computed taxonomy breakdown, not a
client-side aggregation), activity import (see `get_import_mapping`/
`prepare_activity_import`/`commit_activity_import` -- a genuine two-step
server-side check/persist flow, not an adaptation), holdings snapshots
(see `get_snapshots`/`check_holdings_import`/`import_holdings_csv`/
`delete_snapshot` -- the mechanism for loading historical balance points
into a HOLDINGS-tracking-mode account, e.g. a pension plan with no
activity ledger; also a check/persist split like activity import), and
assets (see `list_assets`/`get_asset`/`create_asset`/
`update_asset_profile`/`delete_asset` -- direct one-shot writes, like
accounts, with no draft/commit split).
Valuation history
(`/api/v1/valuations/history[/query]`) was deliberately left unimplemented
-- it exists server-side but is outside this client's current scope
(holdings/performance/net worth/income); add it later if a caller needs
the fuller rationale and exact endpoint shape.

**Mutations here are direct, one-shot writes** -- unlike the now-removed
`wealthfolio_mcp` package's `record_activity` + `commit_activity_draft`
two-phase draft/commit pattern,
`create_activity`/`update_activity`/`save_activities` persist immediately on
a single call. Server-side validation still runs synchronously (a bad
request still raises `WealthfolioAPIError`), but there is no separate
draft-review step to skip -- this is a deliberate behavioral divergence from
the MCP SDK, not an oversight.

Network-level failures (`requests.RequestException`, e.g. connection errors
or timeouts) are wrapped into `WealthfolioAPIError` with `status_code=None`
and `body=None`, the same exception raised for a non-2xx HTTP response --
callers distinguish the two cases by checking `status_code is None`.
"""

import json
import math

from .config import WealthfolioRestConfig, load_rest_config
from .exceptions import WealthfolioAPIError
from .models import (
    Account,
    AccountsResult,
    Activity,
    ActivitiesResult,
    ActivityBulkMutationResult,
    Asset,
    AssetAllocationResult,
    AssetProfile,
    AssetsResult,
    AssetTaxonomyAssignment,
    AssignmentPreview,
    CashActivitySearchResult,
    CashBalancesResult,
    CategorizationRule,
    CheckHoldingsImportResult,
    ContributionLimitsResult,
    GoalsResult,
    HealthStatusResult,
    HoldingsResult,
    ImportActivitiesResult,
    ImportHoldingsCsvResult,
    ImportMappingResult,
    IncomeSummary,
    NetWorthHistoryPoint,
    NetWorthResult,
    PerformanceResult,
    PortfoliosResult,
    PrepareActivityImportResult,
    PrepareAssetClassificationResult,
    SnapshotsResult,
    Taxonomy,
    TaxonomiesResult,
    TaxonomyAssignmentsResult,
    TaxonomyWithCategories,
)

ACCOUNTS_PATH = "/api/v1/accounts"
ASSETS_PATH = "/api/v1/assets"
ASSETS_PROFILE_PATH = "/api/v1/assets/profile"
ACTIVITIES_SEARCH_PATH = "/api/v1/activities/search"
ACTIVITIES_PATH = "/api/v1/activities"
ACTIVITIES_BULK_PATH = "/api/v1/activities/bulk"
ACTIVITIES_IMPORT_MAPPING_PATH = "/api/v1/activities/import/mapping"
ACTIVITIES_IMPORT_CHECK_PATH = "/api/v1/activities/import/check"
ACTIVITIES_IMPORT_PATH = "/api/v1/activities/import"
HOLDINGS_QUERY_PATH = "/api/v1/holdings/query"
SNAPSHOTS_PATH = "/api/v1/snapshots"
SNAPSHOTS_IMPORT_PATH = "/api/v1/snapshots/import"
SNAPSHOTS_IMPORT_CHECK_PATH = "/api/v1/snapshots/import/check"
ALLOCATIONS_QUERY_PATH = "/api/v1/allocations/query"
VALUATIONS_CURRENT_QUERY_PATH = "/api/v1/valuations/current/query"
PERFORMANCE_SUMMARY_PATH = "/api/v1/performance/summary"
PERFORMANCE_HISTORY_PATH = "/api/v1/performance/history"
NET_WORTH_PATH = "/api/v1/net-worth"
NET_WORTH_HISTORY_PATH = "/api/v1/net-worth/history"
INCOME_SUMMARY_PATH = "/api/v1/income/summary"
INCOME_SUMMARY_QUERY_PATH = "/api/v1/income/summary/query"
GOALS_PATH = "/api/v1/goals"
LIMITS_PATH = "/api/v1/limits"
HEALTH_STATUS_PATH = "/api/v1/health/status"
PORTFOLIOS_PATH = "/api/v1/portfolios"
TAXONOMIES_PATH = "/api/v1/taxonomies"
TAXONOMY_ASSET_ASSIGNMENTS_PATH = "/api/v1/taxonomies/assignments/asset"
SPENDING_CASH_ACTIVITIES_SEARCH_PATH = "/api/v1/spending/cash-activities/search"
SPENDING_RULES_PATH = "/api/v1/spending/rules"

DEFAULT_TIMEOUT = 30.0
DEFAULT_ACTIVITIES_PAGE_SIZE = 50


def _compact(**kwargs):
    """Drop keys whose value is `None`, so optional filter/body fields are
    omitted from the JSON body instead of sent as `null`."""
    return {key: value for key, value in kwargs.items() if value is not None}


def _normalize_assignment_payload(asset_id, taxonomy_id, assignment):
    """Build one `NewAssetTaxonomyAssignment`-shaped body item for
    `commit_asset_classification_draft` (and the local preview built by
    `prepare_asset_classification`) from a caller-supplied dict. Accepts
    either `categoryId` or `category_id`; `weight` defaults to `10000`
    (100%, matching the server's own `NewAssetTaxonomyAssignment::default()`)
    and `source` defaults to `"manual"` when omitted."""
    assignment = assignment if isinstance(assignment, dict) else {}
    category_id = assignment.get("categoryId", assignment.get("category_id"))
    return _compact(
        id=assignment.get("id"),
        assetId=asset_id,
        taxonomyId=taxonomy_id,
        categoryId=category_id,
        weight=assignment.get("weight", 10000),
        source=assignment.get("source", "manual"),
    )


def _query_string(**kwargs):
    """Build a `?key=value&...` query string, dropping `None` values and
    lower-casing booleans to match axum's query-string bool parsing
    (`true`/`false`, not Python's `True`/`False`). No percent-encoding is
    applied -- every caller here only ever passes UUIDs, ISO dates, or
    other plain-ASCII identifiers, never free text."""
    parts = []
    for key, value in kwargs.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        parts.append(f"{key}={value}")
    return "?" + "&".join(parts) if parts else ""


def _account_scope_filter(*, account_id=None, portfolio_id=None, account_ids=None):
    """Build an `AccountScope`-shaped filter dict from at most one of
    `account_id`/`portfolio_id`/`account_ids` -- mirrors the Rust
    `AccountScope` enum's wire shape (`crates/core/src/portfolios/
    portfolios_model.rs`, `#[serde(tag = "type", rename_all =
    "camelCase")]`): `{"type": "all"}` / `{"type": "account", "accountId":
    ...}` / `{"type": "portfolio", "portfolioId": ...}` / `{"type":
    "accounts", "accountIds": [...]}`. Passing none of the three yields
    the "all non-archived accounts" scope."""
    given = [
        name
        for name, value in (
            ("account_id", account_id),
            ("portfolio_id", portfolio_id),
            ("account_ids", account_ids),
        )
        if value is not None
    ]
    if len(given) > 1:
        raise ValueError(
            "Pass at most one of account_id/portfolio_id/account_ids, got: "
            + ", ".join(given)
        )
    if account_id is not None:
        return {"type": "account", "accountId": account_id}
    if portfolio_id is not None:
        return {"type": "portfolio", "portfolioId": portfolio_id}
    if account_ids is not None:
        return {"type": "accounts", "accountIds": list(account_ids)}
    return {"type": "all"}


def _encode_metadata(fields: dict) -> dict:
    """Return a copy of `fields` with a dict-valued `metadata` key
    JSON-string-encoded in place -- `NewActivity.metadata` /
    `ActivityUpdate.metadata` are `Option<String>` on the wire (write side
    of the read-object/write-string asymmetry, see module docstring above
    `WealthfolioClient`'s activities methods). A `metadata` value that is
    already a string (or absent) is passed through unchanged -- callers who
    already JSON-encoded it themselves are not double-encoded."""
    metadata = fields.get("metadata")
    if isinstance(metadata, dict):
        fields = dict(fields)
        fields["metadata"] = json.dumps(metadata)
    return fields

# Wealthfolio's login endpoint sets this cookie on a successful
# `/api/v1/auth/login` call; every subsequent request must resend it.
SESSION_COOKIE_NAME = "wf_session"
LOGIN_PATH = "/api/v1/auth/login"

# Cloudflare in front of the real server returns a 403 (error 1010) to
# requests that look like a bare script -- a browser-like User-Agent plus
# Origin/Referer headers matching the site avoid that block. Confirmed live.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class _RestTransport:
    """Minimal REST transport: session-cookie login, cookie replay on every
    request, and one transparent re-login-and-retry on a 401 (the server's
    session TTL is 3600s, so a long-lived client will eventually see one)."""

    def __init__(self, base_url, password, *, timeout=DEFAULT_TIMEOUT):
        import requests

        self._base_url = base_url.rstrip("/")
        self._password = password
        self._timeout = timeout
        self._requests = requests
        self._http = requests.Session()
        self._session_cookie = None

    def _browser_headers(self):
        return {
            "User-Agent": _BROWSER_USER_AGENT,
            "Origin": self._base_url,
            "Referer": self._base_url + "/",
        }

    def _send_raw(self, method, url, *, json_body=None, extra_headers=None):
        headers = self._browser_headers()
        if extra_headers:
            headers.update(extra_headers)
        cookies = {}
        if self._session_cookie:
            cookies[SESSION_COOKIE_NAME] = self._session_cookie
        try:
            return self._http.request(
                method, url, json=json_body, headers=headers, cookies=cookies,
                timeout=self._timeout,
            )
        except self._requests.RequestException as exc:
            raise WealthfolioAPIError(f"{method} {url} failed: {exc}") from exc

    def _login(self):
        url = self._base_url + LOGIN_PATH
        response = self._send_raw(
            "POST", url,
            json_body={"password": self._password},
            extra_headers={"Content-Type": "application/json"},
        )

        cookie = response.cookies.get(SESSION_COOKIE_NAME)
        if cookie:
            self._session_cookie = cookie

        if not (200 <= response.status_code < 300):
            raise WealthfolioAPIError(
                f"Login to {url} failed with HTTP {response.status_code}",
                status_code=response.status_code,
                body=response.text,
            )
        if not self._session_cookie:
            raise WealthfolioAPIError(
                f"Login to {url} succeeded (HTTP {response.status_code}) but no "
                f"'{SESSION_COOKIE_NAME}' cookie was returned",
                status_code=response.status_code,
                body=response.text,
            )
        return self._session_cookie

    def request(self, method, path, *, json_body=None):
        """Send one authenticated request, logging in first if no session
        cookie is held yet, and transparently re-logging-in and retrying
        exactly once if the server responds 401 (session expired/invalid)."""
        if not self._session_cookie:
            self._login()

        url = self._base_url + path
        response = self._send_raw(method, url, json_body=json_body)

        if response.status_code == 401:
            self._session_cookie = None
            self._login()
            response = self._send_raw(method, url, json_body=json_body)

        if not (200 <= response.status_code < 300):
            raise WealthfolioAPIError(
                f"{method} {path} failed with HTTP {response.status_code}",
                status_code=response.status_code,
                body=response.text,
            )
        return response

    def close(self):
        self._http.close()


class WealthfolioClient:
    """Thin owner of a `_RestTransport` plus typed domain methods.

    Usage:
        with WealthfolioClient.from_env() as client:
            ...
    """

    def __init__(self, config: WealthfolioRestConfig = None, *, timeout: float = DEFAULT_TIMEOUT):
        self._config = config or load_rest_config()
        self._transport = _RestTransport(
            self._config.base_url, self._config.password, timeout=timeout
        )

    @classmethod
    def from_env(cls, *, timeout=DEFAULT_TIMEOUT, base_url=None, password=None):
        """Build a client by loading the base URL/password from explicit
        arguments and/or the process environment (see
        `wealthfolio.config.load_rest_config`). Does not read `.env`
        files; call `wealthfolio.config.load_dotenv()` first if you want
        one merged into the process environment."""
        return cls(load_rest_config(base_url=base_url, password=password), timeout=timeout)

    def close(self):
        self._transport.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ---- Accounts ------------------------------------------------------
    # Endpoints confirmed against the live OpenAPI schema
    # (`GET /api/v1/openapi.json`) : these four are the
    # *only* account operations the server exposes.

    def get_accounts(self) -> AccountsResult:
        """`GET /api/v1/accounts` -- list every account. The server returns
        a bare JSON array; `AccountsResult` is a client-side wrapper only
        (see `models.py`)."""
        response = self._transport.request("GET", ACCOUNTS_PATH)
        return AccountsResult.from_dict(response.json())

    def create_account(self, **fields) -> Account:
        """`POST /api/v1/accounts` -- create an account. `fields` are sent
        verbatim as the JSON body and must use the API's own camelCase
        names (matching the `NewAccount` schema, e.g. `name`, `accountType`,
        `currency`, `isDefault`, `isActive`), not this client's snake_case
        `Account` field names -- there is no translation layer."""
        response = self._transport.request("POST", ACCOUNTS_PATH, json_body=fields)
        return Account.from_dict(response.json())

    def update_account(self, account_id, **fields) -> Account:
        """`PUT /api/v1/accounts/{id}` -- update an account. `fields` follow
        the `AccountUpdate` schema's camelCase names, same caveat as
        `create_account`."""
        response = self._transport.request(
            "PUT", f"{ACCOUNTS_PATH}/{account_id}", json_body=fields,
        )
        return Account.from_dict(response.json())

    def delete_account(self, account_id) -> None:
        """`DELETE /api/v1/accounts/{id}` -- delete an account. The server
        responds `204 No Content`, so there is no body to parse."""
        self._transport.request("DELETE", f"{ACCOUNTS_PATH}/{account_id}")
        return None

    # ---- Activities -----------------------------------------------------
    # Endpoints/DTOs confirmed against
    # `apps/server/src/api/activities.rs` and
    # `crates/core/src/activities/activities_model.rs` on
    # `github.com/wealthfolio/wealthfolio@main`.
    #
    # Two real API asymmetries apply to every method below (see also the
    # docstrings on `ActivityDetails`/`Activity` in `models.py`):
    #   1. `comment` (search results) vs. `notes` (create/update/delete
    #      results) name the *same* semantic field differently on the two
    #      response DTOs -- not a bug, not unified here.
    #   2. `metadata` is a JSON *string* on write, a JSON *object* on read.
    #      `create_activity`/`update_activity`/`save_activities` all accept
    #      a plain dict for `metadata` and JSON-encode it before sending
    #      (see `_encode_metadata`); the parsed `Activity`/`ActivityDetails`
    #      returned already has `metadata` as a dict, no `json.loads` needed.

    def search_activities(
        self,
        page=1,
        page_size=DEFAULT_ACTIVITIES_PAGE_SIZE,
        account_id=None,
        activity_type=None,
        asset_id_keyword=None,
        date_from=None,
        date_to=None,
        needs_review=None,
        instrument_type=None,
        activity_id=None,
        sort=None,
    ) -> ActivitiesResult:
        """`POST /api/v1/activities/search` -- paginated activity search
        returning the enriched `ActivityDetails` shape (`comment`, joined
        account/asset display fields).

        `account_id`, `activity_type`, `instrument_type`, and `activity_id`
        each accept either a single string or a list of strings, forwarded
        as-is to `accountIdFilter`/`activityTypeFilter`/
        `instrumentTypeFilter`/`activityIdFilter` -- the server accepts
        both shapes. There is no `symbol` filter on this endpoint (unlike
        `wealthfolio_mcp.client.WealthfolioClient.search_activities`) --
        use `asset_id_keyword` (-> `assetIdKeyword`) instead.

        `page` here is 1-indexed (page 1 = first page), matching every
        other paginated method/CLI flag in this client/repo. The wire
        protocol itself is 0-indexed, so `page - 1` is what's actually
        sent as `"page"` in the request body -- confirmed empirically
        against the real server: sending the 1-indexed
        value directly causes every page to silently skip its own
        `page_size` worth of rows (page 1 returns what should have been
        page 2's rows, etc.), which on a small/filtered result set (e.g.
        with `date_from`/`date_to` set) manifests as an entirely empty
        `activities` array even though `total_row_count` is correct and
        well under `page_size` -- this, not a server-side defect, was the
        root cause of the pagination/date-filter bug previously suspected
        here. Do not remove the `- 1` below without re-verifying against
        a live server first."""
        body = _compact(
            page=page - 1,
            pageSize=page_size,
            accountIdFilter=account_id,
            activityTypeFilter=activity_type,
            assetIdKeyword=asset_id_keyword,
            dateFrom=date_from,
            dateTo=date_to,
            needsReviewFilter=needs_review,
            instrumentTypeFilter=instrument_type,
            activityIdFilter=activity_id,
            sort=sort,
        )
        response = self._transport.request("POST", ACTIVITIES_SEARCH_PATH, json_body=body)
        return ActivitiesResult.from_dict(response.json(), page=page, page_size=page_size)

    def iter_activity_pages(
        self,
        page_size=DEFAULT_ACTIVITIES_PAGE_SIZE,
        account_id=None,
        activity_type=None,
        asset_id_keyword=None,
        date_from=None,
        date_to=None,
        needs_review=None,
        instrument_type=None,
        activity_id=None,
        sort=None,
    ):
        """Yield every `ActivitiesResult` page for a `search_activities`
        query, walking pages `1..ceil(total_row_count / page_size)` with
        the given filters forwarded unchanged to each underlying call
        (mirrors `wealthfolio_mcp.client.WealthfolioClient.iter_activity_pages`,
        adapted to this endpoint's `total_row_count`-based paging instead of
        a server-echoed `total_pages`).

        Terminates safely instead of looping forever if a page comes back
        with an empty `activities` list, or once the computed page count is
        reached/falsy -- in both cases pagination stops after the page
        already fetched, without an extra call."""

        def _pages():
            page = 1
            while True:
                result = self.search_activities(
                    page=page,
                    page_size=page_size,
                    account_id=account_id,
                    activity_type=activity_type,
                    asset_id_keyword=asset_id_keyword,
                    date_from=date_from,
                    date_to=date_to,
                    needs_review=needs_review,
                    instrument_type=instrument_type,
                    activity_id=activity_id,
                    sort=sort,
                )
                if not result.activities:
                    return
                yield result
                total_pages = (
                    math.ceil(result.total_row_count / page_size)
                    if result.total_row_count
                    else None
                )
                if not total_pages or page >= total_pages:
                    return
                page += 1

        return _pages()

    def iter_activities(
        self,
        page_size=DEFAULT_ACTIVITIES_PAGE_SIZE,
        account_id=None,
        activity_type=None,
        asset_id_keyword=None,
        date_from=None,
        date_to=None,
        needs_review=None,
        instrument_type=None,
        activity_id=None,
        sort=None,
    ):
        """Yield every `ActivityDetails` across all pages of a
        `search_activities` query (see `iter_activity_pages` for the
        page-walking and safe-termination semantics this builds on)."""
        return (
            activity
            for page in self.iter_activity_pages(
                page_size=page_size,
                account_id=account_id,
                activity_type=activity_type,
                asset_id_keyword=asset_id_keyword,
                date_from=date_from,
                date_to=date_to,
                needs_review=needs_review,
                instrument_type=instrument_type,
                activity_id=activity_id,
                sort=sort,
            )
            for activity in page.activities
        )

    def create_activity(self, **fields) -> Activity:
        """`POST /api/v1/activities` -- create an activity (direct write,
        no draft/commit step -- see class docstring). `fields` are sent
        verbatim as the JSON body using the API's own camelCase `NewActivity`
        names (e.g. `accountId`, `activityType`, `activityDate`, `currency`,
        `notes`/`comment`), same passthrough convention as
        `create_account`. Note the asset reference is NOT a bare `assetId`
        string field -- the live API expects a nested `symbol` object
        (`AssetResolutionInput`, e.g. `symbol={"id": asset_id}` for an
        already-resolved asset); passing a top-level `assetId` string is
        silently ignored by the server and fails validation with "Asset-
        backed activities need either asset_id or symbol". A dict-valued
        `metadata` kwarg is JSON-encoded automatically (see
        `_encode_metadata`) -- callers should pass a plain dict, not a
        pre-encoded string."""
        response = self._transport.request(
            "POST", ACTIVITIES_PATH, json_body=_encode_metadata(fields)
        )
        return Activity.from_dict(response.json())

    def update_activity(self, **fields) -> Activity:
        """`PUT /api/v1/activities` -- update an activity (direct write, no
        draft/commit step). Note this is the **same path** as
        `create_activity`, distinguished only by HTTP method -- the row to
        update is identified by `fields["id"]` in the body, not a URL path
        segment. This is a full-replace endpoint, not a partial patch:
        `fields` must include the complete `ActivityUpdate` shape every
        time -- `accountId`, `activityType`, `activityDate`, `symbol`
        (`{"id": asset_id}`, same caveat as `create_activity`), `quantity`,
        `unitPrice`, `currency`, `fee` -- omitting any of these fails with
        HTTP 422 "missing field ...". Same `metadata` dict-to-JSON-string
        auto-encoding as `create_activity`."""
        response = self._transport.request(
            "PUT", ACTIVITIES_PATH, json_body=_encode_metadata(fields)
        )
        return Activity.from_dict(response.json())

    def delete_activity(self, activity_id) -> Activity:
        """`DELETE /api/v1/activities/{id}` -- delete an activity. Unlike
        `delete_account`, this responds with the deleted `Activity` row
        (not `204 No Content`)."""
        response = self._transport.request("DELETE", f"{ACTIVITIES_PATH}/{activity_id}")
        return Activity.from_dict(response.json())

    def save_activities(self, creates=None, updates=None, delete_ids=None) -> ActivityBulkMutationResult:
        """`POST /api/v1/activities/bulk` -- create/update/delete many
        activities in one direct-write call (no draft/commit step; a
        per-item failure is reported in the result's `errors` list rather
        than aborting the whole batch -- see `ActivityBulkMutationResult`).

        `creates`/`updates` are lists of camelCase field dicts (same shape
        as `create_activity`/`update_activity`'s `**fields`); any dict-valued
        `metadata` in each item is JSON-encoded automatically. `delete_ids`
        is a plain list of activity id strings."""
        body = {
            "creates": [_encode_metadata(item) for item in (creates or [])],
            "updates": [_encode_metadata(item) for item in (updates or [])],
            "deleteIds": list(delete_ids or []),
        }
        response = self._transport.request("POST", ACTIVITIES_BULK_PATH, json_body=body)
        return ActivityBulkMutationResult.from_dict(response.json())

    # ---- Holdings ---------------------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/holdings/{mod,dto,handlers}.rs` and
    # `crates/core/src/portfolio/holdings/holdings_model.rs`.
    #
    # The real holdings surface is far larger than one method (allocations,
    # single-holding lookup, lots, manual/CSV snapshot import, and both a
    # single-account `GET /holdings` and a scope-filtered `POST
    # /holdings/query` for the *same* underlying data) -- only the
    # scope-filtered query is implemented here, since it is a strict
    # superset of the simple `GET` (a single-account filter produces the
    # same `Holding[]` the `GET` would).

    def get_holdings(
        self, account_id=None, portfolio_id=None, account_ids=None, include_closed=False
    ) -> HoldingsResult:
        """`POST /api/v1/holdings/query` -- every holding for the given
        scope. Pass at most one of `account_id` (single account),
        `portfolio_id` (a saved portfolio), or `account_ids` (an ad-hoc
        list); passing none of the three scopes to every non-archived
        account (`{"type": "all"}` on the wire -- see
        `_account_scope_filter`). `include_closed=True` also returns
        positions whose quantity has gone to zero (closed positions are
        omitted by default)."""
        filter_body = _account_scope_filter(
            account_id=account_id, portfolio_id=portfolio_id, account_ids=account_ids
        )
        body = {"filter": filter_body, "includeClosed": include_closed}
        response = self._transport.request("POST", HOLDINGS_QUERY_PATH, json_body=body)
        return HoldingsResult.from_dict(
            response.json(),
            account_id=account_id,
            portfolio_id=portfolio_id,
            account_ids=account_ids,
            include_closed=include_closed,
        )

    # ---- Holdings snapshots -------------------------------------------------
    # Endpoints/DTOs confirmed against `apps/server/src/api/holdings/{dto,
    # handlers}.rs` on `github.com/wealthfolio/wealthfolio@main`
    # (2026-09-23) -- see the "Holdings snapshots" section in `models.py`
    # for the fuller endpoint-shape rationale. This is the mechanism for
    # loading historical balance points into a HOLDINGS-tracking-mode
    # account (e.g. a pension plan with no activity ledger): each snapshot
    # is one `{date, positions, cashBalances}` entry; `positions` may be
    # an empty list for a cash-only account/valuation point.

    def get_snapshots(self, account_id, date_from=None, date_to=None) -> SnapshotsResult:
        """`GET /api/v1/snapshots` (`SnapshotsQuery` -> bare
        `SnapshotInfo[]`) -- metadata (not full holdings detail) for every
        snapshot stored for `account_id`, across all sources (CALCULATED,
        MANUAL_ENTRY, CSV_IMPORT, ...), optionally bounded by `date_from`/
        `date_to` (`YYYY-MM-DD`, both inclusive server-side). Use the
        returned `.snapshots[].snapshot_date` values for an idempotency
        check before `import_holdings_csv`."""
        query = _query_string(accountId=account_id, dateFrom=date_from, dateTo=date_to)
        response = self._transport.request("GET", SNAPSHOTS_PATH + query)
        return SnapshotsResult.from_dict(
            response.json(), account_id=account_id, date_from=date_from, date_to=date_to
        )

    def check_holdings_import(self, account_id, snapshots) -> CheckHoldingsImportResult:
        """`POST /api/v1/snapshots/import/check`
        (`CheckHoldingsImportRequest` -> `CheckHoldingsImportResult`) --
        validates a batch of holdings snapshots **without persisting
        anything**. `snapshots` is sent verbatim as the JSON body's
        `snapshots` array: each item is a `HoldingsSnapshotInput`-shaped
        dict with `date` (`YYYY-MM-DD`), `positions` (list of
        `{symbol, quantity, currency, ...}` dicts -- may be `[]` for a
        cash-only valuation point), and `cashBalances` (dict of currency
        code -> decimal string, e.g. `{"EUR": "12345.67"}`). Returns
        `.existing_dates` (dates that already have a stored snapshot --
        informational only: re-importing one overwrites it rather than
        erroring), `.symbols` (per-symbol resolution status), and
        `.valid_snapshot_dates`/`.invalid_snapshot_dates`/
        `.validation_errors`. Pass the same `snapshots` list straight into
        `import_holdings_csv` once satisfied."""
        body = {"accountId": account_id, "snapshots": list(snapshots)}
        response = self._transport.request("POST", SNAPSHOTS_IMPORT_CHECK_PATH, json_body=body)
        return CheckHoldingsImportResult.from_dict(response.json())

    def import_holdings_csv(self, account_id, snapshots) -> ImportHoldingsCsvResult:
        """`POST /api/v1/snapshots/import` (`ImportHoldingsCsvRequest` ->
        `ImportHoldingsCsvResult`) -- actually persists a batch of holdings
        snapshots (same `snapshots` item shape as `check_holdings_import`).
        Each snapshot is imported independently server-side: a per-date
        failure is reflected in `.snapshots_failed`/`.errors`, not a
        whole-request 4xx. Importing a date that already has a stored
        snapshot overwrites it (see `check_holdings_import`'s
        `.existing_dates` to detect this upfront)."""
        body = {"accountId": account_id, "snapshots": list(snapshots)}
        response = self._transport.request("POST", SNAPSHOTS_IMPORT_PATH, json_body=body)
        return ImportHoldingsCsvResult.from_dict(response.json())

    def delete_snapshot(self, account_id, date, snapshot_id=None) -> None:
        """`DELETE /api/v1/snapshots` (`DeleteSnapshotQuery`) -- deletes
        one snapshot, resolved by `snapshot_id` if given, else by
        `account_id` + `date` (`YYYY-MM-DD`). The server responds `204 No
        Content`, so there is no body to parse. Raises
        `WealthfolioAPIError` if no matching snapshot exists, or if the
        account's tracking mode/snapshot source doesn't allow ad-hoc
        deletion here (e.g. a `CALCULATED` snapshot on a Transactions-mode
        account -- update/delete the underlying activity instead)."""
        query = _query_string(accountId=account_id, date=date, snapshotId=snapshot_id)
        self._transport.request("DELETE", SNAPSHOTS_PATH + query)
        return None

    # ---- Performance --------------------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/performance.rs` and
    # `crates/core/src/portfolio/performance/performance_model.rs`.
    #
    # The request body (`PerfBody` in Rust) requires `itemType`/`itemId` on
    # every call -- `itemId` has no `Option<...>` wrapper server-side, so
    # it must always be present in the JSON body even when unused (see
    # below). The server branches on the body, not the endpoint, to decide
    # *how* to resolve performance:
    #   1. `item_type == "account"` AND a `filter` is present in the body
    #      -> resolves via the multi-account/portfolio/all scope in
    #      `filter`, ignoring `item_id` entirely.
    #   2. Otherwise -> looks up the single item named by `item_id`
    #      (`item_type` distinguishes "account" from other item kinds the
    #      server supports, e.g. a symbol or holding).
    # Passing one of `account_id`/`portfolio_id`/`account_ids` selects
    # path 1 above (`item_type` must stay `"account"`, the default); pass
    # `item_id` alone (with any `item_type`) for path 2.

    def _performance_body(
        self,
        item_type,
        item_id,
        account_id,
        portfolio_id,
        account_ids,
        start_date,
        end_date,
        tracking_mode,
        profile,
    ):
        body = {"itemType": item_type, "itemId": item_id or ""}
        body.update(
            _compact(
                startDate=start_date,
                endDate=end_date,
                trackingMode=tracking_mode,
                profile=profile,
            )
        )
        scope_given = any(v is not None for v in (account_id, portfolio_id, account_ids))
        if item_type == "account" and scope_given:
            body["filter"] = _account_scope_filter(
                account_id=account_id, portfolio_id=portfolio_id, account_ids=account_ids
            )
        return body

    def get_performance_summary(
        self,
        item_id=None,
        item_type="account",
        account_id=None,
        portfolio_id=None,
        account_ids=None,
        start_date=None,
        end_date=None,
        tracking_mode=None,
        profile=None,
    ) -> PerformanceResult:
        """`POST /api/v1/performance/summary` -- headline performance
        metrics (returns/attribution/risk) for one item or one account
        scope over `start_date`..`end_date` (both optional -- an omitted
        bound means "since inception"/"through today"). See the class
        section comment above for the `item_id` vs. `account_id`/
        `portfolio_id`/`account_ids` branching this forwards to the
        server unchanged. `profile` (server default `"full"`) also
        accepts `"summary"`/`"dashboard"` for a cheaper partial
        calculation; `tracking_mode` accepts `"HOLDINGS"`/`"TRANSACTIONS"`
        and only applies to the single-item path."""
        body = self._performance_body(
            item_type, item_id, account_id, portfolio_id, account_ids,
            start_date, end_date, tracking_mode, profile,
        )
        response = self._transport.request("POST", PERFORMANCE_SUMMARY_PATH, json_body=body)
        return PerformanceResult.from_dict(response.json())

    def get_performance_history(
        self,
        item_id=None,
        item_type="account",
        account_id=None,
        portfolio_id=None,
        account_ids=None,
        start_date=None,
        end_date=None,
        tracking_mode=None,
    ) -> PerformanceResult:
        """`POST /api/v1/performance/history` -- same `PerformanceResult`
        shape and same item/scope selection as `get_performance_summary`
        (no `profile` parameter here -- history always computes the full
        series), but with `series` populated (one point per day in the
        requested range) instead of being the summary-only empty list a
        summary call typically leaves it as."""
        body = self._performance_body(
            item_type, item_id, account_id, portfolio_id, account_ids,
            start_date, end_date, tracking_mode, None,
        )
        response = self._transport.request("POST", PERFORMANCE_HISTORY_PATH, json_body=body)
        return PerformanceResult.from_dict(response.json())

    # ---- Net worth ----------------------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/net_worth.rs` and
    # `crates/core/src/portfolio/net_worth/net_worth_model.rs`.

    def get_net_worth(self, date=None) -> NetWorthResult:
        """`GET /api/v1/net-worth` -- a balance-sheet snapshot (assets,
        liabilities, net worth) as of `date` (`YYYY-MM-DD`, server default
        today in the user's configured timezone if omitted)."""
        response = self._transport.request("GET", NET_WORTH_PATH + _query_string(date=date))
        return NetWorthResult.from_dict(response.json())

    def get_net_worth_history(self, start_date, end_date):
        """`GET /api/v1/net-worth/history` -- daily net worth time series
        between `start_date` and `end_date` (`YYYY-MM-DD`, both required
        by the server -- there is no "since inception" default here,
        unlike `get_net_worth`). Returns a plain `list[NetWorthHistoryPoint]`
        (the response is a bare array with no request-scope worth echoing,
        unlike `get_holdings`'s `HoldingsResult`)."""
        response = self._transport.request(
            "GET", NET_WORTH_HISTORY_PATH + _query_string(startDate=start_date, endDate=end_date)
        )
        return [NetWorthHistoryPoint.from_dict(item) for item in response.json()]

    # ---- Income ---------------------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/performance.rs` (income endpoints are declared
    # in that file server-side, not a separate `income.rs`) and
    # `crates/core/src/portfolio/income/income_model.rs`.

    def get_income_summary(self, account_id=None):
        """`GET /api/v1/income/summary` -- one aggregated `IncomeSummary`
        for `account_id` (if given) or for every active,
        income-eligible account (if omitted), wrapped in a bare
        single-element `list` by the server regardless. Returns a plain
        `list[IncomeSummary]` (see `get_net_worth_history` for why no
        wrapper class is used)."""
        response = self._transport.request(
            "GET", INCOME_SUMMARY_PATH + _query_string(accountId=account_id)
        )
        return [IncomeSummary.from_dict(item) for item in response.json()]

    def get_income_summary_query(self, portfolio_id=None, account_ids=None):
        """`POST /api/v1/income/summary/query` -- same response shape as
        `get_income_summary`, but scoped by a saved `portfolio_id` or an
        ad-hoc `account_ids` list instead of a single `account_id` (there
        is no single-account filter type here since `get_income_summary`
        already covers that case more simply). Passing neither omits the
        body's `filter` key entirely, which the server treats the same as
        `get_income_summary`'s own omitted `account_id` -- every active,
        income-eligible account."""
        body = {}
        if portfolio_id is not None or account_ids is not None:
            body["filter"] = _account_scope_filter(
                portfolio_id=portfolio_id, account_ids=account_ids
            )
        response = self._transport.request("POST", INCOME_SUMMARY_QUERY_PATH, json_body=body)
        return [IncomeSummary.from_dict(item) for item in response.json()]

    # ---- Goals ----------------------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/goals.rs` and
    # `crates/core/src/goals/goals_model.rs`.

    def get_goals(self) -> GoalsResult:
        """`GET /api/v1/goals` -- list every goal. The server returns a
        bare JSON array; `GoalsResult` is a client-side wrapper only (see
        `models.py`). `goals.rs` also registers single-goal CRUD, funding
        rules, goal plans, and retirement/save-up simulation endpoints
        under `/goals/...` -- those endpoints are not implemented here."""
        response = self._transport.request("GET", GOALS_PATH)
        return GoalsResult.from_dict(response.json())

    # ---- Contribution limits ----------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/limits.rs` and
    # `crates/core/src/limits/limits_model.rs`.

    def get_contribution_limits(self) -> ContributionLimitsResult:
        """`GET /api/v1/limits` -- list every contribution limit. The
        server returns a bare JSON array; `ContributionLimitsResult` is a
        client-side wrapper only. Per-limit computed usage
        (`usedAmount`/`remainingAmount`) is not part of this shape --
        fetch it separately via `GET /api/v1/limits/{id}/deposits` (not
        implemented here)."""
        response = self._transport.request("GET", LIMITS_PATH)
        return ContributionLimitsResult.from_dict(response.json())

    # ---- Health -------------------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/health.rs` and
    # `crates/core/src/health/model.rs`.

    def get_health_status(self) -> HealthStatusResult:
        """`GET /api/v1/health/status` -- the cached `HealthStatus` if
        still fresh (`isStale=false`), else a synchronous fresh check.
        `health.rs` also exposes `/health/check` (force-fresh),
        `/health/dismiss`, `/health/restore`, `/health/dismissed`,
        `/health/fix`, and `/health/config` -- none of those are
        implemented here."""
        response = self._transport.request("GET", HEALTH_STATUS_PATH)
        return HealthStatusResult.from_dict(response.json())

    # ---- Portfolios -----------------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/portfolios.rs` (plural) and
    # `crates/core/src/portfolios/portfolios_model.rs`.

    def get_portfolios(self) -> PortfoliosResult:
        """`GET /api/v1/portfolios` -- list every saved portfolio (each
        with its resolved member `accountIds`). The server returns a bare
        JSON array; `PortfoliosResult` is a client-side wrapper only. This
        is the real equivalent of `wealthfolio_mcp`'s `get_portfolios`/
        `PortfoliosResult` -- served by the *plural*
        `apps/server/src/api/portfolios.rs`, not the singular
        `apps/server/src/api/portfolio.rs` (which only exposes
        recalculation-job triggers and an SSE event stream, no data
        read)."""
        response = self._transport.request("GET", PORTFOLIOS_PATH)
        return PortfoliosResult.from_dict(response.json())

    # ---- Asset taxonomies -------------------------------------------------
    # Endpoints/DTOs confirmed against
    # `apps/server/src/api/taxonomies.rs` and
    # `crates/core/src/taxonomies/taxonomy_model.rs`.
    #
    # `taxonomies.rs` has no server-side search-by-name and no per-category
    # depth limit -- `taxonomy_name`/`category_depth` (both present on
    # `wealthfolio_mcp.client.WealthfolioClient.list_asset_taxonomies`) are
    # accepted here for interface parity only: `taxonomy_name` filters the
    # already-fetched list client-side (case-insensitive exact match on
    # `name`); `category_depth` has no effect at all (there is no
    # depth-limited variant of `GET /taxonomies/{id}` to call), and is
    # accepted purely so existing MCP-shaped call sites don't need to drop
    # the keyword.

    def list_asset_taxonomies(
        self, taxonomy_id=None, taxonomy_name=None, include_categories=None, category_depth=None
    ) -> TaxonomiesResult:
        """List taxonomies. With `taxonomy_id`, calls
        `GET /api/v1/taxonomies/{id}` (`Option<TaxonomyWithCategories>` --
        one taxonomy with its full category list, or a bare `null` if not
        found) and returns a single-item result. Without it, calls
        `GET /api/v1/taxonomies` (a bare `Vec<Taxonomy>`, no categories)
        and, only if `include_categories` is truthy, fetches each
        taxonomy's categories with one follow-up
        `GET /api/v1/taxonomies/{id}` call per taxonomy -- there is no
        bulk "all taxonomies with categories" endpoint. Those per-taxonomy
        fetches land in `TaxonomiesResult.details`; `.taxonomies` always
        holds the plain (category-less) list."""
        if taxonomy_id:
            response = self._transport.request("GET", f"{TAXONOMIES_PATH}/{taxonomy_id}")
            data = response.json()
            if not isinstance(data, dict):
                return TaxonomiesResult(taxonomies=[], details=[], count=0, raw=data)
            detail = TaxonomyWithCategories.from_dict(data)
            taxonomies = [detail.taxonomy] if detail.taxonomy is not None else []
            return TaxonomiesResult(
                taxonomies=taxonomies, details=[detail], count=len(taxonomies), raw=data
            )

        response = self._transport.request("GET", TAXONOMIES_PATH)
        data = response.json()
        taxonomies = [Taxonomy.from_dict(item) for item in data] if isinstance(data, list) else []
        if taxonomy_name:
            needle = taxonomy_name.strip().lower()
            taxonomies = [t for t in taxonomies if (t.name or "").strip().lower() == needle]
        details = []
        if include_categories:
            for taxonomy in taxonomies:
                if not taxonomy.id:
                    continue
                sub_response = self._transport.request("GET", f"{TAXONOMIES_PATH}/{taxonomy.id}")
                sub_data = sub_response.json()
                if isinstance(sub_data, dict):
                    details.append(TaxonomyWithCategories.from_dict(sub_data))
        return TaxonomiesResult(taxonomies=taxonomies, details=details, count=len(taxonomies), raw=data)

    def get_asset_taxonomy_assignments(self, asset_id, taxonomy_id=None) -> TaxonomyAssignmentsResult:
        """`GET /api/v1/taxonomies/assignments/asset/{assetId}` -- every
        taxonomy assignment for one asset, as a bare
        `Vec<AssetTaxonomyAssignment>`.

        Divergence from `wealthfolio_mcp.client.WealthfolioClient.get_asset_taxonomy_assignments`:
        that tool accepts a fuzzy `asset_query` (symbol/name/ISIN),
        resolved server-side by an MCP-only lookup with disambiguation.
        This REST endpoint requires the literal `assetId` path parameter
        with no fuzzy resolution available, so this method takes
        `asset_id` instead -- resolve a query to a real id yourself first
        (e.g. via `search_activities`) if you only have a symbol.

        `taxonomy_id`, if given, filters the results client-side -- the
        endpoint itself has no query-parameter filter."""
        response = self._transport.request("GET", f"{TAXONOMY_ASSET_ASSIGNMENTS_PATH}/{asset_id}")
        data = response.json()
        assignments = (
            [AssetTaxonomyAssignment.from_dict(item) for item in data] if isinstance(data, list) else []
        )
        if taxonomy_id:
            assignments = [a for a in assignments if a.taxonomy_id == taxonomy_id]
        return TaxonomyAssignmentsResult(
            asset_id=asset_id, assignments=assignments, count=len(assignments), raw=data
        )

    def prepare_asset_classification(
        self, asset_id, taxonomy_id, assignments
    ) -> PrepareAssetClassificationResult:
        """Non-mutating preview for a classification change.

        **Deviates from `wealthfolio_mcp`'s draft/commit split**:
        `taxonomies.rs` has no server-side draft endpoint at all -- its
        `assign_asset_to_category`/`replace_asset_taxonomy_assignments`
        handlers mutate immediately, there is nothing to "prepare" on the
        server. To keep the same two-method shape for interface parity,
        this method makes exactly one **read** call
        (`get_asset_taxonomy_assignments`) to show the asset's current
        assignments for `taxonomy_id`, and echoes `assignments` back as a
        local, not-yet-persisted `proposed_assignments` preview -- nothing
        is sent to a write endpoint here. Call
        `commit_asset_classification_draft` with the same `asset_id`/
        `taxonomy_id`/`assignments` to actually persist them; there is no
        way to "commit" only what this call already returned, since it
        never sent anything to the server to commit."""
        current = self.get_asset_taxonomy_assignments(asset_id, taxonomy_id=taxonomy_id).assignments
        proposed = [
            AssignmentPreview.from_dict(_normalize_assignment_payload(asset_id, taxonomy_id, item))
            for item in (assignments or [])
        ]
        return PrepareAssetClassificationResult(
            asset_id=asset_id,
            taxonomy_id=taxonomy_id,
            current_assignments=current,
            proposed_assignments=proposed,
        )

    def commit_asset_classification_draft(self, asset_id, taxonomy_id, assignments):
        """`PUT /api/v1/taxonomies/assignments/asset/{assetId}/taxonomy/{taxonomyId}`
        (`replace_asset_taxonomy_assignments`) -- **replaces** every
        assignment `asset_id` has for `taxonomy_id` with `assignments`
        (each item needs at least `category_id`; `weight` defaults to
        `10000` (100%) and `source` to `"manual"` if omitted -- see
        `_normalize_assignment_payload`). This is a direct, immediate
        mutation -- see `prepare_asset_classification`'s docstring for why
        there is no separate server-side commit step to call afterwards.
        Returns the server's echoed `list[AssetTaxonomyAssignment]` for
        this (asset, taxonomy) pair after the replace."""
        body = [_normalize_assignment_payload(asset_id, taxonomy_id, item) for item in (assignments or [])]
        response = self._transport.request(
            "PUT",
            f"{TAXONOMY_ASSET_ASSIGNMENTS_PATH}/{asset_id}/taxonomy/{taxonomy_id}",
            json_body=body,
        )
        data = response.json()
        return [AssetTaxonomyAssignment.from_dict(item) for item in data] if isinstance(data, list) else []

    # ---- Transaction categorization -----------------------------------
    # Endpoints/DTOs confirmed against
    # `apps/server/src/api/spending.rs` and
    # `crates/spending/src/{cash_activities,categorization_rules}/model.rs`.
    #
    # `wealthfolio_mcp.client.WealthfolioClient.propose_transaction_categories`
    # has **no REST equivalent** and is deliberately NOT implemented here.
    # It is an MCP-only tool that calls an LLM to suggest categories for a
    # batch of activities; `spending.rs` has no "propose"/"suggest"
    # endpoint of any kind -- the closest thing, `POST /spending/rules/
    # rerun`, deterministically reapplies existing *saved* rules, it does
    # not generate new suggestions. Fabricating a mapping onto that
    # endpoint (or onto the plain search below) would misrepresent what
    # either one actually does.

    def list_categorization_context(
        self, account_ids=None, start_date=None, end_date=None, status=None, limit=None, offset=None
    ) -> CashActivitySearchResult:
        """Adapted from `wealthfolio_mcp`'s `list_categorization_context`
        onto `POST /api/v1/spending/cash-activities/search`
        (`CashActivitySearchRequest`/`CashActivitySearchResponse`) -- the
        closest real read path for "activities that may need
        categorization".

        Two divergences from the MCP tool's kwargs: `activity_ids` has no
        server-side filter on this endpoint at all (filter the returned
        `.items` by `.activity.id` client-side if you need it); `status`
        defaults to `"uncategorized"` here (matching the MCP tool's
        implied intent) instead of the server's own default of `"all"` --
        pass `status="all"` explicitly to see every activity regardless of
        categorization state. Accepts the same `CashActivityStatusFilter`
        values the server does: `"all"`, `"needs_review"`,
        `"uncategorized"`, `"categorized"`."""
        body = _compact(
            accountIds=account_ids,
            startDate=start_date,
            endDate=end_date,
            status=status if status is not None else "uncategorized",
            offset=offset,
            limit=limit,
        )
        response = self._transport.request("POST", SPENDING_CASH_ACTIVITIES_SEARCH_PATH, json_body=body)
        return CashActivitySearchResult.from_dict(response.json())

    def create_categorization_rule(
        self,
        name,
        pattern,
        taxonomy_id=None,
        category_id=None,
        match_type=None,
        account_id=None,
        activity_type=None,
        amount_op=None,
        amount_value=None,
        amount_value2=None,
        priority=None,
        is_global=None,
    ) -> CategorizationRule:
        """`POST /api/v1/spending/rules` (`NewCategorizationRule`).

        Divergence from
        `wealthfolio_mcp.client.WealthfolioClient.create_categorization_rule`:
        that tool takes `category_key` and resolves it to a real
        `taxonomyId`/`categoryId` pair server-side (an MCP-only
        convenience lookup). The real `NewCategorizationRule` schema has
        no key-based lookup of its own, so this method takes `category_id`
        directly instead -- resolve a key to an id yourself first (e.g.
        via `list_asset_taxonomies(taxonomy_id=..., include_categories=True)`
        and match on `Category.key`). `name` is also required here (it is
        optional with a caller-friendly default on the MCP tool, but
        `NewCategorizationRule.name` has no server-side default -- omitting
        it raises `WealthfolioAPIError` from a 4xx response)."""
        body = _compact(
            name=name,
            pattern=pattern,
            matchType=match_type,
            taxonomyId=taxonomy_id,
            categoryId=category_id,
            activityType=activity_type,
            amountOp=amount_op,
            amountValue=amount_value,
            amountValue2=amount_value2,
            priority=priority,
            isGlobal=is_global,
            accountId=account_id,
        )
        response = self._transport.request("POST", SPENDING_RULES_PATH, json_body=body)
        return CategorizationRule.from_dict(response.json())

    # ---- Cash balances --------------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/holdings/{mod,dto,handlers}.rs` and
    # `crates/core/src/portfolio/valuation/valuation_model.rs`.
    #
    # There is no dedicated "cash balance" endpoint on the server --
    # `get_cash_balances` is adapted onto `POST /api/v1/valuations/
    # current/query` (the live per-scope valuation endpoint used by
    # `get_holding`/health-center-style "current state" views), the
    # closest real read path. `CurrentValuationSummary.cashCurrencySplit`
    # is the actual per-currency cash breakdown this method exists to
    # expose; the response also carries investment/total value fields
    # (kept on `CashBalancesResult`, not trimmed, since they come from the
    # same call for free).

    def get_cash_balances(
        self, account_id=None, portfolio_id=None, account_ids=None, include_accounts=False
    ) -> CashBalancesResult:
        """`POST /api/v1/valuations/current/query` (`CurrentValuationBody`
        -> `CurrentValuationResponse`). Pass at most one of `account_id`,
        `portfolio_id`, or `account_ids`; passing none scopes to every
        non-archived account. `include_accounts=True` additionally
        populates `.accounts` with one `CurrentAccountValuation` per
        resolved account (omitted by default, matching the server's own
        default)."""
        body = {
            "filter": _account_scope_filter(
                account_id=account_id, portfolio_id=portfolio_id, account_ids=account_ids
            ),
            "includeAccounts": bool(include_accounts),
        }
        response = self._transport.request("POST", VALUATIONS_CURRENT_QUERY_PATH, json_body=body)
        return CashBalancesResult.from_dict(response.json())

    # ---- Asset allocation -------------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/holdings/{mod,dto,handlers}.rs` and
    # `crates/core/src/portfolio/allocation/allocation_model.rs`.
    #
    # This is a real server-computed breakdown, not a client-side
    # aggregation over `get_holdings()` -- the server maintains its own
    # `allocation_service` that rolls holdings up by taxonomy category.

    def get_asset_allocation(
        self, account_id=None, portfolio_id=None, account_ids=None, include_closed=False
    ) -> AssetAllocationResult:
        """`POST /api/v1/allocations/query` (`AllocationFilterBody`'s
        sibling `FilterBody` -> `PortfolioAllocations`). Same scope
        convention as `get_holdings`/`get_cash_balances`: pass at most one
        of `account_id`/`portfolio_id`/`account_ids`, or none for every
        non-archived account. `include_closed=True` also counts positions
        whose quantity has gone to zero."""
        body = {
            "filter": _account_scope_filter(
                account_id=account_id, portfolio_id=portfolio_id, account_ids=account_ids
            ),
            "includeClosed": bool(include_closed),
        }
        response = self._transport.request("POST", ALLOCATIONS_QUERY_PATH, json_body=body)
        return AssetAllocationResult.from_dict(response.json())

    # ---- Activity import --------------------------------------------------
    # Endpoint/DTO confirmed against
    # `apps/server/src/api/activities.rs` and
    # `crates/core/src/activities/activities_model.rs`.
    #
    # `get_import_mapping`/`prepare_activity_import`/
    # `commit_activity_import` are real REST equivalents of a genuine
    # two-step server flow -- `check` validates/dedups a batch without
    # persisting (populating `.errors`/`.warnings`/`.duplicateOfId` per
    # row), and the plain `import` endpoint actually persists. This is
    # unlike client-side classification previews; the server itself exposes
    # both steps as distinct routes.
    #
    # `activities.rs` also registers CSV parsing (`/activities/import/
    # parse`), new-asset preview (`/activities/import/assets/preview`),
    # import templates, and existing-duplicate checks -- none of those are
    # implemented here.

    def get_import_mapping(self, account_id, context_kind=None) -> ImportMappingResult:
        """`GET /api/v1/activities/import/mapping` (`MappingQuery` ->
        `ImportMappingData`). `context_kind` defaults server-side to
        `"CSV_ACTIVITY"` (`import_type::ACTIVITY`) when omitted -- the
        other real value is `"CSV_HOLDINGS"` (`import_type::HOLDINGS`),
        for the separate holdings-snapshot import flow under
        `/snapshots/import*`, not covered by this client."""
        query = _query_string(accountId=account_id, contextKind=context_kind)
        response = self._transport.request("GET", ACTIVITIES_IMPORT_MAPPING_PATH + query)
        return ImportMappingResult.from_dict(response.json())

    def prepare_activity_import(self, activities) -> PrepareActivityImportResult:
        """`POST /api/v1/activities/import/check` (`ImportCheckBody` ->
        bare `Vec<ActivityImport>`) -- validates and deduplicates a batch
        of `ActivityImport`-shaped row dicts **without persisting
        anything**. `activities` items are sent verbatim as the JSON
        body, same camelCase-passthrough convention as `create_activity`
        -- each row's non-optional wire fields are `date`, `symbol`,
        `activityType`, `currency`, `isDraft`, and `isValid` (there is no
        server-side default for the latter two; omitting either raises
        `WealthfolioAPIError` from a 4xx response). Pass the (possibly
        error/warning-annotated) rows this method returns straight into
        `commit_activity_import` once the caller is satisfied with them."""
        body = {"activities": list(activities)}
        response = self._transport.request("POST", ACTIVITIES_IMPORT_CHECK_PATH, json_body=body)
        return PrepareActivityImportResult.from_dict(response.json())

    def commit_activity_import(self, activities) -> ImportActivitiesResult:
        """`POST /api/v1/activities/import` (`ImportBody` ->
        `ImportActivitiesResult`) -- actually persists a batch of
        `ActivityImport`-shaped row dicts (same shape/required-fields
        caveat as `prepare_activity_import`). Unlike
        `prepare_activity_import`, rows that fail validation here are
        skipped (reflected in `.summary.skipped`/`.summary.success`), not
        rejected as a whole-request 4xx -- check `.summary` and the
        per-row `.activities[].errors` after calling this."""
        body = {"activities": list(activities)}
        response = self._transport.request("POST", ACTIVITIES_IMPORT_PATH, json_body=body)
        return ImportActivitiesResult.from_dict(response.json())

    # ---- Assets -----------------------------------------------------------
    # Endpoints/DTOs confirmed against
    # `apps/server/src/api/assets.rs` and
    # `crates/core/src/assets/assets_model.rs` on
    # `github.com/wealthfolio/wealthfolio@main`.
    #
    # Like accounts -- unlike classification previews or activity import's
    # check/persist split -- asset writes here
    # are direct one-shot mutations: there is no separate draft/preview
    # step for `create_asset`/`update_asset_profile`/`delete_asset`.
    #
    # `assets.rs` also registers pricing-mode toggling (`PUT
    # /assets/pricing-mode/{id}`) and asset-logo CRUD (`/assets/logos`,
    # `/assets/logo/{id}`) -- neither is implemented here.

    def list_assets(self) -> AssetsResult:
        """`GET /api/v1/assets` -- list every asset. The server returns a
        bare JSON array; `AssetsResult` is a client-side wrapper only (see
        `models.py`, same convention as `AccountsResult`)."""
        response = self._transport.request("GET", ASSETS_PATH)
        return AssetsResult.from_dict(response.json())

    def get_asset(self, asset_id) -> AssetProfile:
        """`GET /api/v1/assets/profile?assetId=...` (`AssetQuery` ->
        `AssetProfile`). `AssetProfile` flattens every `Asset` field plus
        two derived valuation fields (`valuationMarketPrice`/
        `valuationMarketCurrency`) at the JSON top level -- see
        `AssetProfile` in `models.py`."""
        query = _query_string(assetId=asset_id)
        response = self._transport.request("GET", ASSETS_PROFILE_PATH + query)
        return AssetProfile.from_dict(response.json())

    def create_asset(self, **fields) -> Asset:
        """`POST /api/v1/assets` -- create an asset. `fields` are sent
        verbatim as the JSON body and must use the API's own camelCase
        names (matching the `NewAsset` schema, e.g. `kind`, `name`,
        `displayCode`, `quoteMode`, `quoteCcy`, `instrumentType`,
        `instrumentSymbol`, `instrumentExchangeMic`, `providerConfig`,
        `notes`, `metadata`), not this client's snake_case `Asset` field
        names -- same convention as `create_account`, no translation
        layer. `kind` and `quoteCcy` have no server-side default;
        omitting either raises `WealthfolioAPIError` from a 4xx
        response."""
        response = self._transport.request("POST", ASSETS_PATH, json_body=fields)
        return Asset.from_dict(response.json())

    def update_asset_profile(self, asset_id, **fields) -> Asset:
        """`PUT /api/v1/assets/profile/{id}` -- update an asset's
        profile. `fields` follow the `UpdateAssetProfile` schema's
        camelCase names, same caveat as `create_asset`.
        **This call is a full replacement, not a per-field patch:**
        despite every field except `notes` being `Option<...>` on the
        wire, omitting a key from `fields` still resets that field to
        null/its default server-side rather than leaving it unchanged
        (confirmed in practice for `name`, `providerConfig`, and
        `quoteCcy`). Callers that want to change only some fields must
        fetch the asset first (`get_asset`) and pass every field back
        explicitly -- see `cmd_wealthfolio_rest_asset_update` in
        `wealthfolio/cli.py` for the reference fetch-then-merge pattern.
        `notes` additionally has no server-side default at all
        (it's a required `String`), so omitting it raises
        `WealthfolioAPIError` from a 4xx response; pass `notes=""`
        explicitly to clear it rather than omitting the key."""
        response = self._transport.request(
            "PUT", f"{ASSETS_PROFILE_PATH}/{asset_id}", json_body=fields,
        )
        return Asset.from_dict(response.json())

    def delete_asset(self, asset_id) -> None:
        """`DELETE /api/v1/assets/{id}` -- delete an asset. The server
        responds `204 No Content`, so there is no body to parse."""
        self._transport.request("DELETE", f"{ASSETS_PATH}/{asset_id}")
        return None
