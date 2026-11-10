#!/usr/bin/env python3
"""Offline tests for the generic `wealthfolio` CLI (no network calls --
WealthfolioClient.from_env is mocked). Covers every subcommand shipped by
this package's own standalone parser -- a host application's own
repo-specific subcommands and cache-invalidation write-hook integration
belong in that application's own test suite instead."""

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from wealthfolio import cli
from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError


class _FakeResult:
    def __init__(self, raw):
        self.raw = raw


class _FakeAccount:
    """Stand-in for `wealthfolio.models.Account`, only carrying the
    id/name/currency fields `accounts-delete`'s lookup-and-print step
    reads."""

    def __init__(self, id, name, currency):
        self.id = id
        self.name = name
        self.currency = currency


class _FakeAccountsResult:
    """Stand-in for `wealthfolio.models.AccountsResult` -- only the
    `.accounts` attribute `accounts-delete` reads."""

    def __init__(self, accounts):
        self.accounts = accounts


class _FakeAsset:
    """Stand-in for `wealthfolio.models.Asset`, only carrying the
    id/name/kind/notes fields `asset-update`'s fetch-then-merge step
    (refilling every field the caller didn't pass) and `asset-delete`'s
    lookup-and-print step read."""

    def __init__(self, id, name, kind, notes=None):
        self.id = id
        self.name = name
        self.kind = kind
        self.notes = notes


class _FakeAssetProfile:
    """Stand-in for `wealthfolio.models.AssetProfile` -- only the
    `.asset`/`.raw` attributes the asset-CRUD handlers read."""

    def __init__(self, asset, raw=None):
        self.asset = asset
        self.raw = raw if raw is not None else {"id": asset.id, "notes": asset.notes}


class _FakeActivityDetails:
    """Stand-in for `wealthfolio.models.ActivityDetails` -- only the
    fields `activities-update`'s fetch-and-merge step and
    `activities-delete`'s lookup-and-print step read."""

    def __init__(
        self, id, account_id=None, activity_type=None, date=None,
        quantity=None, unit_price=None, currency=None, fee=None,
        tax=None, comment=None, asset_id=None,
    ):
        self.id = id
        self.account_id = account_id
        self.activity_type = activity_type
        self.date = date
        self.quantity = quantity
        self.unit_price = unit_price
        self.currency = currency
        self.fee = fee
        self.tax = tax
        self.comment = comment
        self.asset_id = asset_id


class _FakeSearchActivitiesResult:
    """Stand-in for `wealthfolio.models.ActivitiesResult` -- only the
    `.activities` attribute the activity-CRUD handlers' lookup steps
    read."""

    def __init__(self, activities):
        self.activities = activities


class _FakeActivityImportRow:
    """Stand-in for `wealthfolio.models.ActivityImportRow`, only carrying
    the fields `_print_activity_import_row_preview` reads."""

    def __init__(
        self, symbol=None, date=None, activity_type=None, is_valid=None,
        errors=None, warnings=None, duplicate_of_id=None,
    ):
        self.symbol = symbol
        self.date = date
        self.activity_type = activity_type
        self.is_valid = is_valid
        self.errors = errors if errors is not None else {}
        self.warnings = warnings if warnings is not None else {}
        self.duplicate_of_id = duplicate_of_id


class _FakePrepareResult:
    """Stand-in for `wealthfolio.models.PrepareActivityImportResult`/
    `ImportActivitiesResult` -- only the `.rows`/`.raw` attributes the
    import-preview/import-commit handlers read."""

    def __init__(self, rows, raw=None):
        self.rows = rows
        self.raw = raw if raw is not None else {"rows": len(rows)}


class _FakeClient:
    """Stand-in for wealthfolio.client.WealthfolioClient supporting the
    `with ... as client` usage in `_wealthfolio_rest_run`, with one canned
    method per subcommand. List-returning methods (net worth history,
    income) hand back a list of `_FakeResult`s to match the real client's
    bare-array response shapes."""

    def __init__(
        self, raw=None, calls=None, as_list=False, accounts=None,
        prepare_result=None, commit_result=None, asset=None, activities=None,
    ):
        self._raw = raw if raw is not None else {"ok": True}
        self._calls = calls if calls is not None else []
        self._as_list = as_list
        # `None` (default) preserves the old `get_accounts` -> _FakeResult
        # behavior used by the read-only `accounts` tests below; a (possibly
        # empty) list switches `get_accounts` to the `AccountsResult`-shaped
        # (`.accounts`) response the `accounts-delete` lookup step needs.
        self._accounts = accounts
        # `prepare_result`/`commit_result` let import-preview/import-commit
        # tests inject a `_FakePrepareResult` carrying `.rows` (of
        # `_FakeActivityImportRow`) -- `_record`'s plain `_FakeResult` has
        # no `.rows` attribute, which `_print_activity_import_row_preview`
        # needs.
        self._prepare_result = prepare_result
        self._commit_result = commit_result
        # `asset` (a `_FakeAsset`) switches `get_asset` to the
        # `AssetProfile`-shaped (`.asset`) response `asset-update`'s
        # notes-defaulting step and `asset-delete`'s lookup step need.
        self._asset = asset
        # `activities` (a list of `_FakeActivityDetails`) switches
        # `search_activities` to the `ActivitiesResult`-shaped (`.activities`)
        # response `activities-update`'s fetch-and-merge step and
        # `activities-delete`'s lookup step need.
        self._activities = activities

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def _record(self, name, kwargs):
        self._calls.append((name, kwargs))
        if self._as_list:
            return [_FakeResult(self._raw)]
        return _FakeResult(self._raw)

    def get_accounts(self, **kwargs):
        self._calls.append(("get_accounts", kwargs))
        if self._accounts is not None:
            return _FakeAccountsResult(self._accounts)
        if self._as_list:
            return [_FakeResult(self._raw)]
        return _FakeResult(self._raw)

    def create_account(self, **kwargs):
        return self._record("create_account", kwargs)

    def update_account(self, account_id, **kwargs):
        return self._record("update_account", {"account_id": account_id, **kwargs})

    def delete_account(self, account_id):
        return self._record("delete_account", {"account_id": account_id})

    def list_assets(self, **kwargs):
        return self._record("list_assets", kwargs)

    def get_asset(self, asset_id):
        self._calls.append(("get_asset", {"asset_id": asset_id}))
        if self._asset is not None:
            return _FakeAssetProfile(self._asset)
        if self._as_list:
            return [_FakeResult(self._raw)]
        return _FakeResult(self._raw)

    def create_asset(self, **kwargs):
        return self._record("create_asset", kwargs)

    def update_asset_profile(self, asset_id, **kwargs):
        return self._record("update_asset_profile", {"asset_id": asset_id, **kwargs})

    def delete_asset(self, asset_id):
        self._calls.append(("delete_asset", {"asset_id": asset_id}))
        return None

    def get_holdings(self, **kwargs):
        return self._record("get_holdings", kwargs)

    def get_cash_balances(self, **kwargs):
        return self._record("get_cash_balances", kwargs)

    def get_performance_summary(self, **kwargs):
        return self._record("get_performance_summary", kwargs)

    def get_performance_history(self, **kwargs):
        return self._record("get_performance_history", kwargs)

    def search_activities(self, **kwargs):
        self._calls.append(("search_activities", kwargs))
        if self._activities is not None:
            return _FakeSearchActivitiesResult(self._activities)
        if self._as_list:
            return [_FakeResult(self._raw)]
        return _FakeResult(self._raw)

    def create_activity(self, **kwargs):
        return self._record("create_activity", kwargs)

    def update_activity(self, **kwargs):
        return self._record("update_activity", kwargs)

    def delete_activity(self, activity_id):
        self._calls.append(("delete_activity", {"activity_id": activity_id}))
        return _FakeResult(self._raw)

    def save_activities(self, **kwargs):
        return self._record("save_activities", kwargs)

    def get_net_worth(self, **kwargs):
        return self._record("get_net_worth", kwargs)

    def get_net_worth_history(self, start_date, end_date):
        return self._record("get_net_worth_history", {"start_date": start_date, "end_date": end_date})

    def get_asset_allocation(self, **kwargs):
        return self._record("get_asset_allocation", kwargs)

    def get_income_summary(self, **kwargs):
        return self._record("get_income_summary", kwargs)

    def get_income_summary_query(self, **kwargs):
        return self._record("get_income_summary_query", kwargs)

    def get_health_status(self, **kwargs):
        return self._record("get_health_status", kwargs)

    def get_goals(self, **kwargs):
        return self._record("get_goals", kwargs)

    def get_contribution_limits(self, **kwargs):
        return self._record("get_contribution_limits", kwargs)

    def get_portfolios(self, **kwargs):
        return self._record("get_portfolios", kwargs)

    def list_asset_taxonomies(self, **kwargs):
        return self._record("list_asset_taxonomies", kwargs)

    def get_asset_taxonomy_assignments(self, asset_id, **kwargs):
        return self._record("get_asset_taxonomy_assignments", {"asset_id": asset_id, **kwargs})

    def prepare_asset_classification(self, asset_id, taxonomy_id, assignments):
        return self._record(
            "prepare_asset_classification",
            {"asset_id": asset_id, "taxonomy_id": taxonomy_id, "assignments": assignments},
        )

    def commit_asset_classification_draft(self, asset_id, taxonomy_id, assignments):
        return self._record(
            "commit_asset_classification_draft",
            {"asset_id": asset_id, "taxonomy_id": taxonomy_id, "assignments": assignments},
        )

    def list_categorization_context(self, **kwargs):
        return self._record("list_categorization_context", kwargs)

    def create_categorization_rule(self, **kwargs):
        return self._record("create_categorization_rule", kwargs)

    def get_import_mapping(self, **kwargs):
        return self._record("get_import_mapping", kwargs)

    def prepare_activity_import(self, **kwargs):
        self._calls.append(("prepare_activity_import", kwargs))
        if self._prepare_result is not None:
            return self._prepare_result
        return _FakeResult(self._raw)

    def commit_activity_import(self, **kwargs):
        self._calls.append(("commit_activity_import", kwargs))
        if self._commit_result is not None:
            return self._commit_result
        return _FakeResult(self._raw)


class WealthfolioRestParserTests(unittest.TestCase):
    """`build_parser()` wires all 8 read-only `wealthfolio-rest` subcommands
    plus the 3 accounts-CRUD subcommands."""

    def setUp(self):
        self.parser = cli.build_parser()

    def test_help_lists_all_subcommands(self):
        with redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["--help"])
        text = out.getvalue()
        for name in ("accounts", "holdings", "cash-balances", "performance", "activities",
                     "net-worth", "allocation", "income", "health",
                     "goals", "limits", "portfolios",
                     "taxonomies", "taxonomy-assignments", "classify-preview", "classify-commit",
                     "accounts-create", "accounts-update", "accounts-delete",
                     "categorization-context", "categorization-rule-create",
                     "import-mapping", "import-preview", "import-commit",
                     "assets", "asset", "asset-create", "asset-update", "asset-delete",
                     "activities-create", "activities-update", "activities-delete",
                     "activities-bulk"):
            self.assertIn(name, text)

    def test_no_legacy_named_activity_or_asset_write_subcommands_exposed(self):
        """Activity CRUD and asset CRUD
        are named `activities-*`/`asset-*` (verb-last, e.g. `activities-create`/
        `asset-create`), not the `create-activity`/`create-asset`-style names
        this test guards against -- those never got implemented under those
        legacy-style names, so the forbidden substrings below still never
        match the real subcommand names."""
        with redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["--help"])
        text = out.getvalue()
        for forbidden in ("create-activity", "update-activity", "delete-activity",
                           "create-asset", "update-asset", "delete-asset"):
            self.assertNotIn(forbidden, text)

    def test_accounts_takes_no_arguments(self):
        args = self.parser.parse_args(["accounts"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_accounts)

    def test_holdings_parses_kebab_flags(self):
        args = self.parser.parse_args([
            "holdings", "--account-id", "acc-1",
            "--account-ids", "acc-2", "--account-ids", "acc-3", "--include-closed",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_holdings)
        self.assertEqual(args.account_id, "acc-1")
        self.assertEqual(args.account_ids, ["acc-2", "acc-3"])
        self.assertTrue(args.include_closed)

    def test_cash_balances_parses_account_id(self):
        args = self.parser.parse_args([
            "cash-balances", "--account-id", "acc-1",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_cash_balances)
        self.assertEqual(args.account_id, "acc-1")
        self.assertIsNone(args.portfolio_id)
        self.assertIsNone(args.account_ids)
        self.assertFalse(args.include_accounts)

    def test_cash_balances_parses_portfolio_id(self):
        args = self.parser.parse_args([
            "cash-balances", "--portfolio-id", "port-1",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_cash_balances)
        self.assertEqual(args.portfolio_id, "port-1")
        self.assertIsNone(args.account_id)
        self.assertIsNone(args.account_ids)

    def test_cash_balances_parses_account_ids_and_include_accounts(self):
        args = self.parser.parse_args([
            "cash-balances", "--account-ids", "acc-2",
            "--account-ids", "acc-3", "--include-accounts",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_cash_balances)
        self.assertEqual(args.account_ids, ["acc-2", "acc-3"])
        self.assertIsNone(args.account_id)
        self.assertTrue(args.include_accounts)

    def test_cash_balances_no_flags_defaults_to_every_scope_arg_none(self):
        args = self.parser.parse_args(["cash-balances"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_cash_balances)
        self.assertIsNone(args.account_id)
        self.assertIsNone(args.portfolio_id)
        self.assertIsNone(args.account_ids)
        self.assertFalse(args.include_accounts)

    def test_performance_parses_history_flag(self):
        args = self.parser.parse_args([
            "performance", "--account-id", "acc-1",
            "--start-date", "2025-01-01", "--end-date", "2025-12-31", "--history",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_performance)
        self.assertEqual(args.account_id, "acc-1")
        self.assertTrue(args.history)

    def test_activities_uses_asset_id_keyword_not_symbol(self):
        args = self.parser.parse_args([
            "activities", "--asset-id-keyword", "NVDA", "--page", "2",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_activities)
        self.assertEqual(args.asset_id_keyword, "NVDA")
        self.assertFalse(hasattr(args, "symbol"))

    def test_net_worth_parses_kebab_flags(self):
        args = self.parser.parse_args(
            ["net-worth", "--date", "2025-06-01", "--start-date", "2024-01-01"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_net_worth)
        self.assertEqual(args.date, "2025-06-01")
        self.assertEqual(args.start_date, "2024-01-01")

    def test_income_has_no_period_flag(self):
        args = self.parser.parse_args(["income", "--account-id", "acc-1"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_income)
        self.assertFalse(hasattr(args, "period"))

    def test_health_takes_no_arguments(self):
        args = self.parser.parse_args(["health"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_health)

    def test_goals_takes_no_arguments(self):
        args = self.parser.parse_args(["goals"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_goals)

    def test_limits_takes_no_arguments(self):
        args = self.parser.parse_args(["limits"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_limits)

    def test_portfolios_takes_no_arguments(self):
        args = self.parser.parse_args(["portfolios"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_portfolios)

    def test_taxonomies_parses_all_four_flags(self):
        args = self.parser.parse_args([
            "taxonomies", "--taxonomy-id", "tax-1",
            "--taxonomy-name", "Asset Class", "--include-categories",
            "--category-depth", "2",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_taxonomies)
        self.assertEqual(args.taxonomy_id, "tax-1")
        self.assertEqual(args.taxonomy_name, "Asset Class")
        self.assertTrue(args.include_categories)
        self.assertEqual(args.category_depth, 2)

    def test_taxonomies_no_flags_defaults_to_none(self):
        args = self.parser.parse_args(["taxonomies"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_taxonomies)
        self.assertIsNone(args.taxonomy_id)
        self.assertIsNone(args.taxonomy_name)
        self.assertFalse(args.include_categories)
        self.assertIsNone(args.category_depth)

    def test_taxonomy_assignments_requires_asset_id(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["taxonomy-assignments"])
        args = self.parser.parse_args([
            "taxonomy-assignments", "--asset-id", "asset-1",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_taxonomy_assignments)
        self.assertEqual(args.asset_id, "asset-1")
        self.assertIsNone(args.taxonomy_id)

    def test_taxonomy_assignments_parses_optional_taxonomy_id(self):
        args = self.parser.parse_args([
            "taxonomy-assignments", "--asset-id", "asset-1",
            "--taxonomy-id", "tax-1",
        ])
        self.assertEqual(args.taxonomy_id, "tax-1")

    def test_classify_preview_requires_asset_and_taxonomy_id_and_assignments(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["classify-preview"])
        args = self.parser.parse_args([
            "classify-preview", "--asset-id", "asset-1",
            "--taxonomy-id", "tax-1", "--assignments", '[{"category_id": "cat-1"}]',
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_classify_preview)
        self.assertEqual(args.asset_id, "asset-1")
        self.assertEqual(args.taxonomy_id, "tax-1")
        self.assertEqual(args.assignments, '[{"category_id": "cat-1"}]')

    def test_classify_commit_requires_asset_and_taxonomy_id_and_assignments_defaults_no_yes(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["classify-commit"])
        args = self.parser.parse_args([
            "classify-commit", "--asset-id", "asset-1",
            "--taxonomy-id", "tax-1", "--assignments", '[{"category_id": "cat-1"}]',
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_classify_commit)
        self.assertEqual(args.assignments, '[{"category_id": "cat-1"}]')
        self.assertFalse(args.yes)

    def test_classify_commit_parses_yes_flag(self):
        args = self.parser.parse_args([
            "classify-commit", "--asset-id", "asset-1",
            "--taxonomy-id", "tax-1", "--assignments", '[{"category_id": "cat-1"}]', "--yes",
        ])
        self.assertTrue(args.yes)

    def test_categorization_context_parses_all_flags(self):
        args = self.parser.parse_args([
            "categorization-context",
            "--account-ids", "acc-1", "--account-ids", "acc-2",
            "--start-date", "2025-01-01", "--end-date", "2025-12-31",
            "--status", "needs_review", "--limit", "10", "--offset", "5",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_categorization_context)
        self.assertEqual(args.account_ids, ["acc-1", "acc-2"])
        self.assertEqual(args.start_date, "2025-01-01")
        self.assertEqual(args.end_date, "2025-12-31")
        self.assertEqual(args.status, "needs_review")
        self.assertEqual(args.limit, 10)
        self.assertEqual(args.offset, 5)

    def test_categorization_context_no_flags_defaults_to_none(self):
        args = self.parser.parse_args(["categorization-context"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_categorization_context)
        self.assertIsNone(args.account_ids)
        self.assertIsNone(args.start_date)
        self.assertIsNone(args.end_date)
        self.assertIsNone(args.status)
        self.assertIsNone(args.limit)
        self.assertIsNone(args.offset)

    def test_categorization_rule_create_requires_name_and_pattern(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["categorization-rule-create"])
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args([
                    "categorization-rule-create", "--name", "Groceries",
                ])
        args = self.parser.parse_args([
            "categorization-rule-create",
            "--name", "Groceries", "--pattern", "SUPERMARKET",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_categorization_rule_create)
        self.assertEqual(args.name, "Groceries")
        self.assertEqual(args.pattern, "SUPERMARKET")
        self.assertFalse(args.yes)
        self.assertIsNone(args.category_id)
        self.assertIsNone(args.is_global)

    def test_categorization_rule_create_parses_all_optional_flags(self):
        args = self.parser.parse_args([
            "categorization-rule-create",
            "--name", "Groceries", "--pattern", "SUPERMARKET",
            "--taxonomy-id", "tax-1", "--category-id", "cat-1",
            "--match-type", "contains", "--account-id", "acc-1",
            "--activity-type", "expense", "--amount-op", "gt",
            "--amount-value", "10", "--amount-value2", "100",
            "--priority", "5", "--is-global", "--yes",
        ])
        self.assertEqual(args.taxonomy_id, "tax-1")
        self.assertEqual(args.category_id, "cat-1")
        self.assertEqual(args.match_type, "contains")
        self.assertEqual(args.account_id, "acc-1")
        self.assertEqual(args.activity_type, "expense")
        self.assertEqual(args.amount_op, "gt")
        self.assertEqual(args.amount_value, "10")
        self.assertEqual(args.amount_value2, "100")
        self.assertEqual(args.priority, 5)
        self.assertTrue(args.is_global)
        self.assertTrue(args.yes)

    def test_accounts_create_requires_name_and_parses_camelcase_mapped_flags(self):
        args = self.parser.parse_args([
            "accounts-create", "--name", "Brokerage",
            "--account-type", "SECURITIES", "--currency", "EUR",
            "--is-default", "true", "--is-active", "false",
            "--group", "Investments", "--account-number", "ACC-123", "--yes",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_accounts_create)
        self.assertEqual(args.name, "Brokerage")
        self.assertEqual(args.account_type, "SECURITIES")
        self.assertEqual(args.currency, "EUR")
        self.assertEqual(args.is_default, "true")
        self.assertEqual(args.is_active, "false")
        self.assertEqual(args.group, "Investments")
        self.assertEqual(args.account_number, "ACC-123")
        self.assertTrue(args.yes)

    def test_accounts_create_missing_name_is_a_parse_error(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["accounts-create", "--currency", "EUR"])

    def test_accounts_update_requires_account_id_and_name_is_optional(self):
        args = self.parser.parse_args([
            "accounts-update", "--account-id", "acc-1",
            "--currency", "USD",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_accounts_update)
        self.assertEqual(args.account_id, "acc-1")
        self.assertEqual(args.currency, "USD")
        self.assertIsNone(args.name)
        self.assertFalse(args.yes)

    def test_accounts_delete_requires_account_id(self):
        args = self.parser.parse_args([
            "accounts-delete", "--account-id", "acc-1", "--yes",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_accounts_delete)
        self.assertEqual(args.account_id, "acc-1")
        self.assertTrue(args.yes)

    def test_import_mapping_requires_account_id_context_kind_optional(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["import-mapping"])
        args = self.parser.parse_args([
            "import-mapping", "--account-id", "acc-1",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_import_mapping)
        self.assertEqual(args.account_id, "acc-1")
        self.assertIsNone(args.context_kind)

    def test_import_mapping_accepts_explicit_context_kind(self):
        args = self.parser.parse_args([
            "import-mapping", "--account-id", "acc-1",
            "--context-kind", "CSV_HOLDINGS",
        ])
        self.assertEqual(args.context_kind, "CSV_HOLDINGS")

    def test_import_preview_requires_file_account_id_optional(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["import-preview"])
        args = self.parser.parse_args([
            "import-preview", "--file", "rows.csv",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_import_preview)
        self.assertEqual(args.file, "rows.csv")
        self.assertIsNone(args.account_id)

    def test_import_commit_requires_file_and_defaults_yes_false(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["import-commit"])
        args = self.parser.parse_args([
            "import-commit", "--file", "rows.json",
            "--account-id", "acc-1",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_import_commit)
        self.assertEqual(args.file, "rows.json")
        self.assertEqual(args.account_id, "acc-1")
        self.assertFalse(args.yes)

    def test_import_commit_accepts_yes_flag(self):
        args = self.parser.parse_args([
            "import-commit", "--file", "rows.json", "--yes",
        ])
        self.assertTrue(args.yes)

    def test_assets_takes_no_arguments(self):
        args = self.parser.parse_args(["assets"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_assets)

    def test_asset_requires_asset_id(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["asset"])
        args = self.parser.parse_args(["asset", "--asset-id", "asset-1"])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_asset)
        self.assertEqual(args.asset_id, "asset-1")

    def test_asset_create_requires_kind_and_quote_ccy(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["asset-create", "--name", "Foo"])
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args([
                    "asset-create", "--kind", "SECURITY", "--name", "Foo",
                ])
        args = self.parser.parse_args([
            "asset-create", "--kind", "SECURITY", "--quote-ccy", "EUR",
            "--name", "Foo", "--display-code", "FOO", "--quote-mode", "MANUAL",
            "--instrument-type", "EQUITY", "--instrument-symbol", "FOO.MC",
            "--instrument-exchange-mic", "XMAD", "--notes", "some notes",
            "--metadata-json", '{"a": 1}', "--provider-config-json", '{"b": 2}', "--yes",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_asset_create)
        self.assertEqual(args.kind, "SECURITY")
        self.assertEqual(args.quote_ccy, "EUR")
        self.assertEqual(args.name, "Foo")
        self.assertEqual(args.display_code, "FOO")
        self.assertEqual(args.quote_mode, "MANUAL")
        self.assertEqual(args.instrument_type, "EQUITY")
        self.assertEqual(args.instrument_symbol, "FOO.MC")
        self.assertEqual(args.instrument_exchange_mic, "XMAD")
        self.assertEqual(args.notes, "some notes")
        self.assertEqual(args.metadata_json, '{"a": 1}')
        self.assertEqual(args.provider_config_json, '{"b": 2}')
        self.assertTrue(args.yes)

    def test_asset_update_requires_asset_id_kind_and_quote_ccy_optional(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["asset-update"])
        args = self.parser.parse_args([
            "asset-update", "--asset-id", "asset-1",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_asset_update)
        self.assertEqual(args.asset_id, "asset-1")
        self.assertIsNone(args.kind)
        self.assertIsNone(args.quote_ccy)
        self.assertIsNone(args.notes)
        self.assertFalse(args.yes)

    def test_asset_delete_requires_asset_id(self):
        args = self.parser.parse_args([
            "asset-delete", "--asset-id", "asset-1", "--yes",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_asset_delete)
        self.assertEqual(args.asset_id, "asset-1")
        self.assertTrue(args.yes)

    def test_activities_create_requires_account_type_date_and_translates_asset_id(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["activities-create"])
        args = self.parser.parse_args([
            "activities-create",
            "--account-id", "acc-1", "--activity-type", "BUY",
            "--activity-date", "2026-01-01", "--asset-id", "asset-1",
            "--quantity", "10", "--unit-price", "5.5", "--currency", "EUR",
            "--fee", "1.5", "--tax", "0.5", "--notes", "some notes",
            "--metadata-json", '{"a": 1}', "--yes",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_activities_create)
        self.assertEqual(args.account_id, "acc-1")
        self.assertEqual(args.activity_type, "BUY")
        self.assertEqual(args.activity_date, "2026-01-01")
        self.assertEqual(args.asset_id, "asset-1")
        self.assertEqual(args.quantity, 10.0)
        self.assertEqual(args.unit_price, 5.5)
        self.assertEqual(args.currency, "EUR")
        self.assertEqual(args.fee, 1.5)
        self.assertEqual(args.tax, 0.5)
        self.assertEqual(args.notes, "some notes")
        self.assertEqual(args.metadata_json, '{"a": 1}')
        self.assertTrue(args.yes)

    def test_activities_create_accepts_comment_alias_for_notes(self):
        args = self.parser.parse_args([
            "activities-create",
            "--account-id", "acc-1", "--activity-type", "BUY",
            "--activity-date", "2026-01-01", "--comment", "aliased notes",
        ])
        self.assertEqual(args.notes, "aliased notes")

    def test_activities_update_requires_activity_id_other_fields_optional(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["activities-update"])
        args = self.parser.parse_args([
            "activities-update", "--activity-id", "act-1",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_activities_update)
        self.assertEqual(args.activity_id, "act-1")
        self.assertIsNone(args.account_id)
        self.assertIsNone(args.activity_type)
        self.assertFalse(args.yes)

    def test_activities_delete_requires_activity_id(self):
        args = self.parser.parse_args([
            "activities-delete", "--activity-id", "act-1", "--yes",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_activities_delete)
        self.assertEqual(args.activity_id, "act-1")
        self.assertTrue(args.yes)

    def test_activities_bulk_parses_repeatable_delete_ids(self):
        args = self.parser.parse_args([
            "activities-bulk",
            "--creates-json", '[{"accountId": "acc-1"}]',
            "--updates-json", '[{"id": "act-1"}]',
            "--delete-ids", "act-2,act-3", "--delete-ids", "act-4", "--yes",
        ])
        self.assertIs(args.func, cli.cmd_wealthfolio_rest_activities_bulk)
        self.assertEqual(args.creates_json, '[{"accountId": "acc-1"}]')
        self.assertEqual(args.updates_json, '[{"id": "act-1"}]')
        self.assertEqual(args.delete_ids, ["act-2,act-3", "act-4"])
        self.assertTrue(args.yes)

    def test_activities_bulk_defaults_all_optional(self):
        args = self.parser.parse_args(["activities-bulk"])
        self.assertIsNone(args.creates_json)
        self.assertIsNone(args.updates_json)
        self.assertIsNone(args.delete_ids)
        self.assertFalse(args.yes)


class WealthfolioRestHandlerTests(unittest.TestCase):
    """`cmd_wealthfolio_rest_*` handlers are thin JSON pass-throughs with
    clean error handling (no raw tracebacks leak to the caller)."""

    def _run(self, func, args, fake_client):
        with mock.patch("wealthfolio.client.WealthfolioClient.from_env", return_value=fake_client):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    func(args)
                    exited = None
                except SystemExit as exc:
                    exited = exc.code
        return out.getvalue(), err.getvalue(), exited

    def test_accounts_emits_raw_json_on_stdout(self):
        calls = []
        fake_client = _FakeClient(raw={"count": 1}, calls=calls)
        args = mock.Mock()
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_accounts, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"count": 1', out)
        self.assertEqual(calls, [("get_accounts", {})])

    def test_assets_emits_raw_json_on_stdout(self):
        calls = []
        fake_client = _FakeClient(raw={"count": 1}, calls=calls)
        args = mock.Mock()
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_assets, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"count": 1', out)
        self.assertEqual(calls, [("list_assets", {})])

    def test_asset_forwards_asset_id_and_emits_full_raw_json(self):
        """`asset` prints `.raw` verbatim -- the full server response,
        including `notes`/`metadata` -- with no client-side truncation or
        summarization."""
        calls = []
        fake_client = _FakeClient(
            raw={"id": "asset-1", "notes": "long notes text", "metadata": {"k": "v"}},
            calls=calls,
        )
        args = mock.Mock(asset_id="asset-1")
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_asset, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"notes": "long notes text"', out)
        self.assertIn('"metadata"', out)
        self.assertEqual(calls, [("get_asset", {"asset_id": "asset-1"})])

    def test_activities_omits_page_and_page_size_when_not_given(self):
        """Regression test: `--page`/`--page-size` both default to `None`
        in the parser, but `WealthfolioClient.search_activities(page=...)`
        computes `page - 1` unconditionally -- passing `page=None` through
        raised `TypeError: unsupported operand type(s) for -: 'NoneType'
        and 'int'` on every plain `activities` call that omitted `--page`.
        The handler must omit `page`/`page_size` from
        the forwarded kwargs entirely when unset, letting the client's own
        defaults (`page=1`, `page_size=DEFAULT_ACTIVITIES_PAGE_SIZE`) apply."""
        calls = []
        fake_client = _FakeClient(raw={"data": []}, calls=calls)
        args = mock.Mock(
            account_id=None, activity_type=None, asset_id_keyword="NVDA",
            date_from=None, date_to=None, page=None, page_size=None,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(calls, [("search_activities", {
            "account_id": None, "activity_type": None, "asset_id_keyword": "NVDA",
            "date_from": None, "date_to": None,
        })])

    def test_activities_forwards_page_and_page_size_when_given(self):
        calls = []
        fake_client = _FakeClient(raw={"data": []}, calls=calls)
        args = mock.Mock(
            account_id=None, activity_type=None, asset_id_keyword=None,
            date_from=None, date_to=None, page=2, page_size=25,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(calls, [("search_activities", {
            "account_id": None, "activity_type": None, "asset_id_keyword": None,
            "date_from": None, "date_to": None, "page": 2, "page_size": 25,
        })])

    def test_goals_emits_raw_json_on_stdout(self):
        calls = []
        fake_client = _FakeClient(raw={"goals": []}, calls=calls)
        args = mock.Mock()
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_goals, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"goals": []', out)
        self.assertEqual(calls, [("get_goals", {})])

    def test_limits_emits_raw_json_on_stdout(self):
        calls = []
        fake_client = _FakeClient(raw={"limits": []}, calls=calls)
        args = mock.Mock()
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_limits, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"limits": []', out)
        self.assertEqual(calls, [("get_contribution_limits", {})])

    def test_portfolios_emits_raw_json_on_stdout(self):
        calls = []
        fake_client = _FakeClient(raw={"portfolios": []}, calls=calls)
        args = mock.Mock()
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_portfolios, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"portfolios": []', out)
        self.assertEqual(calls, [("get_portfolios", {})])

    def test_taxonomies_forwards_all_four_flags(self):
        calls = []
        fake_client = _FakeClient(raw={"taxonomies": []}, calls=calls)
        args = mock.Mock(
            taxonomy_id="tax-1", taxonomy_name="Asset Class",
            include_categories=True, category_depth=2,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_taxonomies, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"taxonomies": []', out)
        self.assertEqual(calls, [(
            "list_asset_taxonomies",
            {"taxonomy_id": "tax-1", "taxonomy_name": "Asset Class",
             "include_categories": True, "category_depth": 2},
        )])

    def test_taxonomy_assignments_forwards_asset_id_and_taxonomy_id(self):
        calls = []
        fake_client = _FakeClient(raw={"assignments": []}, calls=calls)
        args = mock.Mock(asset_id="asset-1", taxonomy_id="tax-1")
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_taxonomy_assignments, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"assignments": []', out)
        self.assertEqual(
            calls, [("get_asset_taxonomy_assignments", {"asset_id": "asset-1", "taxonomy_id": "tax-1"})])

    def test_taxonomy_assignments_no_taxonomy_id_forwards_none(self):
        calls = []
        fake_client = _FakeClient(raw={"assignments": []}, calls=calls)
        args = mock.Mock(asset_id="asset-1", taxonomy_id=None)
        self._run(cli.cmd_wealthfolio_rest_taxonomy_assignments, args, fake_client)
        self.assertEqual(
            calls, [("get_asset_taxonomy_assignments", {"asset_id": "asset-1", "taxonomy_id": None})])

    def test_classify_preview_forwards_parsed_assignments(self):
        calls = []
        fake_client = _FakeClient(raw={"proposed": []}, calls=calls)
        args = mock.Mock(
            asset_id="asset-1", taxonomy_id="tax-1",
            assignments='[{"category_id": "cat-1", "weight": 5000}]',
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_classify_preview, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"proposed": []', out)
        self.assertEqual(calls, [(
            "prepare_asset_classification",
            {"asset_id": "asset-1", "taxonomy_id": "tax-1",
             "assignments": [{"category_id": "cat-1", "weight": 5000}]},
        )])

    def test_classify_preview_invalid_json_errors_without_calling_client(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = mock.Mock(asset_id="asset-1", taxonomy_id="tax-1", assignments="not-json")
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_classify_preview, args, fake_client)
        self.assertEqual(exited, 1)
        self.assertEqual(calls, [])
        self.assertIn("not valid JSON", err)

    def test_classify_preview_non_list_json_errors_without_calling_client(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = mock.Mock(asset_id="asset-1", taxonomy_id="tax-1", assignments='{"category_id": "cat-1"}')
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_classify_preview, args, fake_client)
        self.assertEqual(exited, 1)
        self.assertEqual(calls, [])
        self.assertIn("must be a JSON list", err)

    def test_classify_commit_without_yes_previews_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = mock.Mock(
            asset_id="asset-1", taxonomy_id="tax-1",
            assignments='[{"category_id": "cat-1"}]', yes=False,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_classify_commit, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [])
        self.assertIn("Preview (dry-run)", out)
        self.assertIn('"category_id": "cat-1"', out)

    def test_classify_commit_with_yes_calls_commit_with_parsed_assignments(self):
        calls = []
        fake_client = _FakeClient(raw={"committed": True}, calls=calls)
        args = mock.Mock(
            asset_id="asset-1", taxonomy_id="tax-1",
            assignments='[{"category_id": "cat-1"}]', yes=True,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_classify_commit, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(calls, [(
            "commit_asset_classification_draft",
            {"asset_id": "asset-1", "taxonomy_id": "tax-1",
             "assignments": [{"category_id": "cat-1"}]},
        )])
        self.assertIn('"committed": true', out)

    def test_classify_commit_invalid_json_errors_without_calling_client(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = mock.Mock(asset_id="asset-1", taxonomy_id="tax-1", assignments="not-json", yes=True)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_classify_commit, args, fake_client)
        self.assertEqual(exited, 1)
        self.assertEqual(calls, [])
        self.assertIn("not valid JSON", err)

    def test_categorization_context_forwards_all_flags(self):
        calls = []
        fake_client = _FakeClient(raw={"items": []}, calls=calls)
        args = mock.Mock(
            account_ids=["acc-1", "acc-2"], start_date="2025-01-01", end_date="2025-12-31",
            status="needs_review", limit=10, offset=5,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_categorization_context, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"items": []', out)
        self.assertEqual(calls, [(
            "list_categorization_context",
            {"account_ids": ["acc-1", "acc-2"], "start_date": "2025-01-01", "end_date": "2025-12-31",
             "status": "needs_review", "limit": 10, "offset": 5},
        )])

    def test_categorization_context_omitted_status_forwards_none(self):
        """Confirms the CLI forwards a bare `None` for `--status` when it's
        not passed, letting `WealthfolioClient.list_categorization_context`
        apply its own `"uncategorized"` default rather than the CLI
        hard-coding one."""
        calls = []
        fake_client = _FakeClient(raw={"items": []}, calls=calls)
        args = mock.Mock(
            account_ids=None, start_date=None, end_date=None, status=None, limit=None, offset=None,
        )
        self._run(cli.cmd_wealthfolio_rest_categorization_context, args, fake_client)
        self.assertEqual(calls, [(
            "list_categorization_context",
            {"account_ids": None, "start_date": None, "end_date": None,
             "status": None, "limit": None, "offset": None},
        )])

    def test_categorization_rule_create_without_yes_previews_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = mock.Mock(
            pattern="SUPERMARKET", taxonomy_id=None, category_id=None, match_type=None,
            account_id=None, activity_type=None, amount_op=None, amount_value=None,
            amount_value2=None, priority=None, is_global=None, yes=False,
        )
        args.name = "Groceries"  # `name` can't be a `Mock(...)` constructor kwarg (reserved)
        out, err, exited = self._run(
            cli.cmd_wealthfolio_rest_categorization_rule_create, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [])
        self.assertIn("Preview (dry-run)", out)
        self.assertIn('"name": "Groceries"', out)
        self.assertIn('"pattern": "SUPERMARKET"', out)
        self.assertNotIn("taxonomy_id", out)

    def test_categorization_rule_create_with_yes_calls_client_omitting_unset_fields(self):
        calls = []
        fake_client = _FakeClient(raw={"id": "rule-1"}, calls=calls)
        args = mock.Mock(
            pattern="SUPERMARKET", taxonomy_id=None, category_id=None, match_type=None,
            account_id=None, activity_type=None, amount_op=None, amount_value=None,
            amount_value2=None, priority=None, is_global=None, yes=True,
        )
        args.name = "Groceries"  # `name` can't be a `Mock(...)` constructor kwarg (reserved)
        out, err, exited = self._run(
            cli.cmd_wealthfolio_rest_categorization_rule_create, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(calls, [(
            "create_categorization_rule",
            {"name": "Groceries", "pattern": "SUPERMARKET"},
        )])
        self.assertIn('"id": "rule-1"', out)

    def test_categorization_rule_create_with_yes_forwards_all_optional_fields(self):
        calls = []
        fake_client = _FakeClient(raw={"id": "rule-1"}, calls=calls)
        args = mock.Mock(
            pattern="SUPERMARKET", taxonomy_id="tax-1", category_id="cat-1",
            match_type="contains", account_id="acc-1", activity_type="expense",
            amount_op="gt", amount_value="10", amount_value2="100",
            priority=5, is_global=True, yes=True,
        )
        args.name = "Groceries"  # `name` can't be a `Mock(...)` constructor kwarg (reserved)
        self._run(cli.cmd_wealthfolio_rest_categorization_rule_create, args, fake_client)
        self.assertEqual(calls, [(
            "create_categorization_rule",
            {
                "name": "Groceries", "pattern": "SUPERMARKET", "taxonomy_id": "tax-1",
                "category_id": "cat-1", "match_type": "contains", "account_id": "acc-1",
                "activity_type": "expense", "amount_op": "gt", "amount_value": "10",
                "amount_value2": "100", "priority": 5, "is_global": True,
            },
        )])

    def test_cash_balances_forwards_scope_and_include_accounts_flags(self):
        calls = []
        fake_client = _FakeClient(raw={"cash": 0}, calls=calls)
        args = mock.Mock(
            account_id=None, portfolio_id="pf-1", account_ids=None, include_accounts=True)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_cash_balances, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertIn('"cash": 0', out)
        self.assertEqual(calls, [(
            "get_cash_balances",
            {"account_id": None, "portfolio_id": "pf-1", "account_ids": None, "include_accounts": True},
        )])

    def test_performance_calls_summary_by_default_and_history_when_flagged(self):
        calls = []
        fake_client = _FakeClient(raw={"mode": "summary"}, calls=calls)
        args = mock.Mock(
            account_id="acc-1", portfolio_id=None, account_ids=None,
            item_id=None, item_type="account", start_date=None, end_date=None,
            tracking_mode=None, profile=None, history=False,
        )
        self._run(cli.cmd_wealthfolio_rest_performance, args, fake_client)
        self.assertEqual(calls[0][0], "get_performance_summary")

        calls.clear()
        args.history = True
        self._run(cli.cmd_wealthfolio_rest_performance, args, fake_client)
        self.assertEqual(calls[0][0], "get_performance_history")

    def test_net_worth_uses_history_only_when_start_date_given(self):
        calls = []
        fake_client = _FakeClient(raw={"netWorth": 1}, calls=calls, as_list=True)
        args = mock.Mock(date="2025-06-01", start_date="2024-01-01")
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_net_worth, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [("get_net_worth_history", {"start_date": "2024-01-01", "end_date": "2025-06-01"})])
        self.assertIn('"netWorth": 1', out)

    def test_income_prefers_scoped_query_over_single_account(self):
        calls = []
        fake_client = _FakeClient(raw={"totalIncome": 0}, calls=calls, as_list=True)
        args = mock.Mock(account_id="acc-1", portfolio_id="pf-1", account_ids=None)
        self._run(cli.cmd_wealthfolio_rest_income, args, fake_client)
        self.assertEqual(calls, [("get_income_summary_query", {"portfolio_id": "pf-1", "account_ids": None})])

    def test_config_error_is_actionable_and_exits_nonzero(self):
        args = mock.Mock()
        with mock.patch("wealthfolio.client.WealthfolioClient.from_env",
                        side_effect=WealthfolioConfigError("no password found")):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    cli.cmd_wealthfolio_rest_accounts(args)
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("[wealthfolio-rest] ERROR", err.getvalue())
        self.assertIn("WEALTHFOLIO_PASSWORD", err.getvalue())

    def test_wealthfolio_error_exits_nonzero_without_traceback(self):
        args = mock.Mock()
        with mock.patch("wealthfolio.client.WealthfolioClient.from_env",
                        side_effect=WealthfolioError("request failed")):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    cli.cmd_wealthfolio_rest_health(args)
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("[wealthfolio-rest] ERROR: request failed", err.getvalue())

    def test_import_mapping_forwards_account_id_and_context_kind(self):
        calls = []
        fake_client = _FakeClient(raw={"accountId": "acc-1"}, calls=calls)
        args = mock.Mock(account_id="acc-1", context_kind="CSV_HOLDINGS")
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_import_mapping, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(calls, [(
            "get_import_mapping", {"account_id": "acc-1", "context_kind": "CSV_HOLDINGS"},
        )])
        self.assertIn('"accountId": "acc-1"', out)

    def test_import_mapping_omits_context_kind_when_none(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = mock.Mock(account_id="acc-1", context_kind=None)
        self._run(cli.cmd_wealthfolio_rest_import_mapping, args, fake_client)
        self.assertEqual(calls, [(
            "get_import_mapping", {"account_id": "acc-1", "context_kind": None},
        )])

    def test_import_preview_forwards_loaded_rows_and_prints_per_row_summary(self):
        calls = []
        rows = [
            _FakeActivityImportRow(
                symbol="NVDA", date="2025-01-01", activity_type="BUY", is_valid=True,
            ),
            _FakeActivityImportRow(
                symbol="MSFT", date="2025-01-02", activity_type="SELL", is_valid=False,
                errors={"quantity": ["required"]}, duplicate_of_id="existing-1",
            ),
        ]
        fake_client = _FakeClient(calls=calls, prepare_result=_FakePrepareResult(rows))
        args = mock.Mock(file="rows.json", account_id=None)
        with mock.patch.object(
            cli, "_load_activity_import_rows", return_value=[{"symbol": "NVDA"}, {"symbol": "MSFT"}],
        ) as load_mock:
            out, err, exited = self._run(cli.cmd_wealthfolio_rest_import_preview, args, fake_client)
        load_mock.assert_called_once_with("rows.json", account_id=None)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(calls, [(
            "prepare_activity_import", {"activities": [{"symbol": "NVDA"}, {"symbol": "MSFT"}]},
        )])
        self.assertIn("row 0: symbol=NVDA date=2025-01-01 type=BUY valid=True "
                      "errors=none warnings=none duplicate_of=none", out)
        self.assertIn("duplicate_of=existing-1", out)
        self.assertIn('"rows": 2', out)

    def test_import_commit_without_yes_previews_via_prepare_and_does_not_commit(self):
        calls = []
        rows = [_FakeActivityImportRow(symbol="NVDA", date="2025-01-01", activity_type="BUY", is_valid=True)]
        fake_client = _FakeClient(calls=calls, prepare_result=_FakePrepareResult(rows))
        args = mock.Mock(file="rows.csv", account_id=None, yes=False)
        with mock.patch.object(cli, "_load_activity_import_rows", return_value=[{"symbol": "NVDA"}]):
            out, err, exited = self._run(cli.cmd_wealthfolio_rest_import_commit, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(calls, [("prepare_activity_import", {"activities": [{"symbol": "NVDA"}]})])
        self.assertIn("Preview (dry-run)", out)
        self.assertIn("row 0: symbol=NVDA", out)

    def test_import_commit_with_yes_calls_commit_not_prepare(self):
        calls = []
        fake_client = _FakeClient(raw={"importRunId": "run-1"}, calls=calls)
        args = mock.Mock(file="rows.csv", account_id="acc-1", yes=True)
        with mock.patch.object(cli, "_load_activity_import_rows", return_value=[{"symbol": "NVDA"}]) as load_mock:
            out, err, exited = self._run(cli.cmd_wealthfolio_rest_import_commit, args, fake_client)
        load_mock.assert_called_once_with("rows.csv", account_id="acc-1")
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(calls, [("commit_activity_import", {"activities": [{"symbol": "NVDA"}]})])
        self.assertIn('"importRunId": "run-1"', out)


class LoadActivityImportRowsTests(unittest.TestCase):
    """`_load_activity_import_rows` loads `.json`/CSV files into
    `ActivityImport`-shaped row dicts with actionable failures (clean
    `sys.exit(1)`, never a traceback) on malformed input."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def _path(self, name):
        import os as _os
        return _os.path.join(self._tmpdir.name, name)

    def test_loads_json_list_verbatim(self):
        import json
        path = self._path("rows.json")
        payload = [{"date": "2025-01-01", "symbol": "NVDA", "activityType": "BUY",
                    "currency": "USD", "isDraft": False, "isValid": True}]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        rows = cli._load_activity_import_rows(path)
        self.assertEqual(rows, payload)

    def test_json_non_list_top_level_exits_1(self):
        import json
        path = self._path("rows.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"not": "a list"}, f)
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli._load_activity_import_rows(path)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("must contain a JSON list", err.getvalue())

    def test_missing_file_exits_1(self):
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli._load_activity_import_rows(self._path("does-not-exist.json"))
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("not found", err.getvalue())

    def test_loads_csv_coercing_booleans_numerics_and_dropping_empty_strings(self):
        path = self._path("rows.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(
                "date,symbol,activityType,currency,isDraft,isValid,quantity,unitPrice,comment\n"
                "2025-01-01,NVDA,BUY,USD,false,true,10,120.5,\n"
            )
        rows = cli._load_activity_import_rows(path)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIs(row["isDraft"], False)
        self.assertIs(row["isValid"], True)
        self.assertEqual(row["quantity"], 10.0)
        self.assertEqual(row["unitPrice"], 120.5)
        self.assertNotIn("comment", row)  # empty string dropped

    def test_csv_bad_boolean_exits_1(self):
        path = self._path("rows.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("date,symbol,activityType,currency,isDraft,isValid\n"
                     "2025-01-01,NVDA,BUY,USD,maybe,true\n")
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli._load_activity_import_rows(path)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("row 1", err.getvalue())
        self.assertIn("isDraft", err.getvalue())

    def test_csv_bad_numeric_exits_1(self):
        path = self._path("rows.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("date,symbol,activityType,currency,isDraft,isValid,quantity\n"
                     "2025-01-01,NVDA,BUY,USD,true,true,not-a-number\n")
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli._load_activity_import_rows(path)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("row 1", err.getvalue())
        self.assertIn("quantity", err.getvalue())

    def test_account_id_fills_only_rows_missing_their_own(self):
        path = self._path("rows.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("date,symbol,activityType,currency,isDraft,isValid,accountId\n"
                     "2025-01-01,NVDA,BUY,USD,true,true,\n"
                     "2025-01-02,MSFT,BUY,USD,true,true,acc-own\n")
        rows = cli._load_activity_import_rows(path, account_id="acc-fallback")
        self.assertEqual(rows[0]["accountId"], "acc-fallback")
        self.assertEqual(rows[1]["accountId"], "acc-own")

    def test_account_id_fills_json_rows_missing_accountid_too(self):
        import json
        path = self._path("rows.json")
        payload = [{"symbol": "NVDA"}, {"symbol": "MSFT", "accountId": "acc-own"}]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        rows = cli._load_activity_import_rows(path, account_id="acc-fallback")
        self.assertEqual(rows[0]["accountId"], "acc-fallback")
        self.assertEqual(rows[1]["accountId"], "acc-own")


class WealthfolioRestAccountsCrudHandlerTests(unittest.TestCase):
    """`cmd_wealthfolio_rest_accounts_{create,update,delete}`:
    default to a dry-run preview and only perform the real write when
    `--yes` is given; field flags are forwarded verbatim as the camelCase
    kwargs the client expects (no snake_case translation happens in
    `client.py`, so the CLI must not add one either)."""

    def _run(self, func, args, fake_client):
        with mock.patch("wealthfolio.client.WealthfolioClient.from_env", return_value=fake_client):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    func(args)
                    exited = None
                except SystemExit as exc:
                    exited = exc.code
        return out.getvalue(), err.getvalue(), exited

    # ---- accounts-create -------------------------------------------------

    def test_create_without_yes_previews_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = mock.Mock(
            account_type="SECURITIES", currency="EUR",
            is_default=None, is_active=None, group=None, account_number=None,
            yes=False,
        )
        args.name = "Brokerage"  # `name` can't be a `Mock(...)` constructor kwarg (reserved)
        # No `WealthfolioClient.from_env` mock needed for the preview path,
        # but patching it anyway proves the preview never opens a connection.
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_accounts_create, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [])
        self.assertIn("Preview (dry-run)", out)
        self.assertIn('"name": "Brokerage"', out)
        self.assertIn('"accountType": "SECURITIES"', out)
        self.assertIn('"currency": "EUR"', out)

    def test_create_with_yes_calls_create_account_with_camelcase_fields(self):
        calls = []
        fake_client = _FakeClient(raw={"id": "new-1"}, calls=calls)
        args = mock.Mock(
            account_type="SECURITIES", currency="EUR",
            is_default="true", is_active="false", group="Investments",
            account_number="ACC-123", yes=True,
        )
        args.name = "Brokerage"  # `name` can't be a `Mock(...)` constructor kwarg (reserved)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_accounts_create, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(len(calls), 1)
        name, kwargs = calls[0]
        self.assertEqual(name, "create_account")
        self.assertEqual(kwargs, {
            "name": "Brokerage", "accountType": "SECURITIES", "currency": "EUR",
            "isDefault": True, "isActive": False, "group": "Investments",
            "accountNumber": "ACC-123",
        })
        self.assertIn('"id": "new-1"', out)

    # ---- accounts-update --------------------------------------------------

    def test_update_without_yes_previews_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = mock.Mock(
            account_id="acc-1", account_type=None, currency="USD",
            is_default=None, is_active=None, group=None, account_number=None,
            yes=False,
        )
        args.name = None  # `name` can't be a `Mock(...)` constructor kwarg (reserved)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_accounts_update, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [])
        self.assertIn("Preview (dry-run)", out)
        self.assertIn("acc-1", out)
        self.assertIn('"currency": "USD"', out)

    def test_update_with_yes_calls_update_account_with_only_forwarded_fields(self):
        calls = []
        fake_client = _FakeClient(raw={"id": "acc-1"}, calls=calls)
        args = mock.Mock(
            account_id="acc-1", account_type=None, currency="USD",
            is_default=None, is_active="true", group=None, account_number=None,
            yes=True,
        )
        args.name = None  # `name` can't be a `Mock(...)` constructor kwarg (reserved)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_accounts_update, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(len(calls), 1)
        name, kwargs = calls[0]
        self.assertEqual(name, "update_account")
        self.assertEqual(kwargs, {"account_id": "acc-1", "currency": "USD", "isActive": True})

    def test_update_with_no_fields_errors_without_calling_client(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = mock.Mock(
            account_id="acc-1", account_type=None, currency=None,
            is_default=None, is_active=None, group=None, account_number=None,
            yes=True,
        )
        args.name = None  # `name` can't be a `Mock(...)` constructor kwarg (reserved)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_accounts_update, args, fake_client)
        self.assertEqual(exited, 1)
        self.assertEqual(calls, [])
        self.assertIn("no fields given", err)

    # ---- accounts-delete ---------------------------------------------------

    def test_delete_without_yes_previews_looked_up_account_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(
            calls=calls,
            accounts=[_FakeAccount(id="acc-1", name="Brokerage", currency="EUR")],
        )
        args = mock.Mock(account_id="acc-1", yes=False)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_accounts_delete, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [("get_accounts", {})])
        self.assertIn("Brokerage", out)
        self.assertIn("EUR", out)
        self.assertIn("Pass --yes", out)

    def test_delete_with_yes_looks_up_then_calls_delete_account(self):
        calls = []
        fake_client = _FakeClient(
            raw={"id": "acc-1"},
            calls=calls,
            accounts=[_FakeAccount(id="acc-1", name="Brokerage", currency="EUR")],
        )
        args = mock.Mock(account_id="acc-1", yes=True)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_accounts_delete, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(
            calls,
            [("get_accounts", {}), ("delete_account", {"account_id": "acc-1"})],
        )
        self.assertIn('"deleted": true', out)
        self.assertIn('"id": "acc-1"', out)

    def test_delete_unknown_account_id_errors_without_calling_delete(self):
        calls = []
        fake_client = _FakeClient(calls=calls, accounts=[])
        args = mock.Mock(account_id="missing-1", yes=True)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_accounts_delete, args, fake_client)
        self.assertEqual(exited, 1)
        self.assertEqual(calls, [("get_accounts", {})])
        self.assertIn("no account found", err)


class LoadJsonArgTests(unittest.TestCase):
    """`_load_json_arg`: parses `--metadata-json`/
    `--provider-config-json`-style CLI values, either as inline JSON text
    or (if the value names an existing path) from a JSON file, and fails
    loud with an actionable stderr message + `sys.exit(1)` on malformed
    JSON."""

    def test_none_passes_through_unchanged(self):
        self.assertIsNone(cli._load_json_arg(None))

    def test_inline_json_string_is_parsed(self):
        result = cli._load_json_arg('{"a": 1, "b": [2, 3]}')
        self.assertEqual(result, {"a": 1, "b": [2, 3]})

    def test_json_file_path_is_loaded(self):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"x": "y"}')
            path = f.name
        try:
            result = cli._load_json_arg(path)
            self.assertEqual(result, {"x": "y"})
        finally:
            os.remove(path)

    def test_malformed_inline_json_exits_cleanly(self):
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli._load_json_arg("{not valid json", flag_name="--metadata-json")
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("--metadata-json", err.getvalue())
        self.assertIn("{not valid json", err.getvalue())


class WealthfolioRestAssetsCrudHandlerTests(unittest.TestCase):
    """`cmd_wealthfolio_rest_asset_{create,update,delete}`:
    default to a dry-run preview and only perform the real write when
    `--yes` is given; field flags are forwarded verbatim as the camelCase
    kwargs the client expects (no snake_case translation happens in
    `client.py`, so the CLI must not add one either). `asset-update`'s
    `--notes` gets special handling because the wire's
    `UpdateAssetProfile.notes` is required."""

    def _run(self, func, args, fake_client):
        with mock.patch("wealthfolio.client.WealthfolioClient.from_env", return_value=fake_client):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    func(args)
                    exited = None
                except SystemExit as exc:
                    exited = exc.code
        return out.getvalue(), err.getvalue(), exited

    def _asset_args(self, **overrides):
        defaults = dict(
            asset_id=None, kind=None, display_code=None, quote_mode=None,
            quote_ccy=None, instrument_type=None, instrument_symbol=None,
            instrument_exchange_mic=None, notes=None,
            metadata_json=None, provider_config_json=None, yes=False,
        )
        name = overrides.pop("name", None)
        defaults.update(overrides)
        args = mock.Mock(**defaults)
        args.name = name  # `name` can't be a `Mock(...)` constructor kwarg (reserved)
        return args

    # ---- asset-create -------------------------------------------------

    def test_create_without_yes_previews_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = self._asset_args(kind="SECURITY", quote_ccy="EUR", name="Foo")
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_asset_create, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [])
        self.assertIn("Preview (dry-run)", out)
        self.assertIn('"kind": "SECURITY"', out)
        self.assertIn('"quoteCcy": "EUR"', out)
        self.assertIn('"name": "Foo"', out)

    def test_create_with_yes_calls_create_asset_with_camelcase_fields_including_json_flags(self):
        calls = []
        fake_client = _FakeClient(raw={"id": "asset-new-1"}, calls=calls)
        args = self._asset_args(
            kind="SECURITY", quote_ccy="EUR", name="Foo", display_code="FOO",
            quote_mode="MANUAL", instrument_type="EQUITY",
            instrument_symbol="FOO.MC", instrument_exchange_mic="XMAD",
            notes="some notes", metadata_json='{"tag": "x"}',
            provider_config_json='{"provider": "manual"}', yes=True,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_asset_create, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(len(calls), 1)
        name, kwargs = calls[0]
        self.assertEqual(name, "create_asset")
        self.assertEqual(kwargs, {
            "kind": "SECURITY", "quoteCcy": "EUR", "name": "Foo",
            "displayCode": "FOO", "quoteMode": "MANUAL",
            "instrumentType": "EQUITY", "instrumentSymbol": "FOO.MC",
            "instrumentExchangeMic": "XMAD", "notes": "some notes",
            "metadata": {"tag": "x"}, "providerConfig": {"provider": "manual"},
        })
        self.assertIn('"id": "asset-new-1"', out)

    # ---- asset-update -------------------------------------------------

    def test_update_without_notes_flag_defaults_notes_from_fetched_asset(self):
        calls = []
        fake_client = _FakeClient(
            calls=calls,
            asset=_FakeAsset(id="asset-1", name="Foo", kind="SECURITY", notes="existing notes"),
        )
        args = self._asset_args(asset_id="asset-1", quote_ccy="USD", yes=True)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_asset_update, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual([c[0] for c in calls], ["get_asset", "update_asset_profile"])
        update_kwargs = calls[1][1]
        self.assertEqual(update_kwargs["notes"], "existing notes")
        self.assertEqual(update_kwargs["quoteCcy"], "USD")

    def test_update_with_explicit_notes_is_not_overridden_by_fetch(self):
        calls = []
        fake_client = _FakeClient(
            calls=calls,
            asset=_FakeAsset(id="asset-1", name="Foo", kind="SECURITY", notes="existing notes"),
        )
        args = self._asset_args(asset_id="asset-1", notes="", yes=True)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_asset_update, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        # The asset is always fetched now (every omitted field, not just
        # `notes`, must be refilled from the current profile since the
        # PUT is a full replacement) -- but the explicitly-passed
        # `--notes ""` still wins over whatever the fetch returned.
        self.assertEqual([c[0] for c in calls], ["get_asset", "update_asset_profile"])
        update_kwargs = calls[1][1]
        self.assertEqual(update_kwargs["notes"], "")

    def test_update_refills_unset_fields_from_fetched_asset(self):
        """A field the caller never mentioned (e.g. `name`) must be
        resent with its current value, not omitted -- omitting it would
        let the server's full-replace semantics null it out."""
        calls = []
        fake_client = _FakeClient(
            calls=calls,
            asset=_FakeAsset(id="asset-1", name="Foo Fund", kind="SECURITY", notes="existing notes"),
        )
        args = self._asset_args(asset_id="asset-1", quote_ccy="USD", yes=True)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_asset_update, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        update_kwargs = calls[1][1]
        self.assertEqual(update_kwargs["name"], "Foo Fund")
        self.assertEqual(update_kwargs["kind"], "SECURITY")
        self.assertEqual(update_kwargs["quoteCcy"], "USD")

    def test_update_without_yes_previews_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(
            calls=calls,
            asset=_FakeAsset(id="asset-1", name="Foo", kind="SECURITY", notes="existing notes"),
        )
        args = self._asset_args(asset_id="asset-1", quote_ccy="USD", yes=False)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_asset_update, args, fake_client)
        self.assertIsNone(exited)
        # `get_asset` is still called to build the preview (notes defaulting).
        self.assertEqual([c[0] for c in calls], ["get_asset"])
        self.assertIn("Preview (dry-run)", out)
        self.assertIn('"notes": "existing notes"', out)

    # ---- asset-delete ---------------------------------------------------

    def test_delete_without_yes_previews_looked_up_asset_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(
            calls=calls, asset=_FakeAsset(id="asset-1", name="Foo Fund", kind="SECURITY"),
        )
        args = mock.Mock(asset_id="asset-1", yes=False)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_asset_delete, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [("get_asset", {"asset_id": "asset-1"})])
        self.assertIn("Foo Fund", out)
        self.assertIn("Pass --yes", out)

    def test_delete_with_yes_looks_up_then_calls_delete_asset_and_handles_none_return(self):
        calls = []
        fake_client = _FakeClient(
            calls=calls, asset=_FakeAsset(id="asset-1", name="Foo Fund", kind="SECURITY"),
        )
        args = mock.Mock(asset_id="asset-1", yes=True)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_asset_delete, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(
            calls,
            [("get_asset", {"asset_id": "asset-1"}), ("delete_asset", {"asset_id": "asset-1"})],
        )
        self.assertIn('"deleted": true', out)
        self.assertIn('"id": "asset-1"', out)


class WealthfolioRestActivitiesCrudHandlerTests(unittest.TestCase):
    """`cmd_wealthfolio_rest_activities_{create,update,delete,bulk}`:
    default to a dry-run preview and only perform the
    real write when `--yes` is given; `--asset-id` is translated to the
    nested `symbol={"id": ...}` object the wire schema expects (no
    top-level `assetId`). `activities-update` fetches-and-merges any
    full-replace-required field not explicitly passed, via
    `search_activities` (there being no singular get-activity endpoint)."""

    def _run(self, func, args, fake_client):
        with mock.patch("wealthfolio.client.WealthfolioClient.from_env", return_value=fake_client):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    func(args)
                    exited = None
                except SystemExit as exc:
                    exited = exc.code
        return out.getvalue(), err.getvalue(), exited

    def _activity_args(self, **overrides):
        defaults = dict(
            activity_id=None, account_id=None, activity_type=None, activity_date=None,
            asset_id=None, quantity=None, unit_price=None, currency=None, fee=None,
            tax=None, notes=None, metadata_json=None, yes=False,
        )
        defaults.update(overrides)
        return mock.Mock(**defaults)

    # ---- activities-create ----------------------------------------------

    def test_create_without_yes_previews_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = self._activity_args(
            account_id="acc-1", activity_type="BUY", activity_date="2026-01-01",
            asset_id="asset-1", quantity=10.0,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities_create, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [])
        self.assertIn("Preview (dry-run)", out)
        self.assertIn('"accountId": "acc-1"', out)
        self.assertIn('"symbol"', out)
        self.assertIn('"id": "asset-1"', out)

    def test_create_with_yes_calls_create_activity_with_symbol_nesting(self):
        calls = []
        fake_client = _FakeClient(raw={"id": "act-new-1"}, calls=calls)
        args = self._activity_args(
            account_id="acc-1", activity_type="BUY", activity_date="2026-01-01",
            asset_id="asset-1", quantity=10.0, unit_price=5.5, currency="EUR",
            fee=1.5, tax=0.5, notes="some notes",
            metadata_json='{"tag": "x"}', yes=True,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities_create, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(len(calls), 1)
        name, kwargs = calls[0]
        self.assertEqual(name, "create_activity")
        self.assertEqual(kwargs, {
            "accountId": "acc-1", "activityType": "BUY", "activityDate": "2026-01-01",
            "quantity": 10.0, "unitPrice": 5.5, "currency": "EUR", "fee": 1.5,
            "tax": 0.5, "notes": "some notes", "symbol": {"id": "asset-1"},
            "metadata": {"tag": "x"},
        })
        self.assertIn('"id": "act-new-1"', out)

    # ---- activities-update ------------------------------------------------

    def test_update_without_fields_fetches_and_merges_from_current_activity(self):
        calls = []
        fake_client = _FakeClient(
            calls=calls,
            activities=[_FakeActivityDetails(
                id="act-1", account_id="acc-1", activity_type="BUY", date="2026-01-01",
                quantity=10.0, unit_price=5.0, currency="EUR", fee=1.0, tax=0.5,
                comment="old notes", asset_id="asset-1",
            )],
        )
        args = self._activity_args(activity_id="act-1", yes=True)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities_update, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual([c[0] for c in calls], ["search_activities", "update_activity"])
        self.assertEqual(calls[0][1], {"activity_id": ["act-1"]})
        update_kwargs = calls[1][1]
        self.assertEqual(update_kwargs, {
            "id": "act-1", "accountId": "acc-1", "activityType": "BUY",
            "activityDate": "2026-01-01", "quantity": 10.0, "unitPrice": 5.0,
            "currency": "EUR", "fee": 1.0, "tax": 0.5, "notes": "old notes",
            "symbol": {"id": "asset-1"},
        })

    def test_update_with_all_required_fields_explicit_skips_fetch(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = self._activity_args(
            activity_id="act-1", account_id="acc-1", activity_type="BUY",
            activity_date="2026-01-01", asset_id="asset-1", quantity=10.0,
            unit_price=5.0, currency="EUR", fee=1.0, yes=True,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities_update, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        # No `search_activities` fetch -- every required field was explicit.
        self.assertEqual([c[0] for c in calls], ["update_activity"])

    def test_update_without_yes_previews_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(
            calls=calls,
            activities=[_FakeActivityDetails(
                id="act-1", account_id="acc-1", activity_type="BUY", date="2026-01-01",
                quantity=10.0, unit_price=5.0, currency="EUR", fee=1.0,
            )],
        )
        args = self._activity_args(activity_id="act-1", yes=False)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities_update, args, fake_client)
        self.assertIsNone(exited)
        # `search_activities` is still called to build the preview.
        self.assertEqual([c[0] for c in calls], ["search_activities"])
        self.assertIn("Preview (dry-run)", out)
        self.assertIn('"accountId": "acc-1"', out)

    # ---- activities-delete --------------------------------------------------

    def test_delete_without_yes_previews_looked_up_activity_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(
            calls=calls,
            activities=[_FakeActivityDetails(
                id="act-1", account_id="acc-1", activity_type="SELL", date="2026-02-02",
            )],
        )
        args = mock.Mock(activity_id="act-1", yes=False)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities_delete, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [("search_activities", {"activity_id": ["act-1"]})])
        self.assertIn("SELL", out)
        self.assertIn("act-1", out)
        self.assertIn("Pass --yes", out)

    def test_delete_with_yes_looks_up_then_calls_delete_activity(self):
        calls = []
        fake_client = _FakeClient(
            raw={"id": "act-1", "notes": "deleted"},
            calls=calls,
            activities=[_FakeActivityDetails(
                id="act-1", account_id="acc-1", activity_type="SELL", date="2026-02-02",
            )],
        )
        args = mock.Mock(activity_id="act-1", yes=True)
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities_delete, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(
            calls,
            [("search_activities", {"activity_id": ["act-1"]}),
             ("delete_activity", {"activity_id": "act-1"})],
        )
        self.assertIn('"id": "act-1"', out)
        self.assertIn('"notes": "deleted"', out)

    # ---- activities-bulk ----------------------------------------------------

    def test_bulk_without_yes_previews_and_makes_no_write(self):
        calls = []
        fake_client = _FakeClient(calls=calls)
        args = mock.Mock(
            creates_json='[{"accountId": "acc-1"}]', updates_json=None,
            delete_ids=["act-2,act-3"], yes=False,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities_bulk, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(calls, [])
        self.assertIn("Preview (dry-run)", out)
        self.assertIn('"accountId": "acc-1"', out)
        self.assertIn('"act-2"', out)
        self.assertIn('"act-3"', out)

    def test_bulk_with_yes_calls_save_activities_and_prints_errors_passthrough(self):
        calls = []
        fake_client = _FakeClient(
            raw={
                "created": [{"id": "act-9"}],
                "updated": [], "deleted": [], "createdMappings": [],
                "errors": [{"id": "act-x", "action": "create", "message": "boom"}],
            },
            calls=calls,
        )
        args = mock.Mock(
            creates_json='[{"accountId": "acc-1"}]', updates_json=None,
            delete_ids=["act-9"], yes=True,
        )
        out, err, exited = self._run(cli.cmd_wealthfolio_rest_activities_bulk, args, fake_client)
        self.assertIsNone(exited)
        self.assertEqual(err, "")
        self.assertEqual(len(calls), 1)
        name, kwargs = calls[0]
        self.assertEqual(name, "save_activities")
        self.assertEqual(kwargs, {
            "creates": [{"accountId": "acc-1"}], "updates": [], "delete_ids": ["act-9"],
        })
        self.assertIn('"errors"', out)
        self.assertIn("boom", out)


if __name__ == "__main__":
    unittest.main()
