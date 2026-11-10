#!/usr/bin/env python3
"""Live, read-only smoke check for every non-mutating `WealthfolioClient`
(REST) method, plus an opt-in section that captures the *shape* of the two
non-mutating "prepare" methods' responses (never a `create_*`/`update_*`/
`delete_*`/`commit_*`/`save_activities` call -- see below).

This is an OPT-IN diagnostic script, not a test suite: it is intentionally
named `smoke_check.py` (not `test_*.py`) so `python3 -m unittest discover`
never picks it up and never opens a real network connection as part of the
offline test suite. Run directly by a human against a real remote server,
with `WEALTHFOLIO_PASSWORD`/`WEALTHFOLIO_REST_URL` set in the process
environment (see `wealthfolio.config.load_rest_config` -- this script does
not read `.env` files itself; call `wealthfolio.config.load_dotenv()`
first, or export the variables, if you want one):

    python -m wealthfolio.smoke_check

It calls every read-only method on `WealthfolioClient` once, plus
`prepare_activity_import`/`prepare_asset_classification` (non-mutating by
design -- see their docstrings in `client.py`), and reports pass/fail/skip.
It NEVER calls `create_account`/`update_account`/`delete_account`,
`create_activity`/`update_activity`/`delete_activity`/`save_activities`,
`commit_activity_import`, `create_asset`/`update_asset_profile`/
`delete_asset`, `commit_asset_classification_draft`, or
`create_categorization_rule`.

Because Wealthfolio holds sensitive personal financial data, this script
only ever prints the *shape* of each response (Python type, list length,
dict top-level keys, dataclass field names) via `_describe_shape` -- never
actual account values, balances, holdings amounts, or any other real
financial figure. `_describe_shape` explicitly skips every typed model's
`.raw` field for this reason (it holds the real, unredacted server payload).

Exits 0 in all cases (pass, fail, or skip) since this is a diagnostic aid,
not a CI gate: it skips cleanly with a message if no usable password /
reachable server is configured.
"""

import dataclasses
import sys

from wealthfolio.client import WealthfolioClient
from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError


def _describe_shape(value, depth=0, max_depth=4):
    """A redacted structural summary of a response: types, list lengths,
    dict top-level keys, and dataclass field names only -- never the actual
    values it contains. Every typed model's `.raw` field (the verbatim
    server payload) is deliberately never descended into."""
    if depth > max_depth:
        return "..."
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {
            f.name: _describe_shape(getattr(value, f.name), depth + 1, max_depth)
            for f in dataclasses.fields(value)
            if f.name != "raw"
        }
        return {"<{}>".format(type(value).__name__): fields}
    if isinstance(value, dict):
        return {key: _describe_shape(v, depth + 1, max_depth) for key, v in value.items()}
    if isinstance(value, list):
        if not value:
            return "list[len=0]"
        return f"list[len={len(value)}] of {_describe_shape(value[0], depth + 1, max_depth)}"
    return type(value).__name__


class _CheckResult:
    def __init__(self, name, status, detail=""):
        self.name = name
        self.status = status  # "pass" | "fail" | "skip"
        self.detail = detail


def _run_check(results, name, fn):
    """Call `fn()`, record a pass/fail `_CheckResult` (shape-only on
    success), and return the raw response so callers can use it for
    discovery (e.g. picking an account/asset/taxonomy id) without
    re-printing it."""
    try:
        value = fn()
    except WealthfolioError as exc:
        results.append(_CheckResult(name, "fail", f"{type(exc).__name__}: {exc}"))
        return None
    except Exception as exc:  # defensive: never let one bad call abort the run
        results.append(_CheckResult(name, "fail", f"unexpected {type(exc).__name__}: {exc}"))
        return None
    results.append(_CheckResult(name, "pass", str(_describe_shape(value))))
    return value


def _skip(results, name, reason):
    results.append(_CheckResult(name, "skip", reason))


def _discover_asset(client):
    """Best-effort, silent discovery of a real asset (id + ticker symbol)
    for the get_asset/get_asset_taxonomy_assignments/
    prepare_asset_classification/prepare_activity_import checks below,
    from `list_assets()`. Returns an `(asset_id, symbol)` tuple (either
    element may be `None`) -- this is plumbing for the checks below, not
    itself a reported check."""
    try:
        assets = client.list_assets().assets or []
    except WealthfolioError:
        return None, None
    if not assets:
        return None, None
    asset = assets[0]
    return asset.id, (asset.instrument_symbol or asset.display_code)


def _discover_taxonomy_id(client):
    """Best-effort, silent discovery of a real `taxonomy_id` for the
    classification-preview shape check below, from `list_asset_taxonomies()`."""
    try:
        taxonomies = client.list_asset_taxonomies().taxonomies or []
    except WealthfolioError:
        return None
    return taxonomies[0].id if taxonomies else None


def _print_summary(results):
    print()
    print("=== Wealthfolio REST live read-only smoke check ===")
    name_width = max((len(r.name) for r in results), default=20)
    for result in results:
        marker = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[result.status]
        print(f"{result.name.ljust(name_width)}  {marker}  {result.detail}")
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skip")
    print("-" * (name_width + 20))
    print(f"Total: {len(results)}   pass={passed} fail={failed} skip={skipped}")


def run():
    try:
        client = WealthfolioClient.from_env()
    except WealthfolioConfigError as exc:
        print(f"SKIPPED: no usable Wealthfolio REST config found ({exc})")
        return 0

    results = []
    try:
        # Connectivity check + account discovery in one call. Any
        # WealthfolioError here (unreachable server, bad password, etc.)
        # means we skip the rest of the run cleanly rather than cascading
        # failures.
        accounts = _run_check(results, "get_accounts", client.get_accounts)
        if accounts is None:
            print("SKIPPED: could not reach the Wealthfolio REST server "
                  "(see the get_accounts failure above for detail).")
            _print_summary(results)
            return 0

        account_list = accounts.accounts or []
        account_ids = [a.id for a in account_list if a.id]
        account_id = account_ids[0] if account_ids else None

        if account_id is not None:
            _run_check(results, "get_holdings", lambda: client.get_holdings(account_id=account_id))
            _run_check(
                results, "get_cash_balances", lambda: client.get_cash_balances(account_id=account_id)
            )
            _run_check(
                results,
                "get_performance_summary",
                lambda: client.get_performance_summary(account_id=account_id),
            )
            _run_check(
                results,
                "get_performance_history",
                lambda: client.get_performance_history(account_id=account_id),
            )
            _run_check(
                results, "get_import_mapping", lambda: client.get_import_mapping(account_id)
            )
            _run_check(
                results, "get_income_summary", lambda: client.get_income_summary(account_id=account_id)
            )
        else:
            for name in (
                "get_holdings",
                "get_cash_balances",
                "get_performance_summary",
                "get_performance_history",
                "get_import_mapping",
                "get_income_summary",
            ):
                _skip(results, name, "skipped: no account_id available")

        _run_check(results, "get_net_worth", client.get_net_worth)
        _run_check(
            results,
            "get_net_worth_history",
            lambda: client.get_net_worth_history("2024-01-01", "2024-01-31"),
        )
        _run_check(results, "get_asset_allocation", client.get_asset_allocation)
        _run_check(
            results, "search_activities", lambda: client.search_activities(page=1, page_size=5)
        )
        _run_check(results, "get_income_summary_query", client.get_income_summary_query)
        _run_check(results, "get_goals", client.get_goals)
        _run_check(results, "get_contribution_limits", client.get_contribution_limits)
        _run_check(results, "get_portfolios", client.get_portfolios)
        _run_check(results, "get_health_status", client.get_health_status)
        _run_check(results, "list_asset_taxonomies", client.list_asset_taxonomies)
        _run_check(results, "list_categorization_context", client.list_categorization_context)
        _run_check(results, "list_assets", client.list_assets)

        asset_id, asset_symbol = _discover_asset(client)
        if asset_id is not None:
            _run_check(results, "get_asset", lambda: client.get_asset(asset_id))
            _run_check(
                results,
                "get_asset_taxonomy_assignments",
                lambda: client.get_asset_taxonomy_assignments(asset_id),
            )
        else:
            for name in ("get_asset", "get_asset_taxonomy_assignments"):
                _skip(results, name, "skipped: no asset id could be discovered from list_assets")

        # ---- Non-mutating "prepare" shape checks ---------------------------
        # These call the prepare_*/get_*mapping-adjacent methods that, by
        # design, never persist anything -- NEVER a create_*/update_*/
        # delete_*/commit_*/save_activities call. The quantity/price/date
        # values below are synthetic placeholders (not real transactions);
        # only the account_id/asset_id are real, discovered the same
        # read-only way as the checks above.
        taxonomy_id = _discover_taxonomy_id(client)

        if account_id is not None and asset_symbol is not None:
            _run_check(
                results,
                "prepare_activity_import (check only, never persisted)",
                lambda: client.prepare_activity_import(
                    [
                        {
                            "date": "2024-01-01",
                            "accountId": account_id,
                            "symbol": asset_symbol,
                            "activityType": "BUY",
                            "quantity": 1,
                            "unitPrice": 1,
                            "currency": "USD",
                            "isDraft": True,
                            "isValid": True,
                        }
                    ]
                ),
            )
        else:
            _skip(
                results,
                "prepare_activity_import (check only, never persisted)",
                "skipped: no account_id/asset_symbol available",
            )

        if asset_id is not None and taxonomy_id is not None:
            _run_check(
                results,
                "prepare_asset_classification (preview only, never persisted)",
                lambda: client.prepare_asset_classification(asset_id, taxonomy_id, []),
            )
        else:
            _skip(
                results,
                "prepare_asset_classification (preview only, never persisted)",
                "skipped: no asset_id/taxonomy_id available",
            )
    finally:
        client.close()

    _print_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(run())
