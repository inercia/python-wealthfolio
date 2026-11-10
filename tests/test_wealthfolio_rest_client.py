#!/usr/bin/env python3
"""Offline tests for the `wealthfolio` REST client (transport + auth only).

No real network calls are made -- `requests.Session.request` is mocked.

Run with:
    python -m unittest discover -s tests -p 'test_*.py' -v
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wealthfolio.client import (
    ACCOUNTS_PATH,
    ACTIVITIES_BULK_PATH,
    ACTIVITIES_IMPORT_CHECK_PATH,
    ACTIVITIES_IMPORT_MAPPING_PATH,
    ACTIVITIES_IMPORT_PATH,
    ACTIVITIES_PATH,
    ACTIVITIES_SEARCH_PATH,
    ALLOCATIONS_QUERY_PATH,
    ASSETS_PATH,
    ASSETS_PROFILE_PATH,
    GOALS_PATH,
    HEALTH_STATUS_PATH,
    HOLDINGS_QUERY_PATH,
    INCOME_SUMMARY_PATH,
    INCOME_SUMMARY_QUERY_PATH,
    LIMITS_PATH,
    LOGIN_PATH,
    NET_WORTH_HISTORY_PATH,
    NET_WORTH_PATH,
    PERFORMANCE_HISTORY_PATH,
    PERFORMANCE_SUMMARY_PATH,
    PORTFOLIOS_PATH,
    SESSION_COOKIE_NAME,
    SPENDING_CASH_ACTIVITIES_SEARCH_PATH,
    SPENDING_RULES_PATH,
    TAXONOMIES_PATH,
    TAXONOMY_ASSET_ASSIGNMENTS_PATH,
    VALUATIONS_CURRENT_QUERY_PATH,
    WealthfolioClient,
    _RestTransport,
)
from wealthfolio.config import WealthfolioRestConfig, load_dotenv, load_rest_config
from wealthfolio.exceptions import WealthfolioAPIError, WealthfolioConfigError
from wealthfolio.models import (
    Account,
    AccountsResult,
    Activity,
    ActivitiesResult,
    ActivityBulkMutationResult,
    ActivityDetails,
    ActivityImportRow,
    Asset,
    AssetAllocationResult,
    AssetProfile,
    AssetsResult,
    AssetTaxonomyAssignment,
    AssignmentPreview,
    CashActivitySearchResult,
    CashBalancesResult,
    CategorizationRule,
    ContributionLimit,
    ContributionLimitsResult,
    Goal,
    GoalsResult,
    HealthIssue,
    HealthStatusResult,
    Holding,
    HoldingsResult,
    ImportActivitiesResult,
    ImportMappingResult,
    IncomeSummary,
    NetWorthHistoryPoint,
    NetWorthResult,
    PerformanceResult,
    Portfolio,
    PortfoliosResult,
    PrepareActivityImportResult,
    PrepareAssetClassificationResult,
    Taxonomy,
    TaxonomiesResult,
    TaxonomyAssignmentsResult,
    TaxonomyWithCategories,
)

BASE_URL = "https://finance.example.test"


def _make_response(status_code=200, cookie=None, text=""):
    response = mock.Mock()
    response.status_code = status_code
    response.text = text
    response.cookies = mock.Mock()
    response.cookies.get = mock.Mock(return_value=cookie)
    return response


class RestTransportLoginTests(unittest.TestCase):
    def setUp(self):
        self.transport = _RestTransport(BASE_URL, "s3cret")

    def test_login_sends_browser_headers_and_password_body(self):
        with mock.patch.object(
            self.transport._http, "request",
            return_value=_make_response(200, cookie="cookie-value"),
        ) as mocked:
            self.transport._login()

        method, url = mocked.call_args.args
        self.assertEqual(method, "POST")
        self.assertEqual(url, BASE_URL + LOGIN_PATH)
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["json"], {"password": "s3cret"})
        headers = kwargs["headers"]
        self.assertIn("User-Agent", headers)
        self.assertEqual(headers["Origin"], BASE_URL)
        self.assertEqual(headers["Referer"], BASE_URL + "/")

    def test_login_failure_raises_api_error(self):
        with mock.patch.object(
            self.transport._http, "request",
            return_value=_make_response(401, text="bad password"),
        ):
            with self.assertRaises(WealthfolioAPIError) as ctx:
                self.transport._login()
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.body, "bad password")


class RestTransportRequestTests(unittest.TestCase):
    def setUp(self):
        self.transport = _RestTransport(BASE_URL, "s3cret")

    def test_session_cookie_captured_and_resent(self):
        login_response = _make_response(200, cookie="my-session-cookie")
        data_response = _make_response(200, text='{"ok": true}')
        with mock.patch.object(
            self.transport._http, "request",
            side_effect=[login_response, data_response],
        ) as mocked:
            self.transport.request("GET", "/api/v1/some/path")

        self.assertEqual(mocked.call_count, 2)
        second_call_cookies = mocked.call_args_list[1].kwargs["cookies"]
        self.assertEqual(second_call_cookies, {SESSION_COOKIE_NAME: "my-session-cookie"})

    def test_401_triggers_relogin_and_retry(self):
        self.transport._session_cookie = "stale-cookie"
        responses = [
            _make_response(401, text="expired"),               # first attempt: rejected
            _make_response(200, cookie="fresh-cookie"),          # re-login
            _make_response(200, text='{"ok": true}'),            # retried request
        ]
        with mock.patch.object(
            self.transport._http, "request", side_effect=responses,
        ) as mocked:
            response = self.transport.request("GET", "/api/v1/some/path")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked.call_count, 3)
        # The retried request must carry the freshly re-logged-in cookie.
        retried_cookies = mocked.call_args_list[2].kwargs["cookies"]
        self.assertEqual(retried_cookies, {SESSION_COOKIE_NAME: "fresh-cookie"})

    def test_non_2xx_raises_api_error_with_status_and_body(self):
        self.transport._session_cookie = "valid-cookie"
        with mock.patch.object(
            self.transport._http, "request",
            return_value=_make_response(500, text="internal error"),
        ):
            with self.assertRaises(WealthfolioAPIError) as ctx:
                self.transport.request("GET", "/api/v1/some/path")

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(ctx.exception.body, "internal error")


class ConfigTests(unittest.TestCase):
    def test_missing_base_url_raises_config_error(self):
        with mock.patch.dict(os.environ, {"WEALTHFOLIO_PASSWORD": "hunter2"}, clear=True):
            with self.assertRaises(WealthfolioConfigError):
                load_rest_config()

    def test_missing_password_raises_config_error(self):
        with mock.patch.dict(os.environ, {"WEALTHFOLIO_REST_URL": "https://custom.test"}, clear=True):
            with self.assertRaises(WealthfolioConfigError):
                load_rest_config()

    def test_password_and_url_resolved_from_env(self):
        env = {"WEALTHFOLIO_PASSWORD": "hunter2", "WEALTHFOLIO_REST_URL": "https://custom.test"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_rest_config()
        self.assertEqual(config.password, "hunter2")
        self.assertEqual(config.base_url, "https://custom.test")
        self.assertEqual(config.password_source, "env")

    def test_explicit_args_take_precedence_over_env(self):
        env = {"WEALTHFOLIO_PASSWORD": "hunter2", "WEALTHFOLIO_REST_URL": "https://custom.test"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_rest_config(base_url="https://explicit.test", password="explicit-pw")
        self.assertEqual(config.password, "explicit-pw")
        self.assertEqual(config.base_url, "https://explicit.test")
        self.assertEqual(config.password_source, "explicit")

    def test_load_rest_config_never_touches_filesystem(self):
        """`load_rest_config` must not read `.env` files itself -- only
        `os.environ`/explicit args."""
        env = {"WEALTHFOLIO_PASSWORD": "hunter2", "WEALTHFOLIO_REST_URL": "https://custom.test"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("wealthfolio.config.find_env_file") as mocked_find:
                load_rest_config()
        mocked_find.assert_not_called()


class LoadDotenvTests(unittest.TestCase):
    """`load_dotenv` is the opt-in helper a host application/CLI calls
    explicitly -- nothing in `config.py` calls it automatically."""

    def test_merges_file_values_without_overriding_real_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("WEALTHFOLIO_PASSWORD=from-file\nWEALTHFOLIO_REST_URL=https://from-file.test\n")
            with mock.patch.dict(os.environ, {"WEALTHFOLIO_PASSWORD": "from-real-env"}, clear=True):
                result = load_dotenv(env_path)
                self.assertEqual(result, env_path)
                self.assertEqual(os.environ["WEALTHFOLIO_PASSWORD"], "from-real-env")
                self.assertEqual(os.environ["WEALTHFOLIO_REST_URL"], "https://from-file.test")

    def test_override_true_lets_file_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("WEALTHFOLIO_PASSWORD=from-file\n")
            with mock.patch.dict(os.environ, {"WEALTHFOLIO_PASSWORD": "from-real-env"}, clear=True):
                load_dotenv(env_path, override=True)
                self.assertEqual(os.environ["WEALTHFOLIO_PASSWORD"], "from-file")

    def test_no_file_found_returns_none_without_raising(self):
        with mock.patch("wealthfolio.config.find_env_file", return_value=None):
            self.assertIsNone(load_dotenv())


def _make_json_response(status_code=200, json_data=None, text=""):
    response = mock.Mock()
    response.status_code = status_code
    response.text = text
    response.json = mock.Mock(return_value=json_data)
    return response


class WealthfolioClientAccountsTests(unittest.TestCase):
    """Offline tests for the accounts domain methods. Only
    `WealthfolioClient._transport.request` is mocked -- never a real
    network call -- so no test creates/updates/deletes a real account."""

    def setUp(self):
        config = WealthfolioRestConfig(base_url=BASE_URL, password="s3cret")
        self.client = WealthfolioClient(config)

    def test_get_accounts_parses_bare_array_response(self):
        raw_accounts = [
            {"id": "acc-1", "name": "Broker", "accountType": "SECURITIES",
             "currency": "EUR", "isDefault": True, "isActive": True},
            {"id": "acc-2", "name": "Cash", "accountType": "SECURITIES",
             "currency": "USD", "isDefault": False, "isActive": True},
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=raw_accounts),
        ) as mocked:
            result = self.client.get_accounts()

        mocked.assert_called_once_with("GET", ACCOUNTS_PATH)
        self.assertIsInstance(result, AccountsResult)
        self.assertEqual(result.count, 2)
        self.assertEqual([a.id for a in result.accounts], ["acc-1", "acc-2"])
        self.assertEqual(result.accounts[0].currency, "EUR")
        self.assertTrue(result.accounts[0].is_default)

    def test_create_account_sends_post_with_body_and_parses_response(self):
        response_json = {
            "id": "acc-new", "name": "New Account", "accountType": "SECURITIES",
            "currency": "EUR", "isDefault": False, "isActive": True,
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            account = self.client.create_account(
                name="New Account", accountType="SECURITIES", currency="EUR",
                isDefault=False, isActive=True,
            )

        mocked.assert_called_once_with(
            "POST", ACCOUNTS_PATH,
            json_body={
                "name": "New Account", "accountType": "SECURITIES",
                "currency": "EUR", "isDefault": False, "isActive": True,
            },
        )
        self.assertIsInstance(account, Account)
        self.assertEqual(account.id, "acc-new")
        self.assertEqual(account.account_type, "SECURITIES")

    def test_update_account_sends_put_with_id_and_body(self):
        response_json = {"id": "acc-1", "name": "Renamed", "isActive": False}
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            account = self.client.update_account("acc-1", name="Renamed", isActive=False)

        mocked.assert_called_once_with(
            "PUT", f"{ACCOUNTS_PATH}/acc-1",
            json_body={"name": "Renamed", "isActive": False},
        )
        self.assertEqual(account.name, "Renamed")
        self.assertFalse(account.is_active)

    def test_delete_account_sends_delete_and_returns_none(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(status_code=204),
        ) as mocked:
            result = self.client.delete_account("acc-1")

        mocked.assert_called_once_with("DELETE", f"{ACCOUNTS_PATH}/acc-1")
        self.assertIsNone(result)


class AccountModelParsingTests(unittest.TestCase):
    def test_account_from_dict_missing_and_extra_keys(self):
        account = Account.from_dict({"id": "acc-1", "unexpectedField": "x"})
        self.assertEqual(account.id, "acc-1")
        self.assertIsNone(account.name)
        self.assertIsNone(account.currency)
        self.assertEqual(account.raw, {"id": "acc-1", "unexpectedField": "x"})

    def test_account_from_dict_non_dict_input_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            account = Account.from_dict(bad_input)
            self.assertIsNone(account.id)
            self.assertEqual(account.raw, {})

    def test_accounts_result_from_bare_list(self):
        result = AccountsResult.from_dict([{"id": "a"}, {"id": "b"}, "not-a-dict"])
        self.assertEqual(result.count, 2)
        self.assertEqual([a.id for a in result.accounts], ["a", "b"])

    def test_accounts_result_from_dict_wrapper(self):
        result = AccountsResult.from_dict({"accounts": [{"id": "a"}]})
        self.assertEqual(result.count, 1)
        self.assertEqual(result.accounts[0].id, "a")

    def test_accounts_result_from_non_list_non_dict_does_not_raise(self):
        result = AccountsResult.from_dict(None)
        self.assertEqual(result.accounts, [])
        self.assertEqual(result.count, 0)


def _activity_details_dict(**overrides):
    base = {
        "id": "act-1", "accountId": "acc-1", "assetId": "asset-1",
        "activityType": "FEE", "date": "2026-09-22", "quantity": "0",
        "unitPrice": "0", "currency": "EUR", "fee": "0", "amount": "0",
        "comment": "DAO_PROBE_TEST_COMMIT_20260922 notes_readback_check",
        "metadata": {"host_app": {"schemaVersion": 1}},
    }
    base.update(overrides)
    return base


class WealthfolioClientActivitiesTests(unittest.TestCase):
    """Offline tests for the activities domain methods -- only
    `WealthfolioClient._transport.request` is mocked, never a real network
    call, so no test creates/updates/deletes a real activity."""

    def setUp(self):
        config = WealthfolioRestConfig(base_url=BASE_URL, password="s3cret")
        self.client = WealthfolioClient(config)

    def test_search_activities_parses_data_and_meta(self):
        response_json = {
            "data": [_activity_details_dict()],
            "meta": {"totalRowCount": 1},
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.search_activities(page=1, page_size=50)

        # Public API is 1-indexed (page=1 == first page), but the wire
        # protocol is 0-indexed -- see search_activities' docstring
        # -- so "page": 0 is what must actually be sent.
        mocked.assert_called_once_with(
            "POST", ACTIVITIES_SEARCH_PATH, json_body={"page": 0, "pageSize": 50},
        )
        self.assertIsInstance(result, ActivitiesResult)
        self.assertEqual(result.total_row_count, 1)
        self.assertEqual(result.page, 1)
        self.assertEqual(result.page_size, 50)
        self.assertEqual(len(result.activities), 1)
        activity = result.activities[0]
        self.assertIsInstance(activity, ActivityDetails)
        self.assertEqual(
            activity.comment,
            "DAO_PROBE_TEST_COMMIT_20260922 notes_readback_check",
        )
        self.assertEqual(activity.metadata, {"host_app": {"schemaVersion": 1}})
        self.assertEqual(activity.quantity, 0.0)

    def test_search_activities_forwards_filters_as_given(self):
        response_json = {"data": [], "meta": {"totalRowCount": 0}}
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            self.client.search_activities(
                page=2, page_size=10,
                account_id=["acc-1", "acc-2"], activity_type="BUY",
                asset_id_keyword="NVDA", date_from="2026-01-01",
                date_to="2026-12-31", needs_review=True,
                instrument_type="EQUITY", activity_id="act-1",
                sort={"field": "date", "order": "desc"},
            )

        mocked.assert_called_once_with(
            "POST", ACTIVITIES_SEARCH_PATH,
            json_body={
                "page": 1, "pageSize": 10,
                "accountIdFilter": ["acc-1", "acc-2"], "activityTypeFilter": "BUY",
                "assetIdKeyword": "NVDA", "dateFrom": "2026-01-01",
                "dateTo": "2026-12-31", "needsReviewFilter": True,
                "instrumentTypeFilter": "EQUITY", "activityIdFilter": "act-1",
                "sort": {"field": "date", "order": "desc"},
            },
        )

    def test_iter_activity_pages_walks_pages_and_terminates(self):
        page1 = {
            "data": [_activity_details_dict(id="act-1"), _activity_details_dict(id="act-2")],
            "meta": {"totalRowCount": 3},
        }
        page2 = {"data": [_activity_details_dict(id="act-3")], "meta": {"totalRowCount": 3}}
        responses = [
            _make_json_response(json_data=page1),
            _make_json_response(json_data=page2),
        ]
        with mock.patch.object(
            self.client._transport, "request", side_effect=responses,
        ) as mocked:
            pages = list(self.client.iter_activity_pages(page_size=2))

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(len(pages), 2)
        self.assertEqual([a.id for a in pages[0].activities], ["act-1", "act-2"])
        self.assertEqual([a.id for a in pages[1].activities], ["act-3"])

    def test_iter_activity_pages_terminates_on_empty_page(self):
        empty_page = {"data": [], "meta": {"totalRowCount": 0}}
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=empty_page),
        ) as mocked:
            pages = list(self.client.iter_activity_pages(page_size=50))

        mocked.assert_called_once()
        self.assertEqual(pages, [])

    def test_iter_activities_flattens_pages(self):
        page1 = {
            "data": [_activity_details_dict(id="act-1"), _activity_details_dict(id="act-2")],
            "meta": {"totalRowCount": 2},
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=page1),
        ):
            activities = list(self.client.iter_activities(page_size=2))

        self.assertEqual([a.id for a in activities], ["act-1", "act-2"])

    def test_create_activity_encodes_dict_metadata_and_parses_notes_response(self):
        response_json = {
            "id": "act-new", "accountId": "acc-1", "activityType": "BUY",
            "notes": "hello", "metadata": {"host_app": {"schemaVersion": 1}},
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            activity = self.client.create_activity(
                accountId="acc-1", activityType="BUY", activityDate="2026-09-22",
                currency="EUR", metadata={"host_app": {"schemaVersion": 1}},
            )

        mocked.assert_called_once_with(
            "POST", ACTIVITIES_PATH,
            json_body={
                "accountId": "acc-1", "activityType": "BUY",
                "activityDate": "2026-09-22", "currency": "EUR",
                "metadata": json.dumps({"host_app": {"schemaVersion": 1}}),
            },
        )
        self.assertIsInstance(activity, Activity)
        self.assertEqual(activity.notes, "hello")
        self.assertEqual(activity.metadata, {"host_app": {"schemaVersion": 1}})

    def test_create_activity_leaves_string_metadata_unchanged(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data={"id": "act-new"}),
        ) as mocked:
            self.client.create_activity(
                accountId="acc-1", activityType="BUY",
                metadata="already-a-string",
            )

        mocked.assert_called_once_with(
            "POST", ACTIVITIES_PATH,
            json_body={
                "accountId": "acc-1", "activityType": "BUY",
                "metadata": "already-a-string",
            },
        )

    def test_update_activity_sends_put_to_activities_path_with_id_in_body(self):
        response_json = {"id": "act-1", "notes": "renamed", "metadata": {"a": 1}}
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            activity = self.client.update_activity(
                id="act-1", accountId="acc-1", activityType="BUY",
                metadata={"a": 1},
            )

        mocked.assert_called_once_with(
            "PUT", ACTIVITIES_PATH,
            json_body={
                "id": "act-1", "accountId": "acc-1", "activityType": "BUY",
                "metadata": json.dumps({"a": 1}),
            },
        )
        self.assertEqual(activity.notes, "renamed")
        self.assertEqual(activity.metadata, {"a": 1})

    def test_delete_activity_sends_delete_and_parses_deleted_row(self):
        response_json = {"id": "act-1", "notes": "gone"}
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            activity = self.client.delete_activity("act-1")

        mocked.assert_called_once_with("DELETE", f"{ACTIVITIES_PATH}/act-1")
        self.assertIsInstance(activity, Activity)
        self.assertEqual(activity.id, "act-1")
        self.assertEqual(activity.notes, "gone")

    def test_save_activities_sends_bulk_body_and_encodes_metadata_per_item(self):
        response_json = {
            "created": [{"id": "act-new", "notes": "x"}],
            "updated": [], "deleted": [],
            "createdMappings": [{"tempId": "tmp-1", "activityId": "act-new"}],
            "errors": [],
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.save_activities(
                creates=[{"accountId": "acc-1", "metadata": {"a": 1}}],
                updates=[{"id": "act-2", "metadata": {"b": 2}}],
                delete_ids=["act-3"],
            )

        mocked.assert_called_once_with(
            "POST", ACTIVITIES_BULK_PATH,
            json_body={
                "creates": [{"accountId": "acc-1", "metadata": json.dumps({"a": 1})}],
                "updates": [{"id": "act-2", "metadata": json.dumps({"b": 2})}],
                "deleteIds": ["act-3"],
            },
        )
        self.assertIsInstance(result, ActivityBulkMutationResult)
        self.assertEqual(result.created[0].notes, "x")
        self.assertEqual(result.created_mappings[0].temp_id, "tmp-1")
        self.assertEqual(result.created_mappings[0].activity_id, "act-new")


class ActivityModelParsingTests(unittest.TestCase):
    def test_activity_details_from_dict_parses_comment_and_metadata_object(self):
        activity = ActivityDetails.from_dict(_activity_details_dict())
        self.assertEqual(activity.id, "act-1")
        self.assertEqual(
            activity.comment,
            "DAO_PROBE_TEST_COMMIT_20260922 notes_readback_check",
        )
        self.assertEqual(activity.metadata, {"host_app": {"schemaVersion": 1}})
        self.assertEqual(activity.quantity, 0.0)
        self.assertIsInstance(activity.quantity, float)

    def test_activity_details_from_dict_missing_and_non_dict_input(self):
        activity = ActivityDetails.from_dict({"id": "act-1", "unexpected": "x"})
        self.assertEqual(activity.id, "act-1")
        self.assertIsNone(activity.comment)
        self.assertIsNone(activity.quantity)
        for bad_input in (None, "not a dict", 42, []):
            activity = ActivityDetails.from_dict(bad_input)
            self.assertIsNone(activity.id)
            self.assertEqual(activity.raw, {})

    def test_activity_from_dict_parses_notes_and_metadata_object(self):
        activity = Activity.from_dict(
            {"id": "act-1", "notes": "hi", "metadata": {"x": 1}, "quantity": "3.5"}
        )
        self.assertEqual(activity.notes, "hi")
        self.assertEqual(activity.metadata, {"x": 1})
        self.assertEqual(activity.quantity, 3.5)

    def test_activity_from_dict_non_dict_input_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            activity = Activity.from_dict(bad_input)
            self.assertIsNone(activity.id)
            self.assertEqual(activity.raw, {})

    def test_activities_result_from_dict_missing_meta(self):
        result = ActivitiesResult.from_dict({"data": [{"id": "a"}]})
        self.assertEqual(len(result.activities), 1)
        self.assertIsNone(result.total_row_count)

    def test_activities_result_from_non_dict_input_does_not_raise(self):
        result = ActivitiesResult.from_dict(None)
        self.assertEqual(result.activities, [])
        self.assertIsNone(result.total_row_count)

    def test_activity_bulk_mutation_result_from_dict(self):
        result = ActivityBulkMutationResult.from_dict({
            "created": [{"id": "a"}],
            "updated": [{"id": "b"}],
            "deleted": [{"id": "c"}],
            "createdMappings": [{"tempId": "t1", "activityId": "a"}],
            "errors": [{"id": "x", "action": "update", "message": "boom"}],
        })
        self.assertEqual(result.created[0].id, "a")
        self.assertEqual(result.updated[0].id, "b")
        self.assertEqual(result.deleted[0].id, "c")
        self.assertEqual(result.created_mappings[0].temp_id, "t1")
        self.assertEqual(result.errors[0].message, "boom")

    def test_activity_bulk_mutation_result_from_non_dict_input_does_not_raise(self):
        result = ActivityBulkMutationResult.from_dict(None)
        self.assertEqual(result.created, [])
        self.assertEqual(result.errors, [])


def _holding_dict(**overrides):
    base = {
        "id": "hold-1", "accountId": "acc-1", "holdingType": "SECURITY",
        "isClosed": False, "quantity": "10", "localCurrency": "USD",
        "baseCurrency": "EUR", "marketValue": {"local": "1000", "base": "900"},
        "weight": "0.5", "asOfDate": "2026-09-22",
    }
    base.update(overrides)
    return base


class WealthfolioClientHoldingsPerformanceNetWorthIncomeTests(unittest.TestCase):
    """Offline tests for the holdings/performance/net-worth/income domain
    methods -- only `WealthfolioClient._transport.request` is mocked, never
    a real network call."""

    def setUp(self):
        config = WealthfolioRestConfig(base_url=BASE_URL, password="s3cret")
        self.client = WealthfolioClient(config)

    def test_get_holdings_defaults_to_all_scope(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=[_holding_dict()]),
        ) as mocked:
            result = self.client.get_holdings()

        mocked.assert_called_once_with(
            "POST", HOLDINGS_QUERY_PATH,
            json_body={"filter": {"type": "all"}, "includeClosed": False},
        )
        self.assertIsInstance(result, HoldingsResult)
        self.assertEqual(result.count, 1)
        self.assertIsInstance(result.holdings[0], Holding)
        self.assertEqual(result.holdings[0].market_value.local, 1000.0)
        self.assertEqual(result.holdings[0].market_value.base, 900.0)

    def test_get_holdings_single_account_scope(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=[]),
        ) as mocked:
            self.client.get_holdings(account_id="acc-1", include_closed=True)

        mocked.assert_called_once_with(
            "POST", HOLDINGS_QUERY_PATH,
            json_body={
                "filter": {"type": "account", "accountId": "acc-1"},
                "includeClosed": True,
            },
        )

    def test_get_holdings_rejects_multiple_scope_kwargs(self):
        with self.assertRaises(ValueError):
            self.client.get_holdings(account_id="acc-1", portfolio_id="pf-1")

    def test_get_performance_summary_single_item(self):
        response_json = {
            "scope": {"id": "acc-1", "currency": "EUR"},
            "period": {"startDate": "2026-01-01", "endDate": "2026-09-22"},
            "mode": "timeWeighted",
            "returns": {"twr": "0.05"},
            "attribution": {"contributions": "100"},
            "risk": {"volatility": "0.1"},
            "dataQuality": {"status": "ok", "warnings": [], "notApplicableReasons": []},
            "summary": {"amount": "50", "percent": "0.05", "method": "timeWeighted"},
            "series": [{"date": "2026-01-01", "value": "0"}],
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.get_performance_summary(item_id="acc-1")

        mocked.assert_called_once_with(
            "POST", PERFORMANCE_SUMMARY_PATH,
            json_body={"itemType": "account", "itemId": "acc-1"},
        )
        self.assertIsInstance(result, PerformanceResult)
        self.assertEqual(result.scope.currency, "EUR")
        self.assertEqual(result.returns.twr, 0.05)
        self.assertEqual(result.summary.amount, 50.0)
        self.assertEqual(len(result.series), 1)

    def test_get_performance_summary_account_scope_sends_filter_and_empty_item_id(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data={}),
        ) as mocked:
            self.client.get_performance_summary(
                account_ids=["acc-1", "acc-2"], start_date="2026-01-01", profile="summary",
            )

        mocked.assert_called_once_with(
            "POST", PERFORMANCE_SUMMARY_PATH,
            json_body={
                "itemType": "account", "itemId": "",
                "startDate": "2026-01-01", "profile": "summary",
                "filter": {"type": "accounts", "accountIds": ["acc-1", "acc-2"]},
            },
        )

    def test_get_performance_summary_item_type_symbol_ignores_scope(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data={}),
        ) as mocked:
            self.client.get_performance_summary(item_id="AAPL", item_type="symbol")

        mocked.assert_called_once_with(
            "POST", PERFORMANCE_SUMMARY_PATH,
            json_body={"itemType": "symbol", "itemId": "AAPL"},
        )

    def test_get_performance_history_posts_to_history_path(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data={}),
        ) as mocked:
            result = self.client.get_performance_history(
                item_id="acc-1", start_date="2026-01-01", end_date="2026-09-22",
            )

        mocked.assert_called_once_with(
            "POST", PERFORMANCE_HISTORY_PATH,
            json_body={
                "itemType": "account", "itemId": "acc-1",
                "startDate": "2026-01-01", "endDate": "2026-09-22",
            },
        )
        self.assertIsInstance(result, PerformanceResult)

    def test_get_net_worth_sends_date_query_param(self):
        response_json = {
            "date": "2026-09-22",
            "assets": {"total": "1000", "breakdown": []},
            "liabilities": {"total": "0", "breakdown": []},
            "netWorth": "1000",
            "currency": "EUR",
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.get_net_worth(date="2026-09-22")

        mocked.assert_called_once_with("GET", NET_WORTH_PATH + "?date=2026-09-22")
        self.assertIsInstance(result, NetWorthResult)
        self.assertEqual(result.net_worth, 1000.0)
        self.assertEqual(result.assets.total, 1000.0)

    def test_get_net_worth_omits_query_when_date_absent(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data={}),
        ) as mocked:
            self.client.get_net_worth()

        mocked.assert_called_once_with("GET", NET_WORTH_PATH)

    def test_get_net_worth_history_sends_required_date_range_and_parses_bare_array(self):
        response_json = [
            {"date": "2026-01-01", "portfolioValue": "900", "netWorth": "900"},
            {"date": "2026-02-01", "portfolioValue": "950", "netWorth": "950"},
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            points = self.client.get_net_worth_history("2026-01-01", "2026-02-01")

        mocked.assert_called_once_with(
            "GET", NET_WORTH_HISTORY_PATH + "?startDate=2026-01-01&endDate=2026-02-01",
        )
        self.assertEqual(len(points), 2)
        self.assertIsInstance(points[0], NetWorthHistoryPoint)
        self.assertEqual(points[0].net_worth, 900.0)
        self.assertEqual(points[1].portfolio_value, 950.0)

    def test_get_income_summary_sends_account_id_query_param(self):
        response_json = [{
            "period": "2026", "totalIncome": "500", "currency": "EUR",
            "byMonth": {"2026-01": "500"},
            "byAsset": {"asset-1": {"assetId": "asset-1", "income": "500"}},
        }]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.get_income_summary(account_id="acc-1")

        mocked.assert_called_once_with("GET", INCOME_SUMMARY_PATH + "?accountId=acc-1")
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], IncomeSummary)
        self.assertEqual(result[0].total_income, 500.0)
        self.assertEqual(result[0].by_month, {"2026-01": 500.0})
        self.assertEqual(result[0].by_asset["asset-1"].income, 500.0)

    def test_get_income_summary_omits_query_when_account_id_absent(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=[]),
        ) as mocked:
            self.client.get_income_summary()

        mocked.assert_called_once_with("GET", INCOME_SUMMARY_PATH)

    def test_get_income_summary_query_sends_portfolio_filter(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=[]),
        ) as mocked:
            self.client.get_income_summary_query(portfolio_id="pf-1")

        mocked.assert_called_once_with(
            "POST", INCOME_SUMMARY_QUERY_PATH,
            json_body={"filter": {"type": "portfolio", "portfolioId": "pf-1"}},
        )

    def test_get_income_summary_query_omits_filter_when_no_scope_given(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=[]),
        ) as mocked:
            self.client.get_income_summary_query()

        mocked.assert_called_once_with("POST", INCOME_SUMMARY_QUERY_PATH, json_body={})


class HoldingsPerformanceNetWorthIncomeModelParsingTests(unittest.TestCase):
    def test_holding_from_dict_parses_nested_monetary_values_and_instrument(self):
        holding = Holding.from_dict(_holding_dict(
            instrument={"id": "i-1", "symbol": "AAPL", "currency": "USD"},
            unrealizedGain={"local": "10", "base": "9"},
        ))
        self.assertEqual(holding.quantity, 10.0)
        self.assertEqual(holding.instrument.symbol, "AAPL")
        self.assertEqual(holding.unrealized_gain.local, 10.0)
        self.assertEqual(holding.unrealized_gain.base, 9.0)

    def test_holding_from_dict_non_dict_input_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            holding = Holding.from_dict(bad_input)
            self.assertIsNone(holding.id)
            self.assertIsNone(holding.market_value)
            self.assertEqual(holding.raw, {})

    def test_holdings_result_from_non_list_does_not_raise(self):
        result = HoldingsResult.from_dict(None)
        self.assertEqual(result.holdings, [])
        self.assertEqual(result.count, 0)

    def test_performance_result_from_dict_missing_and_non_dict_input(self):
        result = PerformanceResult.from_dict({"mode": "timeWeighted"})
        self.assertEqual(result.mode, "timeWeighted")
        self.assertIsNone(result.scope)
        self.assertEqual(result.series, [])
        for bad_input in (None, "not a dict", 42, []):
            result = PerformanceResult.from_dict(bad_input)
            self.assertIsNone(result.mode)
            self.assertEqual(result.raw, {})

    def test_net_worth_result_breakdown_children_are_recursive(self):
        result = NetWorthResult.from_dict({
            "date": "2026-09-22", "currency": "EUR", "netWorth": "100",
            "assets": {
                "total": "100",
                "breakdown": [
                    {"category": "cash", "name": "Cash", "value": "100", "children": [
                        {"category": "cash", "name": "Checking", "value": "100"},
                    ]},
                ],
            },
        })
        self.assertEqual(result.assets.breakdown[0].children[0].name, "Checking")
        self.assertEqual(result.assets.breakdown[0].children[0].value, 100.0)

    def test_income_summary_from_non_dict_input_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            summary = IncomeSummary.from_dict(bad_input)
            self.assertIsNone(summary.total_income)
            self.assertEqual(summary.by_month, {})
            self.assertEqual(summary.by_asset, {})


class WealthfolioClientGoalsLimitsHealthPortfoliosTests(unittest.TestCase):
    """Offline tests for the goals/contribution-limits/health/portfolios
    domain methods. Only `WealthfolioClient._transport.request` is mocked
    -- never a real network call."""

    def setUp(self):
        config = WealthfolioRestConfig(base_url=BASE_URL, password="s3cret")
        self.client = WealthfolioClient(config)

    def test_get_goals_parses_bare_array_response(self):
        raw_goals = [
            {
                "id": "goal-1", "goalType": "savings", "title": "Emergency Fund",
                "description": None, "targetAmount": 10000.0,
                "statusLifecycle": "active", "statusHealth": "onTrack",
                "priority": 1, "coverImageKey": None, "currency": "EUR",
                "startDate": "2025-01-01", "targetDate": "2026-12-31",
                "summaryCurrentValue": 4000.0, "summaryProgress": 0.4,
                "projectedCompletionDate": "2026-11-01",
                "projectedValueAtTargetDate": 10500.0,
                "summaryTargetAmount": 10000.0,
                "createdAt": "2025-01-01T00:00:00Z", "updatedAt": "2025-06-01T00:00:00Z",
            },
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=raw_goals),
        ) as mocked:
            result = self.client.get_goals()

        mocked.assert_called_once_with("GET", GOALS_PATH)
        self.assertIsInstance(result, GoalsResult)
        self.assertEqual(result.count, 1)
        self.assertIsInstance(result.goals[0], Goal)
        self.assertEqual(result.goals[0].id, "goal-1")
        self.assertEqual(result.goals[0].goal_type, "savings")
        self.assertEqual(result.goals[0].status_lifecycle, "active")
        self.assertEqual(result.goals[0].summary_progress, 0.4)

    def test_goals_result_from_non_list_does_not_raise(self):
        result = GoalsResult.from_dict(None)
        self.assertEqual(result.goals, [])
        self.assertEqual(result.count, 0)

    def test_get_contribution_limits_parses_bare_array_response(self):
        raw_limits = [
            {
                "id": "limit-1", "groupName": "Retirement", "contributionYear": 2026,
                "limitAmount": 12000.0, "accountIds": "acc-1,acc-2",
                "startDate": "2026-01-01", "endDate": "2026-12-31",
                "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z",
            },
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=raw_limits),
        ) as mocked:
            result = self.client.get_contribution_limits()

        mocked.assert_called_once_with("GET", LIMITS_PATH)
        self.assertIsInstance(result, ContributionLimitsResult)
        self.assertEqual(result.count, 1)
        self.assertIsInstance(result.limits[0], ContributionLimit)
        self.assertEqual(result.limits[0].group_name, "Retirement")
        self.assertEqual(result.limits[0].limit_amount, 12000.0)
        # accountIds is a comma-separated string on the wire, not a list.
        self.assertEqual(result.limits[0].account_ids, "acc-1,acc-2")

    def test_contribution_limits_result_from_non_list_does_not_raise(self):
        result = ContributionLimitsResult.from_dict(None)
        self.assertEqual(result.limits, [])
        self.assertEqual(result.count, 0)

    def test_get_health_status_parses_object_response(self):
        response_json = {
            "overallSeverity": "WARNING",
            "issueCounts": {"WARNING": 2, "ERROR": 0},
            "issues": [
                {
                    "id": "price_stale:AAPL", "severity": "WARNING",
                    "category": "PRICE_STALENESS", "title": "Outdated prices",
                    "message": "Prices are stale", "affectedCount": 1,
                    "affectedMvPct": 0.1, "dataHash": "abc123",
                    "timestamp": "2026-09-22T00:00:00Z",
                },
            ],
            "checkedAt": "2026-09-22T00:00:00Z",
            "isStale": False,
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.get_health_status()

        mocked.assert_called_once_with("GET", HEALTH_STATUS_PATH)
        self.assertIsInstance(result, HealthStatusResult)
        self.assertEqual(result.overall_severity, "WARNING")
        self.assertEqual(result.issue_counts, {"WARNING": 2, "ERROR": 0})
        self.assertFalse(result.is_stale)
        self.assertEqual(len(result.issues), 1)
        self.assertIsInstance(result.issues[0], HealthIssue)
        self.assertEqual(result.issues[0].id, "price_stale:AAPL")
        self.assertEqual(result.issues[0].category, "PRICE_STALENESS")
        self.assertEqual(result.issues[0].affected_count, 1)

    def test_health_status_result_from_non_dict_input_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            result = HealthStatusResult.from_dict(bad_input)
            self.assertIsNone(result.overall_severity)
            self.assertEqual(result.issues, [])
            self.assertEqual(result.raw, {})

    def test_get_portfolios_parses_bare_array_response(self):
        raw_portfolios = [
            {
                "id": "pf-1", "name": "Retirement", "description": None,
                "sortOrder": 0, "accountIds": ["acc-1", "acc-2"],
                "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z",
            },
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=raw_portfolios),
        ) as mocked:
            result = self.client.get_portfolios()

        mocked.assert_called_once_with("GET", PORTFOLIOS_PATH)
        self.assertIsInstance(result, PortfoliosResult)
        self.assertEqual(result.count, 1)
        self.assertIsInstance(result.portfolios[0], Portfolio)
        self.assertEqual(result.portfolios[0].name, "Retirement")
        self.assertEqual(result.portfolios[0].account_ids, ["acc-1", "acc-2"])

    def test_portfolios_result_from_non_list_does_not_raise(self):
        result = PortfoliosResult.from_dict(None)
        self.assertEqual(result.portfolios, [])
        self.assertEqual(result.count, 0)


class WealthfolioClientTaxonomiesTests(unittest.TestCase):
    """Offline tests for the asset-taxonomy domain methods. Only
    `WealthfolioClient._transport.request` is mocked -- never a real
    network call."""

    def setUp(self):
        config = WealthfolioRestConfig(base_url=BASE_URL, password="s3cret")
        self.client = WealthfolioClient(config)

    def test_list_asset_taxonomies_without_id_parses_bare_array(self):
        raw_taxonomies = [
            {
                "id": "tax-1", "name": "Asset Classes", "color": "#8abceb",
                "description": None, "isSystem": True, "isSingleSelect": True,
                "sortOrder": 0, "scope": "asset",
                "createdAt": "2026-01-01T00:00:00", "updatedAt": "2026-01-01T00:00:00",
            },
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=raw_taxonomies),
        ) as mocked:
            result = self.client.list_asset_taxonomies()

        mocked.assert_called_once_with("GET", TAXONOMIES_PATH)
        self.assertIsInstance(result, TaxonomiesResult)
        self.assertEqual(result.count, 1)
        self.assertIsInstance(result.taxonomies[0], Taxonomy)
        self.assertEqual(result.taxonomies[0].name, "Asset Classes")
        self.assertEqual(result.details, [])

    def test_list_asset_taxonomies_filters_by_name_client_side(self):
        raw_taxonomies = [
            {"id": "tax-1", "name": "Asset Classes"},
            {"id": "tax-2", "name": "Industries"},
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=raw_taxonomies),
        ):
            result = self.client.list_asset_taxonomies(taxonomy_name="industries")

        self.assertEqual(result.count, 1)
        self.assertEqual(result.taxonomies[0].id, "tax-2")

    def test_list_asset_taxonomies_with_id_fetches_single_with_categories(self):
        raw_detail = {
            "taxonomy": {"id": "tax-1", "name": "Asset Classes"},
            "categories": [
                {"id": "cat-1", "taxonomyId": "tax-1", "name": "Equities", "key": "equities"},
            ],
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=raw_detail),
        ) as mocked:
            result = self.client.list_asset_taxonomies(taxonomy_id="tax-1")

        mocked.assert_called_once_with("GET", f"{TAXONOMIES_PATH}/tax-1")
        self.assertEqual(result.count, 1)
        self.assertEqual(result.taxonomies[0].id, "tax-1")
        self.assertEqual(len(result.details), 1)
        self.assertIsInstance(result.details[0], TaxonomyWithCategories)
        self.assertEqual(result.details[0].categories[0].key, "equities")

    def test_list_asset_taxonomies_with_id_handles_null_response(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=None),
        ):
            result = self.client.list_asset_taxonomies(taxonomy_id="missing")

        self.assertEqual(result.taxonomies, [])
        self.assertEqual(result.details, [])
        self.assertEqual(result.count, 0)

    def test_list_asset_taxonomies_include_categories_fetches_each_taxonomy(self):
        list_response = _make_json_response(
            json_data=[{"id": "tax-1", "name": "Asset Classes"}, {"id": "tax-2", "name": "Industries"}]
        )
        detail_response_1 = _make_json_response(
            json_data={"taxonomy": {"id": "tax-1", "name": "Asset Classes"}, "categories": []}
        )
        detail_response_2 = _make_json_response(
            json_data={"taxonomy": {"id": "tax-2", "name": "Industries"}, "categories": []}
        )
        with mock.patch.object(
            self.client._transport, "request",
            side_effect=[list_response, detail_response_1, detail_response_2],
        ) as mocked:
            result = self.client.list_asset_taxonomies(include_categories=True)

        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(len(result.details), 2)

    def test_get_asset_taxonomy_assignments_parses_bare_array(self):
        raw_assignments = [
            {
                "id": "asn-1", "assetId": "asset-1", "taxonomyId": "tax-1",
                "categoryId": "cat-1", "weight": 10000, "source": "manual",
                "createdAt": "2026-01-01T00:00:00", "updatedAt": "2026-01-01T00:00:00",
            },
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=raw_assignments),
        ) as mocked:
            result = self.client.get_asset_taxonomy_assignments("asset-1")

        mocked.assert_called_once_with("GET", f"{TAXONOMY_ASSET_ASSIGNMENTS_PATH}/asset-1")
        self.assertIsInstance(result, TaxonomyAssignmentsResult)
        self.assertEqual(result.asset_id, "asset-1")
        self.assertEqual(result.count, 1)
        self.assertIsInstance(result.assignments[0], AssetTaxonomyAssignment)
        self.assertEqual(result.assignments[0].category_id, "cat-1")

    def test_get_asset_taxonomy_assignments_filters_by_taxonomy_id_client_side(self):
        raw_assignments = [
            {"id": "asn-1", "assetId": "asset-1", "taxonomyId": "tax-1", "categoryId": "cat-1"},
            {"id": "asn-2", "assetId": "asset-1", "taxonomyId": "tax-2", "categoryId": "cat-2"},
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=raw_assignments),
        ):
            result = self.client.get_asset_taxonomy_assignments("asset-1", taxonomy_id="tax-2")

        self.assertEqual(result.count, 1)
        self.assertEqual(result.assignments[0].id, "asn-2")

    def test_get_asset_taxonomy_assignments_from_non_list_does_not_raise(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=None),
        ):
            result = self.client.get_asset_taxonomy_assignments("asset-1")

        self.assertEqual(result.assignments, [])
        self.assertEqual(result.count, 0)

    def test_prepare_asset_classification_reads_current_and_echoes_proposed(self):
        current_response = _make_json_response(
            json_data=[
                {"id": "asn-1", "assetId": "asset-1", "taxonomyId": "tax-1", "categoryId": "cat-old"},
            ]
        )
        with mock.patch.object(
            self.client._transport, "request", return_value=current_response,
        ) as mocked:
            result = self.client.prepare_asset_classification(
                "asset-1", "tax-1", [{"category_id": "cat-new"}]
            )

        mocked.assert_called_once_with("GET", f"{TAXONOMY_ASSET_ASSIGNMENTS_PATH}/asset-1")
        self.assertIsInstance(result, PrepareAssetClassificationResult)
        self.assertEqual(result.asset_id, "asset-1")
        self.assertEqual(result.taxonomy_id, "tax-1")
        self.assertEqual(len(result.current_assignments), 1)
        self.assertEqual(result.current_assignments[0].category_id, "cat-old")
        self.assertEqual(len(result.proposed_assignments), 1)
        self.assertIsInstance(result.proposed_assignments[0], AssignmentPreview)
        self.assertEqual(result.proposed_assignments[0].category_id, "cat-new")
        self.assertEqual(result.proposed_assignments[0].weight, 10000)
        self.assertEqual(result.proposed_assignments[0].source, "manual")

    def test_prepare_asset_classification_does_not_mutate(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=[]),
        ) as mocked:
            self.client.prepare_asset_classification("asset-1", "tax-1", [{"category_id": "cat-1"}])

        # Only the read call happens -- never a PUT/POST.
        self.assertEqual(mocked.call_args.args[0], "GET")

    def test_commit_asset_classification_draft_puts_replace_endpoint(self):
        response_json = [
            {"id": "asn-1", "assetId": "asset-1", "taxonomyId": "tax-1", "categoryId": "cat-new", "weight": 10000, "source": "manual"},
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.commit_asset_classification_draft(
                "asset-1", "tax-1", [{"categoryId": "cat-new", "weight": 6000, "source": "rule"}]
            )

        mocked.assert_called_once_with(
            "PUT",
            f"{TAXONOMY_ASSET_ASSIGNMENTS_PATH}/asset-1/taxonomy/tax-1",
            json_body=[
                {"assetId": "asset-1", "taxonomyId": "tax-1", "categoryId": "cat-new", "weight": 6000, "source": "rule"},
            ],
        )
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AssetTaxonomyAssignment)
        self.assertEqual(result[0].category_id, "cat-new")

    def test_commit_asset_classification_draft_defaults_weight_and_source(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=[]),
        ) as mocked:
            self.client.commit_asset_classification_draft("asset-1", "tax-1", [{"category_id": "cat-1"}])

        mocked.assert_called_once_with(
            "PUT",
            f"{TAXONOMY_ASSET_ASSIGNMENTS_PATH}/asset-1/taxonomy/tax-1",
            json_body=[
                {"assetId": "asset-1", "taxonomyId": "tax-1", "categoryId": "cat-1", "weight": 10000, "source": "manual"},
            ],
        )

    def test_commit_asset_classification_draft_from_non_list_response_does_not_raise(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=None),
        ):
            result = self.client.commit_asset_classification_draft("asset-1", "tax-1", [])

        self.assertEqual(result, [])


class WealthfolioClientCategorizationTests(unittest.TestCase):
    """Offline tests for the transaction-categorization domain methods.
    Only `WealthfolioClient._transport.request` is mocked -- never a real
    network call."""

    def setUp(self):
        config = WealthfolioRestConfig(base_url=BASE_URL, password="s3cret")
        self.client = WealthfolioClient(config)

    def test_list_categorization_context_defaults_status_to_uncategorized(self):
        response_json = {
            "items": [
                {
                    "id": "act-1", "accountId": "acc-1", "activityType": "WITHDRAWAL",
                    "activityDate": "2026-09-01", "amount": "42.50", "currency": "EUR",
                    "cashFlowBucket": "spending", "assignments": [], "eventId": None,
                    "netAmount": -42.5, "visibleSpendingAmount": 42.5,
                },
            ],
            "totalCount": 1,
            "net": {"byCurrency": [{"currency": "EUR", "amount": -42.5}], "converted": None},
            "baseCurrency": "EUR",
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.list_categorization_context(account_ids=["acc-1"])

        mocked.assert_called_once_with(
            "POST", SPENDING_CASH_ACTIVITIES_SEARCH_PATH,
            json_body={"accountIds": ["acc-1"], "status": "uncategorized"},
        )
        self.assertIsInstance(result, CashActivitySearchResult)
        self.assertEqual(result.total_count, 1)
        self.assertEqual(result.base_currency, "EUR")
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].activity.id, "act-1")
        self.assertEqual(result.items[0].cash_flow_bucket, "spending")
        self.assertEqual(result.items[0].net_amount, -42.5)
        self.assertEqual(result.net.by_currency[0].amount, -42.5)

    def test_list_categorization_context_honors_explicit_status(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data={}),
        ) as mocked:
            self.client.list_categorization_context(status="all", limit=10, offset=5)

        mocked.assert_called_once_with(
            "POST", SPENDING_CASH_ACTIVITIES_SEARCH_PATH,
            json_body={"status": "all", "offset": 5, "limit": 10},
        )

    def test_cash_activity_search_result_from_non_dict_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            result = CashActivitySearchResult.from_dict(bad_input)
            self.assertEqual(result.items, [])
            self.assertIsNone(result.total_count)

    def test_create_categorization_rule_sends_required_and_optional_fields(self):
        response_json = {
            "id": "rule-1", "name": "Groceries", "pattern": "SUPERMARKET",
            "matchType": "contains", "taxonomyId": "tax-1", "categoryId": "cat-1",
            "priority": 0, "isGlobal": True, "presetModified": False,
            "createdAt": "2026-01-01T00:00:00", "updatedAt": "2026-01-01T00:00:00",
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.create_categorization_rule(
                "Groceries", "SUPERMARKET", taxonomy_id="tax-1", category_id="cat-1",
            )

        mocked.assert_called_once_with(
            "POST", SPENDING_RULES_PATH,
            json_body={
                "name": "Groceries", "pattern": "SUPERMARKET",
                "taxonomyId": "tax-1", "categoryId": "cat-1",
            },
        )
        self.assertIsInstance(result, CategorizationRule)
        self.assertEqual(result.id, "rule-1")
        self.assertEqual(result.match_type, "contains")
        self.assertTrue(result.is_global)

    def test_create_categorization_rule_forwards_amount_condition_fields(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data={}),
        ) as mocked:
            self.client.create_categorization_rule(
                "Big purchases", "*", amount_op="gt", amount_value=500, priority=5, is_global=False,
                account_id="acc-1", activity_type="WITHDRAWAL", match_type="regex",
            )

        mocked.assert_called_once_with(
            "POST", SPENDING_RULES_PATH,
            json_body={
                "name": "Big purchases", "pattern": "*", "matchType": "regex",
                "activityType": "WITHDRAWAL", "amountOp": "gt", "amountValue": 500,
                "priority": 5, "isGlobal": False, "accountId": "acc-1",
            },
        )

    def test_categorization_rule_from_non_dict_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            result = CategorizationRule.from_dict(bad_input)
            self.assertIsNone(result.id)
            self.assertEqual(result.raw, {})

    def test_propose_transaction_categories_not_implemented(self):
        """No REST equivalent exists on `spending.rs` for this MCP-only
        AI-driven tool -- see the docstring above
        `WealthfolioClient.list_categorization_context` in `client.py` for
        the full rationale. Confirms it was deliberately not added rather
        than silently missing."""
        self.assertFalse(hasattr(self.client, "propose_transaction_categories"))


class WealthfolioClientCashBalancesAllocationImportTests(unittest.TestCase):
    """Offline tests for the cash-balances/asset-allocation/activity-import
    domain methods. Only `WealthfolioClient._transport.request` is mocked
    -- never a real network call."""

    def setUp(self):
        config = WealthfolioRestConfig(base_url=BASE_URL, password="s3cret")
        self.client = WealthfolioClient(config)

    # -- get_cash_balances --------------------------------------------------

    def test_get_cash_balances_defaults_to_all_scope(self):
        response_json = {
            "summary": {
                "scopeId": "all", "baseCurrency": "EUR",
                "cashBalanceBase": 1000.0, "investmentMarketValueBase": 9000.0,
                "totalValueBase": 10000.0, "holdingsCount": 3, "accountCount": 2,
                "currencySplit": [{"currency": "EUR", "valueBase": 10000.0, "valueLocal": 10000.0, "percentage": 100.0}],
                "cashCurrencySplit": [{"currency": "EUR", "valueBase": 1000.0, "valueLocal": 1000.0, "percentage": 100.0}],
            },
            "accounts": [],
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.get_cash_balances()

        mocked.assert_called_once_with(
            "POST", VALUATIONS_CURRENT_QUERY_PATH,
            json_body={"filter": {"type": "all"}, "includeAccounts": False},
        )
        self.assertIsInstance(result, CashBalancesResult)
        self.assertEqual(result.summary.cash_balance_base, 1000.0)
        self.assertEqual(len(result.summary.cash_currency_split), 1)
        self.assertEqual(result.summary.cash_currency_split[0].currency, "EUR")
        self.assertEqual(result.accounts, [])

    def test_get_cash_balances_scopes_to_account_and_includes_accounts(self):
        response_json = {
            "summary": {"scopeId": "acc-1", "baseCurrency": "EUR"},
            "accounts": [
                {"accountId": "acc-1", "accountCurrency": "EUR", "cashBalance": 500.0, "cashBalanceBase": 500.0},
            ],
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.get_cash_balances(account_id="acc-1", include_accounts=True)

        mocked.assert_called_once_with(
            "POST", VALUATIONS_CURRENT_QUERY_PATH,
            json_body={
                "filter": {"type": "account", "accountId": "acc-1"},
                "includeAccounts": True,
            },
        )
        self.assertEqual(len(result.accounts), 1)
        self.assertEqual(result.accounts[0].account_id, "acc-1")
        self.assertEqual(result.accounts[0].cash_balance_base, 500.0)

    def test_cash_balances_result_from_non_dict_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            result = CashBalancesResult.from_dict(bad_input)
            self.assertIsNone(result.summary)
            self.assertEqual(result.accounts, [])

    # -- get_asset_allocation ------------------------------------------------

    def test_get_asset_allocation_defaults_to_all_scope(self):
        response_json = {
            "assetClasses": {
                "taxonomyId": "tax-1", "taxonomyName": "Asset Classes",
                "categories": [{"categoryId": "cat-1", "categoryName": "Equity", "value": 8000.0, "percentage": 80.0}],
            },
            "totalValue": 10000.0,
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.get_asset_allocation()

        mocked.assert_called_once_with(
            "POST", ALLOCATIONS_QUERY_PATH,
            json_body={"filter": {"type": "all"}, "includeClosed": False},
        )
        self.assertIsInstance(result, AssetAllocationResult)
        self.assertEqual(result.total_value, 10000.0)
        self.assertEqual(result.asset_classes.taxonomy_name, "Asset Classes")
        self.assertEqual(len(result.asset_classes.categories), 1)
        self.assertEqual(result.asset_classes.categories[0].category_name, "Equity")

    def test_get_asset_allocation_scopes_to_portfolio_and_include_closed(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data={}),
        ) as mocked:
            self.client.get_asset_allocation(portfolio_id="port-1", include_closed=True)

        mocked.assert_called_once_with(
            "POST", ALLOCATIONS_QUERY_PATH,
            json_body={
                "filter": {"type": "portfolio", "portfolioId": "port-1"},
                "includeClosed": True,
            },
        )

    def test_asset_allocation_result_from_non_dict_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            result = AssetAllocationResult.from_dict(bad_input)
            self.assertIsNone(result.asset_classes)
            self.assertIsNone(result.total_value)

    # -- get_import_mapping ---------------------------------------------------

    def test_get_import_mapping_builds_query_string(self):
        response_json = {
            "accountId": "acc-1", "contextKind": "CSV_ACTIVITY",
            "fieldMappings": {"date": "Trade Date"}, "activityMappings": {"BUY": ["Buy", "Purchase"]},
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.get_import_mapping("acc-1")

        mocked.assert_called_once_with(
            "GET", ACTIVITIES_IMPORT_MAPPING_PATH + "?accountId=acc-1"
        )
        self.assertIsInstance(result, ImportMappingResult)
        self.assertEqual(result.account_id, "acc-1")
        self.assertEqual(result.field_mappings["date"], "Trade Date")
        self.assertEqual(result.activity_mappings["BUY"], ["Buy", "Purchase"])

    def test_get_import_mapping_forwards_context_kind(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data={}),
        ) as mocked:
            self.client.get_import_mapping("acc-1", context_kind="CSV_HOLDINGS")

        mocked.assert_called_once_with(
            "GET",
            ACTIVITIES_IMPORT_MAPPING_PATH + "?accountId=acc-1&contextKind=CSV_HOLDINGS",
        )

    def test_import_mapping_result_from_non_dict_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            result = ImportMappingResult.from_dict(bad_input)
            self.assertIsNone(result.account_id)
            self.assertEqual(result.field_mappings, {})

    # -- prepare_activity_import / commit_activity_import --------------------

    def test_prepare_activity_import_posts_check_endpoint(self):
        rows = [{"date": "2026-01-01", "symbol": "AAPL", "activityType": "BUY",
                  "currency": "USD", "isDraft": True, "isValid": True}]
        response_json = [dict(rows[0], lineNumber=1, errors={}, warnings={})]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.prepare_activity_import(rows)

        mocked.assert_called_once_with(
            "POST", ACTIVITIES_IMPORT_CHECK_PATH, json_body={"activities": rows}
        )
        self.assertIsInstance(result, PrepareActivityImportResult)
        self.assertEqual(result.count, 1)
        self.assertIsInstance(result.rows[0], ActivityImportRow)
        self.assertEqual(result.rows[0].symbol, "AAPL")
        self.assertEqual(result.rows[0].line_number, 1)

    def test_prepare_activity_import_result_from_non_list_does_not_raise(self):
        for bad_input in (None, "not a list", 42, {}):
            result = PrepareActivityImportResult.from_dict(bad_input)
            self.assertEqual(result.rows, [])
            self.assertEqual(result.count, 0)

    def test_commit_activity_import_posts_import_endpoint(self):
        rows = [{"date": "2026-01-01", "symbol": "AAPL", "activityType": "BUY",
                  "currency": "USD", "isDraft": False, "isValid": True}]
        response_json = {
            "activities": [dict(rows[0], id="act-1")],
            "importRunId": "run-1",
            "summary": {"total": 1, "imported": 1, "skipped": 0, "duplicates": 0, "success": True},
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.commit_activity_import(rows)

        mocked.assert_called_once_with(
            "POST", ACTIVITIES_IMPORT_PATH, json_body={"activities": rows}
        )
        self.assertIsInstance(result, ImportActivitiesResult)
        self.assertEqual(result.import_run_id, "run-1")
        self.assertEqual(len(result.activities), 1)
        self.assertEqual(result.activities[0].id, "act-1")
        self.assertEqual(result.summary.imported, 1)
        self.assertTrue(result.summary.success)

    def test_import_activities_result_from_non_dict_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            result = ImportActivitiesResult.from_dict(bad_input)
            self.assertEqual(result.activities, [])
            self.assertIsNone(result.import_run_id)
            self.assertIsNone(result.summary)


class WealthfolioClientAssetsTests(unittest.TestCase):
    """Offline tests for the assets domain methods. Only
    `WealthfolioClient._transport.request` is mocked -- never a real
    network call."""

    def setUp(self):
        config = WealthfolioRestConfig(base_url=BASE_URL, password="s3cret")
        self.client = WealthfolioClient(config)

    # -- list_assets ----------------------------------------------------------

    def test_list_assets_parses_bare_array(self):
        response_json = [
            {
                "id": "asset-1", "kind": "INVESTMENT", "name": "NVIDIA Corporation",
                "displayCode": "NVDA", "notes": None, "metadata": None,
                "isActive": True, "quoteMode": "MARKET", "quoteCcy": "USD",
                "instrumentType": "EQUITY", "instrumentSymbol": "NVDA",
                "instrumentExchangeMic": "XNAS", "instrumentKey": "EQUITY:NVDA@XNAS",
                "providerConfig": {"host_app": {"schemaVersion": 1, "sector": "Technology"}},
                "createdAt": "2026-01-01T00:00:00", "updatedAt": "2026-01-01T00:00:00",
            }
        ]
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.list_assets()

        mocked.assert_called_once_with("GET", ASSETS_PATH)
        self.assertIsInstance(result, AssetsResult)
        self.assertEqual(result.count, 1)
        self.assertIsInstance(result.assets[0], Asset)
        self.assertEqual(result.assets[0].instrument_symbol, "NVDA")
        self.assertEqual(
            result.assets[0].provider_config["host_app"]["sector"], "Technology"
        )

    def test_assets_result_from_non_list_does_not_raise(self):
        for bad_input in (None, "not a list", 42, {}):
            result = AssetsResult.from_dict(bad_input)
            self.assertEqual(result.assets, [])
            self.assertEqual(result.count, 0)

    # -- get_asset --------------------------------------------------------------

    def test_get_asset_builds_query_string_and_parses_flattened_profile(self):
        response_json = {
            "id": "asset-1", "kind": "INVESTMENT", "name": "NVIDIA Corporation",
            "displayCode": "NVDA", "quoteMode": "MARKET", "quoteCcy": "USD",
            "instrumentType": "EQUITY", "instrumentSymbol": "NVDA",
            "valuationMarketPrice": 125.5, "valuationMarketCurrency": "USD",
        }
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.get_asset("asset-1")

        mocked.assert_called_once_with("GET", ASSETS_PROFILE_PATH + "?assetId=asset-1")
        self.assertIsInstance(result, AssetProfile)
        self.assertEqual(result.asset.id, "asset-1")
        self.assertEqual(result.asset.instrument_symbol, "NVDA")
        self.assertEqual(result.valuation_market_price, 125.5)
        self.assertEqual(result.valuation_market_currency, "USD")

    def test_asset_profile_from_non_dict_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            result = AssetProfile.from_dict(bad_input)
            self.assertIsNone(result.asset.id)
            self.assertIsNone(result.valuation_market_price)

    # -- create_asset -----------------------------------------------------------

    def test_create_asset_posts_fields_verbatim(self):
        fields = {
            "kind": "INVESTMENT", "name": "NVIDIA Corporation", "displayCode": "NVDA",
            "quoteMode": "MARKET", "quoteCcy": "USD", "instrumentType": "EQUITY",
            "instrumentSymbol": "NVDA",
        }
        response_json = dict(fields, id="asset-1", isActive=True)
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.create_asset(**fields)

        mocked.assert_called_once_with("POST", ASSETS_PATH, json_body=fields)
        self.assertIsInstance(result, Asset)
        self.assertEqual(result.id, "asset-1")
        self.assertEqual(result.instrument_symbol, "NVDA")

    # -- update_asset_profile -----------------------------------------------------

    def test_update_asset_profile_puts_to_profile_id_path(self):
        fields = {"notes": "example asset note", "providerConfig": {"host_app": {"schemaVersion": 1}}}
        response_json = dict(fields, id="asset-1", instrumentSymbol="NVDA")
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(json_data=response_json),
        ) as mocked:
            result = self.client.update_asset_profile("asset-1", **fields)

        mocked.assert_called_once_with(
            "PUT", ASSETS_PROFILE_PATH + "/asset-1", json_body=fields
        )
        self.assertIsInstance(result, Asset)
        self.assertEqual(result.notes, "example asset note")
        self.assertEqual(
            result.provider_config["host_app"]["schemaVersion"], 1
        )

    # -- delete_asset -------------------------------------------------------------

    def test_delete_asset_sends_delete_and_returns_none(self):
        with mock.patch.object(
            self.client._transport, "request",
            return_value=_make_json_response(status_code=204, json_data=None),
        ) as mocked:
            result = self.client.delete_asset("asset-1")

        mocked.assert_called_once_with("DELETE", ASSETS_PATH + "/asset-1")
        self.assertIsNone(result)

    def test_asset_from_non_dict_does_not_raise(self):
        for bad_input in (None, "not a dict", 42, []):
            result = Asset.from_dict(bad_input)
            self.assertIsNone(result.id)
            self.assertIsNone(result.provider_config)


if __name__ == "__main__":
    unittest.main()
