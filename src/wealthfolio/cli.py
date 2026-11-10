"""Generic Wealthfolio REST CLI (``wealthfolio`` console script).

Thin pass-throughs to Wealthfolio's own HTTP API -- see ``client.py``'s
module docstring for the full endpoint list. Most subcommands are
read-only and print the server's own JSON response verbatim; no
calculations happen here. ``accounts-create``/``accounts-update``/
``accounts-delete``, ``asset-create``/``asset-update``/``asset-delete``,
``activities-create``/``activities-update``/``activities-delete``/
``activities-bulk``, and ``classify-commit`` perform real writes, gated
behind an explicit ``--yes`` confirmation flag and a preview of the change
printed first (see each subcommand's own --help).

Configure via the required ``WEALTHFOLIO_PASSWORD`` and
``WEALTHFOLIO_REST_URL`` environment variables, or a ``.env`` file -- see
``wealthfolio/config.py``.

This module is imported both as the standalone ``wealthfolio`` console
script (:func:`main`/:func:`build_parser`) and, subcommand-parser-wiring
only, by a host application that wants to add its own repo-specific
subcommands around the generic ones exposed here via
:func:`register_generic_subparsers_part1`/
:func:`register_generic_subparsers_part2`, so there is a single source of
truth for every generic subcommand's argparse wiring and handler body.
"""
import argparse
import sys


# Optional hook a host application can register to run after every
# successful write made through this CLI -- this package has no cache of
# its own to invalidate, so by default this is a no-op.
_write_hook = None


def set_write_hook(fn):
    """Register a zero-arg callable invoked after every successful write
    made through this CLI (accounts/assets/activities create, update,
    delete, bulk; activity-import commit; holdings-snapshot import).
    Intended for host applications that maintain their own read-through
    cache on top of this generic REST client. Pass ``None`` to clear any
    previously registered hook."""
    global _write_hook
    _write_hook = fn


def _run_write_hook():
    if _write_hook is not None:
        _write_hook()


def _wealthfolio_rest_run(action, invalidate_transactions=False):
    """Shared body for every `wealthfolio-rest` subcommand: opens a
    `wealthfolio.client.WealthfolioClient` (configured via the
    `WEALTHFOLIO_PASSWORD`/`WEALTHFOLIO_REST_URL` environment variables or
    an explicit config -- see `wealthfolio/config.py`), calls
    `action(client)` (expected to return one typed result, or a plain list
    of typed results for the handful of REST endpoints that return a bare
    array), and prints the server's own verbatim JSON (each result's `.raw`
    field) to stdout. No calculations happen here -- these subcommands are
    thin pass-throughs onto Wealthfolio's own HTTP API.

    `invalidate_transactions=True` (set by every subcommand whose `action`
    is a live activity/asset write) runs the write hook registered via
    `set_write_hook` (if any) immediately after `action(client)` succeeds --
    this package has no on-disk cache of its own to invalidate; a host
    application registers one to keep its own read-through cache fresh.
    Skipped on any exception below -- an aborted write leaves nothing new
    to invalidate.

    Any `WealthfolioConfigError` (missing `WEALTHFOLIO_PASSWORD`) or other
    `WealthfolioError` (API failure) is reported as an actionable
    `[wealthfolio-rest]`-tagged stderr message with a non-zero exit --
    never a raw traceback.
    """
    import json
    from wealthfolio.client import WealthfolioClient
    from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError

    try:
        with WealthfolioClient.from_env() as client:
            result = action(client)
            if invalidate_transactions:
                _run_write_hook()
    except WealthfolioConfigError as exc:
        print(f"[wealthfolio-rest] ERROR: {exc}", file=sys.stderr)
        print(
            "[wealthfolio-rest] Set WEALTHFOLIO_PASSWORD (and optionally "
            "WEALTHFOLIO_REST_URL) in the process environment or in a .env "
            "file -- see wealthfolio/config.py.",
            file=sys.stderr,
        )
        sys.exit(1)
    except WealthfolioError as exc:
        print(f"[wealthfolio-rest] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    if isinstance(result, list):
        print(json.dumps([item.raw for item in result], indent=2))
    else:
        print(json.dumps(result.raw, indent=2))


def cmd_wealthfolio_rest_accounts(args):
    """Emit Wealthfolio's account list as JSON via the REST client (read-only pass-through)."""
    _wealthfolio_rest_run(lambda client: client.get_accounts())


# `(argparse dest, camelCase field name)` pairs shared by `accounts-create`
# and `accounts-update` -- the client sends these verbatim with no
# snake_case translation (see `WealthfolioClient.create_account`/
# `update_account`), so the camelCase names here must match the API's own
# `NewAccount`/`AccountUpdate` schemas exactly.
_ACCOUNT_FIELD_ARGS = (
    ("name", "name"),
    ("account_type", "accountType"),
    ("currency", "currency"),
    ("is_default", "isDefault"),
    ("is_active", "isActive"),
    ("group", "group"),
    ("account_number", "accountNumber"),
)


def _account_fields_from_args(args):
    """Build the camelCase `fields` kwargs for `create_account`/
    `update_account` from only the flags the user actually passed --
    unset flags (`None`) are omitted entirely so `accounts-update` never
    clobbers a field the caller didn't mention. `--is-default`/
    `--is-active` are tri-state ("true"/"false"/omitted) so an update can
    explicitly flip either to `False`, not just set it to `True`."""
    fields = {}
    for dest, camel in _ACCOUNT_FIELD_ARGS:
        value = getattr(args, dest, None)
        if value is None:
            continue
        if dest in ("is_default", "is_active"):
            value = value == "true"
        fields[camel] = value
    return fields


# Row-level fields that must be real booleans/floats, not the plain strings
# `csv.DictReader` always hands back -- see `_load_activity_import_rows`.
_ACTIVITY_IMPORT_BOOL_FIELDS = ("isDraft", "isValid")
_ACTIVITY_IMPORT_NUMERIC_FIELDS = ("quantity", "unitPrice", "fee", "tax", "amount")


def _load_activity_import_rows(path, account_id=None):
    """Load a batch of `ActivityImport`-shaped row dicts (camelCase wire
    field names, e.g. `date`/`symbol`/`activityType`/`currency`/`isDraft`/
    `isValid`) for `import-preview`/`import-commit` from `--file`.

    `.json` files (case-insensitive) must contain a bare JSON list of row
    dicts, passed through verbatim. Anything else is read as CSV via
    `csv.DictReader`, whose header row's column names ARE the camelCase
    wire field names -- for each row: empty-string/`None` values are
    dropped (so unset optional fields don't clobber server defaults),
    `isDraft`/`isValid` are coerced to real booleans (there is no
    server-side default for either -- see `WealthfolioClient.
    prepare_activity_import`'s docstring), and `quantity`/`unitPrice`/
    `fee`/`tax`/`amount` are coerced to floats. Every other CSV column
    stays a plain string.

    When `account_id` (the `--account-id` flag) is given and a row has no
    (or falsy) `accountId` of its own, it's filled in from `account_id` so
    the caller doesn't have to repeat it in every row -- a row's own
    explicit `accountId` is never overwritten.

    Any malformed input (missing file, non-list JSON, bad boolean/numeric
    value) is reported as an actionable `[wealthfolio-rest]`-tagged
    stderr message with `sys.exit(1)`, never a raw traceback."""
    import csv
    import json
    from pathlib import Path

    file_path = Path(path)
    if not file_path.exists():
        print(f"[wealthfolio-rest] ERROR: import file not found: {path}", file=sys.stderr)
        sys.exit(1)

    if path.lower().endswith(".json"):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(
                f"[wealthfolio-rest] ERROR: {path} must contain a JSON list of "
                f"activity import row objects, got {type(data).__name__}.",
                file=sys.stderr,
            )
            sys.exit(1)
        rows = list(data)
    else:
        rows = []
        with open(file_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for line_num, raw_row in enumerate(reader, start=1):
                row = {k: v for k, v in raw_row.items() if v not in (None, "")}
                for key in _ACTIVITY_IMPORT_BOOL_FIELDS:
                    if key not in row:
                        continue
                    lowered = str(row[key]).strip().lower()
                    if lowered in ("true", "1", "yes"):
                        row[key] = True
                    elif lowered in ("false", "0", "no"):
                        row[key] = False
                    else:
                        print(
                            f"[wealthfolio-rest] ERROR: row {line_num}: invalid "
                            f"boolean value {row[key]!r} for {key!r} (expected "
                            f"one of true/false/1/0/yes/no).",
                            file=sys.stderr,
                        )
                        sys.exit(1)
                for key in _ACTIVITY_IMPORT_NUMERIC_FIELDS:
                    if key not in row:
                        continue
                    try:
                        row[key] = float(row[key])
                    except ValueError:
                        print(
                            f"[wealthfolio-rest] ERROR: row {line_num}: invalid "
                            f"numeric value {row[key]!r} for {key!r}.",
                            file=sys.stderr,
                        )
                        sys.exit(1)
                rows.append(row)

    if account_id:
        for row in rows:
            if isinstance(row, dict) and not row.get("accountId"):
                row["accountId"] = account_id
    return rows


def cmd_wealthfolio_rest_accounts_create(args):
    """Create a Wealthfolio account via `POST /api/v1/accounts`
    (`WealthfolioClient.create_account`). Defaults to a dry-run preview of
    the camelCase fields that would be sent; only calls `create_account`
    (a real write) when `--yes` is given."""
    import json

    fields = _account_fields_from_args(args)
    if not args.yes:
        print(
            "[wealthfolio-rest accounts-create] Preview (dry-run) -- pass "
            "--yes to actually create this account. Fields to send:"
        )
        print(json.dumps(fields, indent=2))
        return
    _wealthfolio_rest_run(lambda client: client.create_account(**fields))


def cmd_wealthfolio_rest_accounts_update(args):
    """Update a Wealthfolio account via `PUT /api/v1/accounts/{id}`
    (`WealthfolioClient.update_account`). Only forwards fields the caller
    actually passed. Defaults to a dry-run preview; only calls
    `update_account` (a real write) when `--yes` is given."""
    import json

    fields = _account_fields_from_args(args)
    if not fields:
        print(
            "[wealthfolio-rest accounts-update] ERROR: no fields given -- "
            "pass at least one of --name/--account-type/--currency/"
            "--is-default/--is-active/--group/--account-number.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.yes:
        print(
            f"[wealthfolio-rest accounts-update] Preview (dry-run) for "
            f"account {args.account_id!r} -- pass --yes to actually apply "
            f"this update. Fields to send:"
        )
        print(json.dumps(fields, indent=2))
        return
    _wealthfolio_rest_run(lambda client: client.update_account(args.account_id, **fields))


def cmd_wealthfolio_rest_accounts_delete(args):
    """Delete a Wealthfolio account via `DELETE /api/v1/accounts/{id}`
    (`WealthfolioClient.delete_account`). Unlike `accounts-create`/
    `accounts-update`, this always opens a client connection and looks
    up the account first (via `get_accounts()`) so the id/name/currency
    being deleted is printed *before* any confirmation is required --
    the delete call itself only fires when `--yes` is given. There is NO
    undo path: Wealthfolio exposes no restore/rollback for a deleted
    account."""
    import json

    from wealthfolio.client import WealthfolioClient
    from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError

    try:
        with WealthfolioClient.from_env() as client:
            accounts_result = client.get_accounts()
            match = next(
                (a for a in accounts_result.accounts if a.id == args.account_id), None
            )
            if match is None:
                print(
                    f"[wealthfolio-rest accounts-delete] ERROR: no account found "
                    f"with id {args.account_id!r}.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(
                f"[wealthfolio-rest accounts-delete] About to delete account: "
                f"id={match.id!r} name={match.name!r} currency={match.currency!r}"
            )
            if not args.yes:
                print(
                    "[wealthfolio-rest accounts-delete] Pass --yes to actually "
                    "delete this account -- no changes made. There is NO undo "
                    "path once deleted."
                )
                return
            client.delete_account(args.account_id)
    except WealthfolioConfigError as exc:
        print(f"[wealthfolio-rest accounts-delete] ERROR: {exc}", file=sys.stderr)
        print(
            "[wealthfolio-rest accounts-delete] Set WEALTHFOLIO_PASSWORD (and "
            "optionally WEALTHFOLIO_REST_URL) in the process environment or in "
            "a .env file -- see wealthfolio/config.py.",
            file=sys.stderr,
        )
        sys.exit(1)
    except WealthfolioError as exc:
        print(f"[wealthfolio-rest accounts-delete] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(
        {"deleted": True, "id": match.id, "name": match.name, "currency": match.currency},
        indent=2,
    ))


def cmd_wealthfolio_rest_holdings(args):
    """Emit Wealthfolio's holdings as JSON via the REST client (read-only pass-through)."""
    _wealthfolio_rest_run(
        lambda client: client.get_holdings(
            account_id=args.account_id,
            portfolio_id=args.portfolio_id,
            account_ids=args.account_ids,
            include_closed=args.include_closed,
        )
    )


def _load_snapshot_import_rows(path):
    """Load a batch of `HoldingsSnapshotInput`-shaped snapshot dicts (a
    bare JSON list of `{date, positions, cashBalances}` objects) for
    `snapshots-check`/`snapshots-import` from `--file`. Unlike
    `_load_activity_import_rows`, there is no CSV shape defined here --
    each snapshot's `positions` (list) and `cashBalances` (dict) fields
    are nested, not flat columns -- so `--file` must be `.json`
    containing a bare JSON list, passed through verbatim.

    Any malformed input (missing file, non-list JSON) is reported as an
    actionable `[wealthfolio-rest]`-tagged stderr message with
    `sys.exit(1)`, never a raw traceback."""
    import json
    from pathlib import Path

    file_path = Path(path)
    if not file_path.exists():
        print(f"[wealthfolio-rest] ERROR: snapshots file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        print(
            f"[wealthfolio-rest] ERROR: {path} must contain a JSON list of "
            f"holdings snapshot objects ({{date, positions, cashBalances}}), "
            f"got {type(data).__name__}.",
            file=sys.stderr,
        )
        sys.exit(1)
    return list(data)


def cmd_wealthfolio_rest_snapshots(args):
    """Emit Wealthfolio's stored holdings-snapshot metadata as JSON via
    the REST client (read-only pass-through around
    `WealthfolioClient.get_snapshots`). This is metadata only (id, date,
    source, position/cash-currency counts) -- not the actual
    holdings/cash detail for each snapshot."""
    _wealthfolio_rest_run(
        lambda client: client.get_snapshots(
            args.account_id, date_from=args.date_from, date_to=args.date_to
        )
    )


def cmd_wealthfolio_rest_snapshots_check(args):
    """Validate a batch of holdings snapshots loaded from `--file`
    without persisting anything, via `POST /api/v1/snapshots/import/check`
    (`WealthfolioClient.check_holdings_import`). Read-only -- safe to run
    freely. Reports `.existing_dates` (dates that already have a stored
    snapshot -- informational, a real import would overwrite rather than
    error) and per-symbol/date validation status."""
    snapshots = _load_snapshot_import_rows(args.file)
    _wealthfolio_rest_run(
        lambda client: client.check_holdings_import(args.account_id, snapshots)
    )


def cmd_wealthfolio_rest_snapshots_import(args):
    """Persist a batch of holdings snapshots loaded from `--file` via
    `POST /api/v1/snapshots/import` (`WealthfolioClient.
    import_holdings_csv`) -- a live write. Defaults to a dry-run preview
    (via the safe, non-persisting `check_holdings_import`, printing how
    many of the submitted dates already have a stored snapshot and would
    be overwritten); only actually imports with `--yes`."""
    import json

    from wealthfolio.client import WealthfolioClient
    from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError

    snapshots = _load_snapshot_import_rows(args.file)
    if not args.yes:
        try:
            with WealthfolioClient.from_env() as client:
                result = client.check_holdings_import(args.account_id, snapshots)
        except WealthfolioConfigError as exc:
            print(f"[wealthfolio-rest snapshots-import] ERROR: {exc}", file=sys.stderr)
            print(
                "[wealthfolio-rest snapshots-import] Set WEALTHFOLIO_PASSWORD (and "
                "optionally WEALTHFOLIO_REST_URL) in the process environment or "
                "in a .env file -- see wealthfolio/config.py.",
                file=sys.stderr,
            )
            sys.exit(1)
        except WealthfolioError as exc:
            print(f"[wealthfolio-rest snapshots-import] ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print(
            f"[wealthfolio-rest snapshots-import] Preview (dry-run) for "
            f"{len(snapshots)} snapshot(s) -- pass --yes to actually import. "
            f"{len(result.existing_dates)} date(s) already have a stored "
            f"snapshot and would be overwritten: {result.existing_dates}"
        )
        print(json.dumps(result.raw, indent=2))
        return
    _wealthfolio_rest_run(
        lambda client: client.import_holdings_csv(args.account_id, snapshots)
    )


def cmd_wealthfolio_rest_snapshot_delete(args):
    """Delete one holdings snapshot via `DELETE /api/v1/snapshots`
    (`WealthfolioClient.delete_snapshot`) -- a live write, NO undo path.
    Mirrors `accounts-delete`/`asset-delete`: looks up the snapshot first
    (via `get_snapshots()`) so its date/source/id is printed *before* any
    confirmation is required -- the delete call itself only fires when
    `--yes` is given."""
    from wealthfolio.client import WealthfolioClient
    from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError

    try:
        with WealthfolioClient.from_env() as client:
            snapshots_result = client.get_snapshots(args.account_id)
            match = next(
                (s for s in snapshots_result.snapshots if s.snapshot_date == args.date), None
            )
            if match is None:
                print(
                    f"[wealthfolio-rest snapshot-delete] ERROR: no snapshot found "
                    f"for account {args.account_id!r} on date {args.date!r}.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(
                f"[wealthfolio-rest snapshot-delete] About to delete snapshot: "
                f"id={match.id!r} date={match.snapshot_date!r} source={match.source!r}"
            )
            if not args.yes:
                print(
                    "[wealthfolio-rest snapshot-delete] Pass --yes to actually "
                    "delete this snapshot -- no changes made. There is NO undo "
                    "path once deleted."
                )
                return
            client.delete_snapshot(args.account_id, args.date, snapshot_id=match.id)
    except WealthfolioConfigError as exc:
        print(f"[wealthfolio-rest snapshot-delete] ERROR: {exc}", file=sys.stderr)
        print(
            "[wealthfolio-rest snapshot-delete] Set WEALTHFOLIO_PASSWORD (and "
            "optionally WEALTHFOLIO_REST_URL) in the process environment or in "
            "a .env file -- see wealthfolio/config.py.",
            file=sys.stderr,
        )
        sys.exit(1)
    except WealthfolioError as exc:
        print(f"[wealthfolio-rest snapshot-delete] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    import json

    print(json.dumps(
        {"deleted": True, "id": match.id, "date": match.snapshot_date, "source": match.source},
        indent=2,
    ))


def cmd_wealthfolio_rest_cash_balances(args):
    """Emit Wealthfolio's current cash/investment/total valuation as JSON
    via the REST client (read-only pass-through). Pass at most one of
    `--account-id`, `--portfolio-id`, or `--account-ids`; passing none
    scopes to every non-archived account, matching the client's own
    default."""
    _wealthfolio_rest_run(
        lambda client: client.get_cash_balances(
            account_id=args.account_id,
            portfolio_id=args.portfolio_id,
            account_ids=args.account_ids,
            include_accounts=args.include_accounts,
        )
    )


def cmd_wealthfolio_rest_performance(args):
    """Emit Wealthfolio's performance as JSON via the REST client
    (read-only pass-through). Calls `/performance/summary` by default;
    pass `--history` for the full daily series from `/performance/history`
    instead (mirrors `WealthfolioClient.get_performance_summary`/
    `get_performance_history`)."""
    if args.history:
        _wealthfolio_rest_run(
            lambda client: client.get_performance_history(
                item_id=args.item_id,
                item_type=args.item_type,
                account_id=args.account_id,
                portfolio_id=args.portfolio_id,
                account_ids=args.account_ids,
                start_date=args.start_date,
                end_date=args.end_date,
                tracking_mode=args.tracking_mode,
            )
        )
    else:
        _wealthfolio_rest_run(
            lambda client: client.get_performance_summary(
                item_id=args.item_id,
                item_type=args.item_type,
                account_id=args.account_id,
                portfolio_id=args.portfolio_id,
                account_ids=args.account_ids,
                start_date=args.start_date,
                end_date=args.end_date,
                tracking_mode=args.tracking_mode,
                profile=args.profile,
            )
        )


def cmd_wealthfolio_rest_activities(args):
    """Emit Wealthfolio's activity search results as JSON via the REST
    client (read-only pass-through). Unlike the MCP-backed `activities`
    subcommand, there is no `--symbol` filter here -- use
    `--asset-id-keyword` instead (see
    `WealthfolioClient.search_activities`)."""
    optional_kwargs = {}
    if args.page is not None:
        optional_kwargs["page"] = args.page
    if args.page_size is not None:
        optional_kwargs["page_size"] = args.page_size
    _wealthfolio_rest_run(
        lambda client: client.search_activities(
            account_id=args.account_id,
            activity_type=args.activity_type,
            asset_id_keyword=args.asset_id_keyword,
            date_from=args.date_from,
            date_to=args.date_to,
            **optional_kwargs,
        )
    )


def cmd_wealthfolio_rest_net_worth(args):
    """Emit Wealthfolio's net worth as JSON via the REST client
    (read-only pass-through). With `--start-date`, calls the REST
    `/net-worth/history` range endpoint (a plain list of daily points,
    ending at `--date` or today -- local time -- if omitted); without
    `--start-date`, calls the single `/net-worth` snapshot as of `--date`."""
    if args.start_date:
        from datetime import datetime

        end_date = args.date or datetime.now().strftime("%Y-%m-%d")
        _wealthfolio_rest_run(
            lambda client: client.get_net_worth_history(args.start_date, end_date)
        )
    else:
        _wealthfolio_rest_run(lambda client: client.get_net_worth(date=args.date))


def cmd_wealthfolio_rest_allocation(args):
    """Emit Wealthfolio's asset allocation breakdown as JSON via the REST
    client (read-only pass-through). Unlike the MCP-backed `allocation`
    subcommand, there is no `--group-by`/`--taxonomy-id`/`--category-id`
    filter here -- the REST endpoint always returns every breakdown
    (asset class, sector, region, risk category, security type, plus any
    custom taxonomy groups) in one response; filter the JSON output
    client-side instead."""
    _wealthfolio_rest_run(
        lambda client: client.get_asset_allocation(
            account_id=args.account_id,
            portfolio_id=args.portfolio_id,
            account_ids=args.account_ids,
            include_closed=args.include_closed,
        )
    )


def cmd_wealthfolio_rest_income(args):
    """Emit Wealthfolio's income summary as JSON via the REST client
    (read-only pass-through). Unlike the MCP-backed `income` subcommand,
    there is no `--period` filter here (the REST endpoint has no period
    concept); scope with `--account-id`, or with `--portfolio-id`/
    `--account-ids` (either of which takes precedence over `--account-id`
    if both are given)."""
    if args.portfolio_id or args.account_ids:
        _wealthfolio_rest_run(
            lambda client: client.get_income_summary_query(
                portfolio_id=args.portfolio_id, account_ids=args.account_ids
            )
        )
    else:
        _wealthfolio_rest_run(
            lambda client: client.get_income_summary(account_id=args.account_id)
        )


def cmd_wealthfolio_rest_health(args):
    """Emit Wealthfolio's data-health status as JSON via the REST client (read-only pass-through)."""
    _wealthfolio_rest_run(lambda client: client.get_health_status())


def cmd_wealthfolio_rest_goals(args):
    """Emit Wealthfolio's goal list as JSON via the REST client (read-only pass-through)."""
    _wealthfolio_rest_run(lambda client: client.get_goals())


def cmd_wealthfolio_rest_limits(args):
    """Emit Wealthfolio's contribution limit list as JSON via the REST client (read-only pass-through)."""
    _wealthfolio_rest_run(lambda client: client.get_contribution_limits())


def cmd_wealthfolio_rest_portfolios(args):
    """Emit Wealthfolio's saved portfolio list as JSON via the REST client (read-only pass-through)."""
    _wealthfolio_rest_run(lambda client: client.get_portfolios())


def cmd_wealthfolio_rest_taxonomies(args):
    """Emit Wealthfolio's taxonomy list (or one taxonomy's detail, with
    `--taxonomy-id`) as JSON via the REST client (read-only pass-through
    around `WealthfolioClient.list_asset_taxonomies`). `--category-depth`
    is accepted purely for interface parity with the old MCP tool and has
    no server-side effect (see the client method's own docstring); it is
    never sent to any endpoint."""
    _wealthfolio_rest_run(
        lambda client: client.list_asset_taxonomies(
            taxonomy_id=args.taxonomy_id,
            taxonomy_name=args.taxonomy_name,
            include_categories=args.include_categories,
            category_depth=args.category_depth,
        )
    )


def cmd_wealthfolio_rest_taxonomy_assignments(args):
    """Emit one asset's taxonomy assignments as JSON via the REST client
    (read-only pass-through around
    `WealthfolioClient.get_asset_taxonomy_assignments`). `--taxonomy-id`,
    if given, filters the results client-side -- the underlying endpoint
    has no query-parameter filter of its own."""
    _wealthfolio_rest_run(
        lambda client: client.get_asset_taxonomy_assignments(
            args.asset_id, taxonomy_id=args.taxonomy_id
        )
    )


def _parse_classification_assignments(raw_json):
    """Shared `--assignments` JSON parsing for `classify-preview`/
    `classify-commit`: must decode to a `list` of assignment dicts (each
    needing at least `category_id`; `weight`/`source` default server-side
    -- see `WealthfolioClient.commit_asset_classification_draft`'s
    docstring). Prints a `[wealthfolio-rest ...]`-tagged stderr error and
    exits non-zero on invalid JSON or a non-list payload; never raises."""
    import json

    try:
        assignments = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        print(f"[wealthfolio-rest] ERROR: --assignments is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(assignments, list):
        print(
            "[wealthfolio-rest] ERROR: --assignments must be a JSON list of "
            "{\"category_id\": ...} objects.",
            file=sys.stderr,
        )
        sys.exit(1)
    return assignments


def cmd_wealthfolio_rest_classify_preview(args):
    """Non-mutating classification preview as JSON via the REST client
    (read-only pass-through around `WealthfolioClient.prepare_asset_classification`).
    Safe by construction -- that client method makes only a read call and
    echoes `--assignments` back as a local, not-yet-persisted preview, so
    there is no `--yes` gate here. Use `classify-commit` with the same
    `--asset-id`/`--taxonomy-id`/`--assignments` to actually persist them."""
    assignments = _parse_classification_assignments(args.assignments)
    _wealthfolio_rest_run(
        lambda client: client.prepare_asset_classification(
            args.asset_id, args.taxonomy_id, assignments
        )
    )


def cmd_wealthfolio_rest_classify_commit(args):
    """Replace every taxonomy assignment an asset has for one taxonomy via
    the REST client (`WealthfolioClient.commit_asset_classification_draft`
    -- a direct, immediate mutation with no separate server-side commit
    step, unlike the MCP-style draft/commit split). Defaults to a dry-run
    preview of the parsed `--assignments`; only calls
    `commit_asset_classification_draft` (a real write that **replaces**
    every existing assignment for this `asset_id`/`taxonomy_id` pair) when
    `--yes` is given."""
    import json

    assignments = _parse_classification_assignments(args.assignments)
    if not args.yes:
        print(
            "[wealthfolio-rest classify-commit] Preview (dry-run) -- pass "
            "--yes to actually replace assignments. Assignments to send:"
        )
        print(json.dumps(assignments, indent=2))
        return
    _wealthfolio_rest_run(
        lambda client: client.commit_asset_classification_draft(
            args.asset_id, args.taxonomy_id, assignments
        )
    )


def cmd_wealthfolio_rest_categorization_context(args):
    """Emit activities that may need categorization as JSON via the REST
    client (read-only pass-through around
    `WealthfolioClient.list_categorization_context`). `--status` defaults
    to `None` here so the client's own `"uncategorized"` default applies;
    pass `--status all` explicitly to see every activity regardless of
    categorization state. Note: `propose_transaction_categories` (the old
    MCP tool that used an LLM to suggest categories) has no REST
    equivalent and is deliberately NOT implemented as a subcommand here --
    see the comment above `list_categorization_context` in
    `wealthfolio/client.py` for why."""
    _wealthfolio_rest_run(
        lambda client: client.list_categorization_context(
            account_ids=args.account_ids,
            start_date=args.start_date,
            end_date=args.end_date,
            status=args.status,
            limit=args.limit,
            offset=args.offset,
        )
    )


def cmd_wealthfolio_rest_categorization_rule_create(args):
    """Create a saved spending categorization rule via
    `POST /api/v1/spending/rules` (`WealthfolioClient.create_categorization_rule`).
    Unlike the old MCP tool, there is no key-based category lookup --
    resolve a human-friendly category to `--category-id` yourself first
    (e.g. via `taxonomies --taxonomy-id <id> --include-categories`).
    Defaults to a dry-run preview of the fields that would be sent; only
    calls `create_categorization_rule` (a real write) when `--yes` is
    given."""
    import json

    fields = {
        "name": args.name,
        "pattern": args.pattern,
    }
    for dest in (
        "taxonomy_id",
        "category_id",
        "match_type",
        "account_id",
        "activity_type",
        "amount_op",
        "amount_value",
        "amount_value2",
        "priority",
        "is_global",
    ):
        value = getattr(args, dest, None)
        if value is None:
            continue
        fields[dest] = value
    if not args.yes:
        print(
            "[wealthfolio-rest categorization-rule-create] Preview (dry-run) -- pass "
            "--yes to actually create this rule. Fields to send:"
        )
        print(json.dumps(fields, indent=2))
        return
    _wealthfolio_rest_run(lambda client: client.create_categorization_rule(**fields))


def cmd_wealthfolio_rest_import_mapping(args):
    """Fetch a saved Wealthfolio import-mapping template via
    `GET /api/v1/activities/import/mapping`
    (`WealthfolioClient.get_import_mapping`, read-only pass-through).
    `--context-kind` defaults to `None` so the server's own
    `"CSV_ACTIVITY"` default applies; `"CSV_HOLDINGS"` is the only other
    real value, for the separate holdings-snapshot import flow this repo
    does not implement. This is the generic Wealthfolio-native
    CSV-import-mapping surface."""
    _wealthfolio_rest_run(
        lambda client: client.get_import_mapping(
            account_id=args.account_id, context_kind=args.context_kind
        )
    )


def _print_activity_import_row_preview(rows):
    """Print one human-readable summary line per `ActivityImportRow`
    returned by `prepare_activity_import`/`commit_activity_import` --
    shared by `import-preview` and `import-commit`'s dry-run path so the
    two subcommands don't duplicate this formatting."""
    for i, row in enumerate(rows):
        errors = row.errors if row.errors else "none"
        warnings = row.warnings if row.warnings else "none"
        duplicate_of = row.duplicate_of_id if row.duplicate_of_id else "none"
        print(
            f"row {i}: symbol={row.symbol} date={row.date} "
            f"type={row.activity_type} valid={row.is_valid} "
            f"errors={errors} warnings={warnings} duplicate_of={duplicate_of}"
        )


def cmd_wealthfolio_rest_import_preview(args):
    """Validate/dedup a batch of `ActivityImport` rows loaded from
    `--file` without persisting anything, via
    `POST /api/v1/activities/import/check`
    (`WealthfolioClient.prepare_activity_import`). This is the generic
    Wealthfolio-native bulk-import-check surface -- raw rows, no account
    transformation beyond the server's own validation.

    Prints a human-readable per-row summary (reusing
    `_print_activity_import_row_preview`) before the existing `.raw` JSON
    dump `_wealthfolio_rest_run` already prints, so users can decide
    whether to proceed without parsing JSON themselves."""
    rows = _load_activity_import_rows(args.file, account_id=args.account_id)

    def action(client):
        result = client.prepare_activity_import(activities=rows)
        _print_activity_import_row_preview(result.rows)
        return result

    _wealthfolio_rest_run(action)


def cmd_wealthfolio_rest_import_commit(args):
    """Bulk-import a batch of `ActivityImport` rows loaded from `--file`
    into Wealthfolio via `POST /api/v1/activities/import`
    (`WealthfolioClient.commit_activity_import`) -- a real, persisting
    write. This is the generic Wealthfolio-native bulk-import surface --
    raw rows, no transformation beyond the server's own import handling.

    Defaults to a dry-run preview (via the safe, non-persisting
    `prepare_activity_import` check -- `commit_activity_import` is never
    called in this branch) -- pass `--yes` to actually call
    `commit_activity_import` and persist the rows."""
    rows = _load_activity_import_rows(args.file, account_id=args.account_id)

    if not args.yes:
        from wealthfolio.client import WealthfolioClient
        from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError

        try:
            with WealthfolioClient.from_env() as client:
                result = client.prepare_activity_import(activities=rows)
        except WealthfolioConfigError as exc:
            print(f"[wealthfolio-rest import-commit] ERROR: {exc}", file=sys.stderr)
            print(
                "[wealthfolio-rest import-commit] Set WEALTHFOLIO_PASSWORD (and "
                "optionally WEALTHFOLIO_REST_URL) in the process environment or "
                "in a .env file -- see wealthfolio/config.py.",
                file=sys.stderr,
            )
            sys.exit(1)
        except WealthfolioError as exc:
            print(f"[wealthfolio-rest import-commit] ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print(
            "[wealthfolio-rest import-commit] Preview (dry-run) -- pass --yes to "
            "actually commit this import. Rows to send:"
        )
        _print_activity_import_row_preview(result.rows)
        return

    _wealthfolio_rest_run(
        lambda client: client.commit_activity_import(activities=rows),
        invalidate_transactions=True,
    )


def _load_json_arg(value, flag_name="the JSON argument"):
    """Parse a `--metadata-json`/`--provider-config-json`-style CLI value
    for `asset-create`/`asset-update`. `None` (flag not passed) passes
    through unchanged. Otherwise, if `value` names an existing filesystem
    path, its contents are `json.load`ed; any other string is parsed as
    inline JSON text via `json.loads`. A malformed-JSON or unreadable-file
    error is reported as an actionable, `flag_name`-tagged stderr message
    naming the bad value, followed by `sys.exit(1)` -- never a raw
    traceback."""
    import json
    from pathlib import Path

    if value is None:
        return None
    try:
        path = Path(value)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return json.loads(value)
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"[wealthfolio-rest] ERROR: invalid JSON for {flag_name} "
            f"({value!r}): {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


# `(argparse dest, camelCase field name)` pairs shared by `asset-create`
# and `asset-update` -- the client sends these verbatim with no
# snake_case translation (see `WealthfolioClient.create_asset`/
# `update_asset_profile`), so the camelCase names here must match the
# API's own `NewAsset`/`UpdateAssetProfile` schemas exactly. `metadata`/
# `providerConfig` are handled separately via `--metadata-json`/
# `--provider-config-json` (see `_asset_fields_from_args`), not listed
# here, since they need JSON parsing rather than a plain string value.
_ASSET_FIELD_ARGS = (
    ("kind", "kind"),
    ("name", "name"),
    ("display_code", "displayCode"),
    ("quote_mode", "quoteMode"),
    ("quote_ccy", "quoteCcy"),
    ("instrument_type", "instrumentType"),
    ("instrument_symbol", "instrumentSymbol"),
    ("instrument_exchange_mic", "instrumentExchangeMic"),
    ("notes", "notes"),
)

# camelCase field name -> `Asset` dataclass attribute name, covering every
# field `update_asset_profile` accepts (the `_ASSET_FIELD_ARGS` pairs plus
# `metadata`/`providerConfig`, which take a separate JSON-loading path in
# `_asset_fields_from_args`). Used by `cmd_wealthfolio_rest_asset_update`'s
# fetch-then-merge: `PUT /api/v1/assets/profile/{id}` is a full replacement
# on the wire, not a per-field patch -- omitting ANY field resets it to
# null (confirmed in practice for `name`, `providerConfig`, and `quoteCcy`,
# not just `notes`), so every field not explicitly passed must be
# refilled from the asset's current value before sending.
_ASSET_FIELD_TO_ATTR = {camel: dest for dest, camel in _ASSET_FIELD_ARGS}
_ASSET_FIELD_TO_ATTR["metadata"] = "metadata"
_ASSET_FIELD_TO_ATTR["providerConfig"] = "provider_config"


def _asset_fields_from_args(args):
    """Build the camelCase `fields` kwargs for `create_asset`/
    `update_asset_profile` from only the flags the user actually passed --
    unset flags (`None`) are omitted entirely, same "unset flags are
    omitted" pattern as `_account_fields_from_args`. `--metadata-json`/
    `--provider-config-json` are loaded via `_load_json_arg` and mapped to
    `metadata`/`providerConfig`. Note: `asset-update`'s special-case
    handling of `notes` (defaulting it from the asset's current value when
    `--notes` is omitted) happens in `cmd_wealthfolio_rest_asset_update`,
    on top of this helper's result -- this helper only forwards `notes`
    when the caller actually passed `--notes`."""
    fields = {}
    for dest, camel in _ASSET_FIELD_ARGS:
        value = getattr(args, dest, None)
        if value is None:
            continue
        fields[camel] = value
    metadata = _load_json_arg(getattr(args, "metadata_json", None), flag_name="--metadata-json")
    if metadata is not None:
        fields["metadata"] = metadata
    provider_config = _load_json_arg(
        getattr(args, "provider_config_json", None), flag_name="--provider-config-json"
    )
    if provider_config is not None:
        fields["providerConfig"] = provider_config
    return fields


def cmd_wealthfolio_rest_assets(args):
    """Emit Wealthfolio's asset list as JSON via the REST client (read-only pass-through)."""
    _wealthfolio_rest_run(lambda client: client.list_assets())


def cmd_wealthfolio_rest_asset(args):
    """Emit one Wealthfolio asset's full profile (including its complete
    `notes`/`metadata`, not a truncated/summarized view) as JSON via the
    REST client (read-only pass-through)."""
    _wealthfolio_rest_run(lambda client: client.get_asset(args.asset_id))


def cmd_wealthfolio_rest_asset_create(args):
    """Create a Wealthfolio asset via `POST /api/v1/assets`
    (`WealthfolioClient.create_asset`). This is a direct one-shot write
    with no server-side draft/preview step (see the module comment above
    `WealthfolioClient.list_assets`), but per this epic's confirm-gate
    convention -- same as `accounts-create`, also a direct one-shot write
    -- it still defaults to a dry-run preview of the camelCase fields
    that would be sent, and only calls `create_asset` (a real write) when
    `--yes` is given. `--kind`/`--quote-ccy` are required flags: the wire
    schema has no server-side default for either, and omitting one raises
    a 4xx from the server."""
    import json

    fields = _asset_fields_from_args(args)
    if not args.yes:
        print(
            "[wealthfolio-rest asset-create] Preview (dry-run) -- pass "
            "--yes to actually create this asset. Fields to send:"
        )
        print(json.dumps(fields, indent=2))
        return
    _wealthfolio_rest_run(lambda client: client.create_asset(**fields), invalidate_transactions=True)


def cmd_wealthfolio_rest_asset_update(args):
    """Update a Wealthfolio asset's profile via `PUT
    /api/v1/assets/profile/{id}` (`WealthfolioClient.update_asset_profile`).
    **This endpoint is a full replacement on the wire, not a per-field
    patch**: any field missing from the JSON body is reset to null/its
    default by the server -- confirmed in practice for `name`,
    `providerConfig`, and `quoteCcy`, not only the `notes` field the wire
    schema marks as a required `String`. To make an update never
    accidentally clobber fields the caller didn't mention, this always
    fetches the asset's *current* profile first (via `get_asset`) and
    fills in every field not explicitly passed with its current value
    (`""` for `notes` specifically, since it can't be sent as null) --
    only the flags the caller actually passed end up changing. Defaults
    to a dry-run preview; only calls `update_asset_profile` (a real
    write) when `--yes` is given."""
    import json

    from wealthfolio.client import WealthfolioClient
    from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError

    fields = _asset_fields_from_args(args)
    try:
        with WealthfolioClient.from_env() as client:
            profile = client.get_asset(args.asset_id)
    except WealthfolioConfigError as exc:
        print(f"[wealthfolio-rest asset-update] ERROR: {exc}", file=sys.stderr)
        print(
            "[wealthfolio-rest asset-update] Set WEALTHFOLIO_PASSWORD (and "
            "optionally WEALTHFOLIO_REST_URL) in the process environment or "
            "in a .env file -- see wealthfolio/config.py.",
            file=sys.stderr,
        )
        sys.exit(1)
    except WealthfolioError as exc:
        print(f"[wealthfolio-rest asset-update] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    current = profile.asset
    for camel, attr in _ASSET_FIELD_TO_ATTR.items():
        if camel in fields:
            continue
        current_value = getattr(current, attr, None) if current else None
        if camel == "notes" and current_value is None:
            current_value = ""
        fields[camel] = current_value
    if not args.yes:
        print(
            f"[wealthfolio-rest asset-update] Preview (dry-run) for asset "
            f"{args.asset_id!r} -- pass --yes to actually apply this update. "
            f"Fields to send:"
        )
        print(json.dumps(fields, indent=2))
        return
    _wealthfolio_rest_run(
        lambda client: client.update_asset_profile(args.asset_id, **fields),
        invalidate_transactions=True,
    )


def cmd_wealthfolio_rest_asset_delete(args):
    """Delete a Wealthfolio asset via `DELETE /api/v1/assets/{id}`
    (`WealthfolioClient.delete_asset`). Mirrors `accounts-delete`: always
    opens a client connection and looks up the asset first (via
    `get_asset`) so its id/name/kind are printed *before* any
    confirmation is required -- the delete call itself only fires when
    `--yes` is given. `delete_asset` returns `None` (204 No Content), so
    the confirmation JSON printed afterward is built from the looked-up
    asset, not from the delete call's own (nonexistent) result. There is
    NO undo path: Wealthfolio exposes no restore/rollback for a deleted
    asset."""
    import json

    from wealthfolio.client import WealthfolioClient
    from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError

    try:
        with WealthfolioClient.from_env() as client:
            profile = client.get_asset(args.asset_id)
            match = profile.asset
            print(
                f"[wealthfolio-rest asset-delete] About to delete asset: "
                f"id={match.id!r} name={match.name!r} kind={match.kind!r}"
            )
            if not args.yes:
                print(
                    "[wealthfolio-rest asset-delete] Pass --yes to actually "
                    "delete this asset -- no changes made. There is NO undo "
                    "path once deleted."
                )
                return
            client.delete_asset(args.asset_id)
            _run_write_hook()
    except WealthfolioConfigError as exc:
        print(f"[wealthfolio-rest asset-delete] ERROR: {exc}", file=sys.stderr)
        print(
            "[wealthfolio-rest asset-delete] Set WEALTHFOLIO_PASSWORD (and "
            "optionally WEALTHFOLIO_REST_URL) in the process environment or in "
            "a .env file -- see wealthfolio/config.py.",
            file=sys.stderr,
        )
        sys.exit(1)
    except WealthfolioError as exc:
        print(f"[wealthfolio-rest asset-delete] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"deleted": True, "id": match.id, "name": match.name}, indent=2))


# `(argparse dest, camelCase field name)` pairs shared by `activities-create`
# and `activities-update` -- the client sends these verbatim with no


# snake_case translation (see `WealthfolioClient.create_activity`/
# `update_activity`), so the camelCase names here must match the API's own
# `NewActivity`/`ActivityUpdate` schemas exactly. `--asset-id` (-> the
# nested `symbol` object) and `--metadata-json` (-> `metadata`) are handled
# separately in `_activity_fields_from_args`, not listed here.
_ACTIVITY_FIELD_ARGS = (
    ("account_id", "accountId"),
    ("activity_type", "activityType"),
    ("activity_date", "activityDate"),
    ("quantity", "quantity"),
    ("unit_price", "unitPrice"),
    ("currency", "currency"),
    ("fee", "fee"),
    ("tax", "tax"),
    ("notes", "notes"),
)

# The full-replace field set `update_activity` requires on every call (see
# its docstring in `client.py`) -- `activities-update` fetches-and-merges
# any of these missing from the flags the caller actually passed.
_ACTIVITY_UPDATE_REQUIRED_CAMEL = (
    "accountId", "activityType", "activityDate", "quantity", "unitPrice", "currency", "fee",
)


def _activity_fields_from_args(args):
    """Build the camelCase `fields` kwargs for `create_activity`/
    `update_activity` from only the flags the user actually passed --
    unset flags (`None`) are omitted entirely, same "unset flags are
    omitted" pattern as `_account_fields_from_args`/`_asset_fields_from_args`.
    `--asset-id` is translated to the nested `symbol={"id": ...}` object
    the wire schema expects (NOT a top-level `assetId` string -- see
    `WealthfolioClient.create_activity`'s docstring). `--metadata-json` is
    loaded via `_load_json_arg` and mapped to `metadata`."""
    fields = {}
    for dest, camel in _ACTIVITY_FIELD_ARGS:
        value = getattr(args, dest, None)
        if value is None:
            continue
        fields[camel] = value
    asset_id = getattr(args, "asset_id", None)
    if asset_id is not None:
        fields["symbol"] = {"id": asset_id}
    metadata = _load_json_arg(getattr(args, "metadata_json", None), flag_name="--metadata-json")
    if metadata is not None:
        fields["metadata"] = metadata
    return fields


def cmd_wealthfolio_rest_activities_create(args):
    """Create an activity via `POST /api/v1/activities`
    (`WealthfolioClient.create_activity`) -- a live write, no draft/commit
    step. Defaults to a dry-run preview of the camelCase fields that would
    be sent (including the `--asset-id` -> nested `symbol={"id": ...}`
    translation); only calls `create_activity` when `--yes` is given."""
    import json

    fields = _activity_fields_from_args(args)
    if not args.yes:
        print(
            "[wealthfolio-rest activities-create] Preview (dry-run) -- pass "
            "--yes to actually create this activity. Fields to send:"
        )
        print(json.dumps(fields, indent=2))
        return
    _wealthfolio_rest_run(lambda client: client.create_activity(**fields), invalidate_transactions=True)


def cmd_wealthfolio_rest_activities_update(args):
    """Update an activity via `PUT /api/v1/activities`
    (`WealthfolioClient.update_activity`) -- a live, full-replace write
    (not a patch): the wire's `ActivityUpdate` requires `accountId`/
    `activityType`/`activityDate`/`symbol`/`quantity`/`unitPrice`/
    `currency`/`fee` on every call. There is no singular `get_activity`
    endpoint, so any of those fields NOT explicitly passed as a flag is
    defaulted from the activity's current value, fetched via
    `search_activities(activity_id=[...])` (the closest equivalent) --
    same "never clobber by omission" reasoning as `asset-update`'s
    `--notes` handling, generalized to every required field here. Defaults
    to a dry-run preview; only calls `update_activity` (a real write) when
    `--yes` is given."""
    import json

    from wealthfolio.client import WealthfolioClient
    from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError

    fields = _activity_fields_from_args(args)
    fields["id"] = args.activity_id

    needs_lookup = "symbol" not in fields or any(
        camel not in fields for camel in _ACTIVITY_UPDATE_REQUIRED_CAMEL
    )
    if needs_lookup:
        try:
            with WealthfolioClient.from_env() as client:
                result = client.search_activities(activity_id=[args.activity_id])
        except WealthfolioConfigError as exc:
            print(f"[wealthfolio-rest activities-update] ERROR: {exc}", file=sys.stderr)
            print(
                "[wealthfolio-rest activities-update] Set WEALTHFOLIO_PASSWORD (and "
                "optionally WEALTHFOLIO_REST_URL) in the process environment or in "
                "a .env file -- see wealthfolio/config.py.",
                file=sys.stderr,
            )
            sys.exit(1)
        except WealthfolioError as exc:
            print(f"[wealthfolio-rest activities-update] ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        current = next((a for a in result.activities if a.id == args.activity_id), None)
        if current is None:
            print(
                f"[wealthfolio-rest activities-update] ERROR: no activity found "
                f"with id {args.activity_id!r}.",
                file=sys.stderr,
            )
            sys.exit(1)
        fields.setdefault("accountId", current.account_id)
        fields.setdefault("activityType", current.activity_type)
        fields.setdefault("activityDate", current.date)
        fields.setdefault("quantity", current.quantity)
        fields.setdefault("unitPrice", current.unit_price)
        fields.setdefault("currency", current.currency)
        fields.setdefault("fee", current.fee)
        fields.setdefault("tax", current.tax)
        fields.setdefault("notes", current.comment)
        if "symbol" not in fields and current.asset_id:
            fields["symbol"] = {"id": current.asset_id}

    if not args.yes:
        print(
            f"[wealthfolio-rest activities-update] Preview (dry-run) for activity "
            f"{args.activity_id!r} -- pass --yes to actually apply this update. "
            f"Fields to send:"
        )
        print(json.dumps(fields, indent=2))
        return
    _wealthfolio_rest_run(lambda client: client.update_activity(**fields), invalidate_transactions=True)


def cmd_wealthfolio_rest_activities_delete(args):
    """Delete an activity via `DELETE /api/v1/activities/{id}`
    (`WealthfolioClient.delete_activity`) -- a live write, NO undo path.
    Mirrors `accounts-delete`: always opens a client connection and looks
    up the activity first (via `search_activities(activity_id=[...])`,
    the closest equivalent to a singular get) so its id/type/date/account
    are printed *before* any confirmation is required -- the delete call
    itself only fires when `--yes` is given. Unlike `delete_account`,
    `delete_activity` returns the deleted `Activity` row (not `204`), so
    that response's own `.raw` is what's printed on a confirmed delete."""
    import json

    from wealthfolio.client import WealthfolioClient
    from wealthfolio.exceptions import WealthfolioConfigError, WealthfolioError

    try:
        with WealthfolioClient.from_env() as client:
            result = client.search_activities(activity_id=[args.activity_id])
            match = next((a for a in result.activities if a.id == args.activity_id), None)
            if match is None:
                print(
                    f"[wealthfolio-rest activities-delete] ERROR: no activity found "
                    f"with id {args.activity_id!r}.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(
                f"[wealthfolio-rest activities-delete] About to delete activity: "
                f"id={match.id!r} type={match.activity_type!r} date={match.date!r} "
                f"account_id={match.account_id!r}"
            )
            if not args.yes:
                print(
                    "[wealthfolio-rest activities-delete] Pass --yes to actually "
                    "delete this activity -- no changes made. There is NO undo "
                    "path once deleted."
                )
                return
            deleted = client.delete_activity(args.activity_id)
            _run_write_hook()
    except WealthfolioConfigError as exc:
        print(f"[wealthfolio-rest activities-delete] ERROR: {exc}", file=sys.stderr)
        print(
            "[wealthfolio-rest activities-delete] Set WEALTHFOLIO_PASSWORD (and "
            "optionally WEALTHFOLIO_REST_URL) in the process environment or in "
            "a .env file -- see wealthfolio/config.py.",
            file=sys.stderr,
        )
        sys.exit(1)
    except WealthfolioError as exc:
        print(f"[wealthfolio-rest activities-delete] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(deleted.raw, indent=2))


def cmd_wealthfolio_rest_activities_bulk(args):
    """Create/update/delete many activities in one call via `POST
    /api/v1/activities/bulk` (`WealthfolioClient.save_activities`) -- a
    live write; a per-item failure lands in the result's `errors` list
    rather than aborting the whole batch. `--creates-json`/`--updates-json`
    (each a JSON list of camelCase field dicts, same shape as
    `activities-create`/`activities-update`, loaded via `_load_json_arg`)
    and `--delete-ids` (repeatable, and/or a comma-separated value per
    occurrence) build the batch. Defaults to a dry-run preview of the
    batch; only calls `save_activities` (a real write) when `--yes` is
    given -- the printed result on a confirmed run includes any per-item
    `errors` verbatim."""
    import json

    creates = _load_json_arg(args.creates_json, flag_name="--creates-json") or []
    updates = _load_json_arg(args.updates_json, flag_name="--updates-json") or []
    if not isinstance(creates, list):
        print(
            f"[wealthfolio-rest activities-bulk] ERROR: --creates-json must be a "
            f"JSON list, got {type(creates).__name__}.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(updates, list):
        print(
            f"[wealthfolio-rest activities-bulk] ERROR: --updates-json must be a "
            f"JSON list, got {type(updates).__name__}.",
            file=sys.stderr,
        )
        sys.exit(1)

    delete_ids = []
    for raw in (args.delete_ids or []):
        delete_ids.extend(part.strip() for part in raw.split(",") if part.strip())

    if not args.yes:
        print(
            "[wealthfolio-rest activities-bulk] Preview (dry-run) -- pass --yes "
            "to actually submit this batch. Batch to send:"
        )
        print(json.dumps(
            {"creates": creates, "updates": updates, "deleteIds": delete_ids}, indent=2,
        ))
        return
    _wealthfolio_rest_run(
        lambda client: client.save_activities(
            creates=creates, updates=updates, delete_ids=delete_ids
        ),
        invalidate_transactions=True,
    )


def _register_accounts(sub):
    wfr_accounts_parser = sub.add_parser("accounts", help="List accounts (JSON)")
    wfr_accounts_parser.set_defaults(func=cmd_wealthfolio_rest_accounts)

    def _add_account_field_args(parser, name_required=False):
        parser.add_argument("--name", default=None, required=name_required,
                             help="Account display name" + (" (required)" if name_required else ""))
        parser.add_argument("--account-type", default=None, dest="account_type",
                             help="e.g. SECURITIES, CASH, CRYPTOCURRENCY")
        parser.add_argument("--currency", default=None, help="ISO currency code, e.g. EUR/USD")
        parser.add_argument("--is-default", default=None, dest="is_default", choices=["true", "false"],
                             help="Mark/unmark this account as the default account")
        parser.add_argument("--is-active", default=None, dest="is_active", choices=["true", "false"],
                             help="Mark/unmark this account as active")
        parser.add_argument("--group", default=None, help="Free-form account group/category label")
        parser.add_argument("--account-number", default=None, dest="account_number",
                             help="External account number, e.g. from a broker statement")

    wfr_accounts_create_parser = sub.add_parser(
        "accounts-create",
        help="Create an account (write; requires --yes)",
        description=(
            "Create a Wealthfolio account via POST /api/v1/accounts "
            "(WealthfolioClient.create_account). Without --yes, prints a "
            "preview of the camelCase fields that would be sent and makes "
            "no write. Pass --yes to actually create the account."
        ),
    )
    _add_account_field_args(wfr_accounts_create_parser, name_required=True)
    wfr_accounts_create_parser.add_argument(
        "--yes", action="store_true", help="Confirm the write; without this, only a preview is printed")
    wfr_accounts_create_parser.set_defaults(func=cmd_wealthfolio_rest_accounts_create)

    wfr_accounts_update_parser = sub.add_parser(
        "accounts-update",
        help="Update an account (write; requires --yes)",
        description=(
            "Update a Wealthfolio account via PUT /api/v1/accounts/{id} "
            "(WealthfolioClient.update_account). Only fields explicitly "
            "passed are forwarded. Without --yes, prints a preview of the "
            "camelCase fields that would be sent and makes no write. Pass "
            "--yes to actually apply the update."
        ),
    )
    wfr_accounts_update_parser.add_argument(
        "--account-id", required=True, dest="account_id", help="Id of the account to update")
    _add_account_field_args(wfr_accounts_update_parser, name_required=False)
    wfr_accounts_update_parser.add_argument(
        "--yes", action="store_true", help="Confirm the write; without this, only a preview is printed")
    wfr_accounts_update_parser.set_defaults(func=cmd_wealthfolio_rest_accounts_update)

    wfr_accounts_delete_parser = sub.add_parser(
        "accounts-delete",
        help="Delete an account (write; requires --yes; NO undo path)",
        description=(
            "Delete a Wealthfolio account via DELETE /api/v1/accounts/{id} "
            "(WealthfolioClient.delete_account). Always looks up and prints "
            "the account (id/name/currency) first. Without --yes, makes no "
            "write. There is NO undo path -- once deleted, the account "
            "cannot be restored via this client."
        ),
    )
    wfr_accounts_delete_parser.add_argument(
        "--account-id", required=True, dest="account_id", help="Id of the account to delete")
    wfr_accounts_delete_parser.add_argument(
        "--yes", action="store_true", help="Confirm the delete; without this, only a preview is printed")
    wfr_accounts_delete_parser.set_defaults(func=cmd_wealthfolio_rest_accounts_delete)


def _register_holdings(sub):
    wfr_holdings_parser = sub.add_parser("holdings", help="List holdings (JSON)")
    wfr_holdings_parser.add_argument("--account-id", default=None, dest="account_id")
    wfr_holdings_parser.add_argument("--portfolio-id", default=None, dest="portfolio_id")
    wfr_holdings_parser.add_argument(
        "--account-ids", action="append", default=None, dest="account_ids",
        help="Repeatable; ad-hoc account scope (pass at most one of --account-id/"
             "--portfolio-id/--account-ids)",
    )
    wfr_holdings_parser.add_argument(
        "--include-closed", action="store_true", dest="include_closed",
        help="Also include positions whose quantity has gone to zero",
    )
    wfr_holdings_parser.set_defaults(func=cmd_wealthfolio_rest_holdings)


def _register_snapshots(sub):
    wfr_snapshots_parser = sub.add_parser(
        "snapshots", help="List stored holdings-snapshot metadata for an account (JSON)")
    wfr_snapshots_parser.add_argument("--account-id", required=True, dest="account_id")
    wfr_snapshots_parser.add_argument("--date-from", default=None, dest="date_from")
    wfr_snapshots_parser.add_argument("--date-to", default=None, dest="date_to")
    wfr_snapshots_parser.set_defaults(func=cmd_wealthfolio_rest_snapshots)

    wfr_snapshots_check_parser = sub.add_parser(
        "snapshots-check",
        help="Validate a batch of holdings snapshots without persisting (JSON; read-only)",
        description=(
            "Validate a batch of holdings snapshots loaded from --file "
            "(a JSON list of {date, positions, cashBalances} objects) via "
            "POST /api/v1/snapshots/import/check. Read-only."
        ),
    )
    wfr_snapshots_check_parser.add_argument("--account-id", required=True, dest="account_id")
    wfr_snapshots_check_parser.add_argument(
        "--file", required=True, help="Path to a JSON file with a list of snapshot objects")
    wfr_snapshots_check_parser.set_defaults(func=cmd_wealthfolio_rest_snapshots_check)

    wfr_snapshots_import_parser = sub.add_parser(
        "snapshots-import",
        help="Persist a batch of holdings snapshots (write; dry-run by default)",
        description=(
            "Persist a batch of holdings snapshots loaded from --file "
            "(a JSON list of {date, positions, cashBalances} objects) via "
            "POST /api/v1/snapshots/import. Importing a date that already "
            "has a stored snapshot overwrites it."
        ),
    )
    wfr_snapshots_import_parser.add_argument("--account-id", required=True, dest="account_id")
    wfr_snapshots_import_parser.add_argument(
        "--file", required=True, help="Path to a JSON file with a list of snapshot objects")
    wfr_snapshots_import_parser.add_argument(
        "--yes", action="store_true", help="Confirm the write; without this, only a preview is printed")
    wfr_snapshots_import_parser.set_defaults(func=cmd_wealthfolio_rest_snapshots_import)

    wfr_snapshot_delete_parser = sub.add_parser(
        "snapshot-delete",
        help="Delete one holdings snapshot by date (write; requires --yes; NO undo path)")
    wfr_snapshot_delete_parser.add_argument("--account-id", required=True, dest="account_id")
    wfr_snapshot_delete_parser.add_argument(
        "--date", required=True, help="Snapshot date to delete (YYYY-MM-DD)")
    wfr_snapshot_delete_parser.add_argument(
        "--yes", action="store_true", help="Confirm the delete; without this, only a preview is printed")
    wfr_snapshot_delete_parser.set_defaults(func=cmd_wealthfolio_rest_snapshot_delete)


def _register_cash_balances(sub):
    wfr_cash_balances_parser = sub.add_parser(
        "cash-balances", help="Current cash/investment/total valuation by scope (JSON)")
    wfr_cash_balances_parser.add_argument("--account-id", default=None, dest="account_id")
    wfr_cash_balances_parser.add_argument("--portfolio-id", default=None, dest="portfolio_id")
    wfr_cash_balances_parser.add_argument(
        "--account-ids", action="append", default=None, dest="account_ids",
        help="Repeatable; ad-hoc account scope (pass at most one of --account-id/"
             "--portfolio-id/--account-ids)",
    )
    wfr_cash_balances_parser.add_argument(
        "--include-accounts", action="store_true", dest="include_accounts",
        help="Also include a per-account breakdown in the response",
    )
    wfr_cash_balances_parser.set_defaults(func=cmd_wealthfolio_rest_cash_balances)


def _register_performance(sub):
    wfr_performance_parser = sub.add_parser(
        "performance", help="Portfolio performance summary or history (JSON)")
    wfr_performance_parser.add_argument("--account-id", default=None, dest="account_id")
    wfr_performance_parser.add_argument("--portfolio-id", default=None, dest="portfolio_id")
    wfr_performance_parser.add_argument("--account-ids", action="append", default=None, dest="account_ids")
    wfr_performance_parser.add_argument(
        "--item-id", default=None, dest="item_id",
        help="Single item id (e.g. a symbol/holding) instead of an account scope",
    )
    wfr_performance_parser.add_argument("--item-type", default="account", dest="item_type")
    wfr_performance_parser.add_argument("--start-date", default=None, dest="start_date")
    wfr_performance_parser.add_argument("--end-date", default=None, dest="end_date")
    wfr_performance_parser.add_argument(
        "--tracking-mode", default=None, dest="tracking_mode",
        help="HOLDINGS or TRANSACTIONS (single-item path only)",
    )
    wfr_performance_parser.add_argument(
        "--profile", default=None, help="full (default), summary, or dashboard")
    wfr_performance_parser.add_argument(
        "--history", action="store_true",
        help="Call /performance/history (full daily series) instead of /performance/summary",
    )
    wfr_performance_parser.set_defaults(func=cmd_wealthfolio_rest_performance)


def _register_activities_search(sub):
    wfr_activities_parser = sub.add_parser(
        "activities", help="Search activities/transactions (JSON)")
    wfr_activities_parser.add_argument("--account-id", default=None, dest="account_id")
    wfr_activities_parser.add_argument("--activity-type", default=None, dest="activity_type")
    wfr_activities_parser.add_argument(
        "--asset-id-keyword", default=None, dest="asset_id_keyword",
        help="Substring match on asset id/symbol (REST has no --symbol filter)",
    )
    wfr_activities_parser.add_argument("--date-from", default=None, dest="date_from")
    wfr_activities_parser.add_argument("--date-to", default=None, dest="date_to")
    wfr_activities_parser.add_argument("--page", type=int, default=None)
    wfr_activities_parser.add_argument("--page-size", type=int, default=None, dest="page_size")
    wfr_activities_parser.set_defaults(func=cmd_wealthfolio_rest_activities)


def _register_net_worth(sub):
    wfr_net_worth_parser = sub.add_parser(
        "net-worth", help="Net worth snapshot or history (JSON)")
    wfr_net_worth_parser.add_argument(
        "--date", default=None,
        help="Snapshot date, or the end of the range when --start-date is given")
    wfr_net_worth_parser.add_argument(
        "--start-date", default=None, dest="start_date",
        help="If given, fetches the /net-worth/history range instead of a single snapshot")
    wfr_net_worth_parser.set_defaults(func=cmd_wealthfolio_rest_net_worth)


def _register_allocation(sub):
    wfr_allocation_parser = sub.add_parser(
        "allocation", help="Asset allocation breakdown (JSON)")
    wfr_allocation_parser.add_argument("--account-id", default=None, dest="account_id")
    wfr_allocation_parser.add_argument("--portfolio-id", default=None, dest="portfolio_id")
    wfr_allocation_parser.add_argument("--account-ids", action="append", default=None, dest="account_ids")
    wfr_allocation_parser.add_argument(
        "--include-closed", action="store_true", dest="include_closed")
    wfr_allocation_parser.set_defaults(func=cmd_wealthfolio_rest_allocation)


def _register_income(sub):
    wfr_income_parser = sub.add_parser(
        "income", help="Income summary, e.g. dividends/interest (JSON)")
    wfr_income_parser.add_argument("--account-id", default=None, dest="account_id")
    wfr_income_parser.add_argument("--portfolio-id", default=None, dest="portfolio_id")
    wfr_income_parser.add_argument("--account-ids", action="append", default=None, dest="account_ids")
    wfr_income_parser.set_defaults(func=cmd_wealthfolio_rest_income)


def _register_health(sub):
    wfr_health_parser = sub.add_parser("health", help="Portfolio data-health status (JSON)")
    wfr_health_parser.set_defaults(func=cmd_wealthfolio_rest_health)


def _register_goals(sub):
    wfr_goals_parser = sub.add_parser("goals", help="List goals (JSON)")
    wfr_goals_parser.set_defaults(func=cmd_wealthfolio_rest_goals)


def _register_limits(sub):
    wfr_limits_parser = sub.add_parser("limits", help="List contribution limits (JSON)")
    wfr_limits_parser.set_defaults(func=cmd_wealthfolio_rest_limits)


def _register_portfolios(sub):
    wfr_portfolios_parser = sub.add_parser("portfolios", help="List saved portfolios (JSON)")
    wfr_portfolios_parser.set_defaults(func=cmd_wealthfolio_rest_portfolios)


def _register_taxonomies(sub):
    wfr_taxonomies_parser = sub.add_parser(
        "taxonomies", help="List taxonomies, or one taxonomy's detail with --taxonomy-id (JSON)")
    wfr_taxonomies_parser.add_argument("--taxonomy-id", default=None, dest="taxonomy_id")
    wfr_taxonomies_parser.add_argument("--taxonomy-name", default=None, dest="taxonomy_name")
    wfr_taxonomies_parser.add_argument(
        "--include-categories", action="store_true", dest="include_categories",
        help="Also fetch each taxonomy's categories (one extra request per taxonomy)",
    )
    wfr_taxonomies_parser.add_argument(
        "--category-depth", type=int, default=None, dest="category_depth",
        help="Accepted for interface parity only -- has no server-side effect",
    )
    wfr_taxonomies_parser.set_defaults(func=cmd_wealthfolio_rest_taxonomies)

    wfr_taxonomy_assignments_parser = sub.add_parser(
        "taxonomy-assignments", help="List one asset's taxonomy assignments (JSON)")
    wfr_taxonomy_assignments_parser.add_argument(
        "--asset-id", required=True, dest="asset_id")
    wfr_taxonomy_assignments_parser.add_argument(
        "--taxonomy-id", default=None, dest="taxonomy_id",
        help="Client-side filter -- the endpoint itself returns every taxonomy's assignments",
    )
    wfr_taxonomy_assignments_parser.set_defaults(func=cmd_wealthfolio_rest_taxonomy_assignments)


def _register_classify(sub):
    wfr_classify_preview_parser = sub.add_parser(
        "classify-preview", help="Non-mutating preview of a classification change (JSON)")
    wfr_classify_preview_parser.add_argument("--asset-id", required=True, dest="asset_id")
    wfr_classify_preview_parser.add_argument("--taxonomy-id", required=True, dest="taxonomy_id")
    wfr_classify_preview_parser.add_argument(
        "--assignments", required=True,
        help='JSON list of {"category_id": ..., "weight": ..., "source": ...} objects',
    )
    wfr_classify_preview_parser.set_defaults(func=cmd_wealthfolio_rest_classify_preview)

    wfr_classify_commit_parser = sub.add_parser(
        "classify-commit",
        help="Replace every taxonomy assignment for an asset/taxonomy pair (dry-run by default)")
    wfr_classify_commit_parser.add_argument("--asset-id", required=True, dest="asset_id")
    wfr_classify_commit_parser.add_argument("--taxonomy-id", required=True, dest="taxonomy_id")
    wfr_classify_commit_parser.add_argument(
        "--assignments", required=True,
        help='JSON list of {"category_id": ..., "weight": ..., "source": ...} objects',
    )
    wfr_classify_commit_parser.add_argument(
        "--yes", action="store_true", help="Actually replace assignments (default: dry-run preview)")
    wfr_classify_commit_parser.set_defaults(func=cmd_wealthfolio_rest_classify_commit)


def _register_categorization(sub):
    wfr_categorization_context_parser = sub.add_parser(
        "categorization-context",
        help="List activities that may need categorization (JSON; read-only)")
    wfr_categorization_context_parser.add_argument(
        "--account-ids", action="append", dest="account_ids",
        help="Repeatable; filter to these account ids",
    )
    wfr_categorization_context_parser.add_argument("--start-date", default=None, dest="start_date")
    wfr_categorization_context_parser.add_argument("--end-date", default=None, dest="end_date")
    wfr_categorization_context_parser.add_argument(
        "--status", default=None,
        help='One of "all"/"needs_review"/"uncategorized"/"categorized" -- '
        'defaults to None so the client applies its own "uncategorized" default',
    )
    wfr_categorization_context_parser.add_argument("--limit", type=int, default=None)
    wfr_categorization_context_parser.add_argument("--offset", type=int, default=None)
    wfr_categorization_context_parser.set_defaults(func=cmd_wealthfolio_rest_categorization_context)

    wfr_categorization_rule_create_parser = sub.add_parser(
        "categorization-rule-create",
        help="Create a saved spending categorization rule (dry-run by default)")
    wfr_categorization_rule_create_parser.add_argument("--name", required=True)
    wfr_categorization_rule_create_parser.add_argument("--pattern", required=True)
    wfr_categorization_rule_create_parser.add_argument("--taxonomy-id", default=None, dest="taxonomy_id")
    wfr_categorization_rule_create_parser.add_argument(
        "--category-id", default=None, dest="category_id",
        help="Resolve via `taxonomies --include-categories` -- no key-based lookup here",
    )
    wfr_categorization_rule_create_parser.add_argument("--match-type", default=None, dest="match_type")
    wfr_categorization_rule_create_parser.add_argument("--account-id", default=None, dest="account_id")
    wfr_categorization_rule_create_parser.add_argument("--activity-type", default=None, dest="activity_type")
    wfr_categorization_rule_create_parser.add_argument("--amount-op", default=None, dest="amount_op")
    wfr_categorization_rule_create_parser.add_argument("--amount-value", default=None, dest="amount_value")
    wfr_categorization_rule_create_parser.add_argument("--amount-value2", default=None, dest="amount_value2")
    wfr_categorization_rule_create_parser.add_argument("--priority", type=int, default=None)
    wfr_categorization_rule_create_parser.add_argument(
        "--is-global", action="store_true", dest="is_global", default=None)
    wfr_categorization_rule_create_parser.add_argument(
        "--yes", action="store_true", help="Actually create this rule (default: dry-run preview)")
    wfr_categorization_rule_create_parser.set_defaults(func=cmd_wealthfolio_rest_categorization_rule_create)


def _register_import(sub):
    wfr_import_mapping_parser = sub.add_parser(
        "import-mapping",
        help="Fetch a saved Wealthfolio import-mapping template (JSON; read-only)",
        description=(
            "Generic Wealthfolio-native CSV-import-mapping surface "
            "(WealthfolioClient.get_import_mapping)."
        ),
    )
    wfr_import_mapping_parser.add_argument(
        "--account-id", required=True, dest="account_id",
        help="Wealthfolio account id to fetch the saved mapping for")
    wfr_import_mapping_parser.add_argument(
        "--context-kind", default=None, dest="context_kind",
        help='Defaults to the server\'s own "CSV_ACTIVITY"; the only other '
             'real value is "CSV_HOLDINGS" (a separate, unimplemented '
             'holdings-snapshot import flow)',
    )
    wfr_import_mapping_parser.set_defaults(func=cmd_wealthfolio_rest_import_mapping)

    wfr_import_preview_parser = sub.add_parser(
        "import-preview",
        help="Validate/dedup a batch of ActivityImport rows without persisting (read-only)",
        description=(
            "Generic Wealthfolio-native bulk-import-check surface "
            "(WealthfolioClient.prepare_activity_import) -- raw ActivityImport "
            "rows, no transformation beyond the server's own validation."
        ),
    )
    wfr_import_preview_parser.add_argument(
        "--file", required=True,
        help="Path to a .json (bare list of camelCase ActivityImport row dicts) "
             "or .csv (header row = camelCase wire field names) file")
    wfr_import_preview_parser.add_argument(
        "--account-id", default=None, dest="account_id",
        help="Fill in accountId for any row that doesn't already set its own")
    wfr_import_preview_parser.set_defaults(func=cmd_wealthfolio_rest_import_preview)

    wfr_import_commit_parser = sub.add_parser(
        "import-commit",
        help="Bulk-import a batch of ActivityImport rows into Wealthfolio (dry-run by default)",
        description=(
            "Generic Wealthfolio-native bulk-import surface "
            "(WealthfolioClient.commit_activity_import) -- raw ActivityImport "
            "rows, no transformation beyond the server's own import handling."
        ),
    )
    wfr_import_commit_parser.add_argument(
        "--file", required=True,
        help="Path to a .json (bare list of camelCase ActivityImport row dicts) "
             "or .csv (header row = camelCase wire field names) file")
    wfr_import_commit_parser.add_argument(
        "--account-id", default=None, dest="account_id",
        help="Fill in accountId for any row that doesn't already set its own")
    wfr_import_commit_parser.add_argument(
        "--yes", action="store_true",
        help="Actually persist this import (default: dry-run preview via "
             "prepare_activity_import, no writes)")
    wfr_import_commit_parser.set_defaults(func=cmd_wealthfolio_rest_import_commit)


def _register_assets(sub):
    wfr_assets_parser = sub.add_parser("assets", help="List assets (JSON)")
    wfr_assets_parser.set_defaults(func=cmd_wealthfolio_rest_assets)

    wfr_asset_parser = sub.add_parser(
        "asset", help="Get one asset's full profile, including notes/metadata (JSON)")
    wfr_asset_parser.add_argument(
        "--asset-id", required=True, dest="asset_id", help="Id of the asset to fetch")
    wfr_asset_parser.set_defaults(func=cmd_wealthfolio_rest_asset)

    def _add_asset_field_args(parser, kind_required=False, quote_ccy_required=False):
        parser.add_argument(
            "--kind", default=None, required=kind_required,
            help="Asset kind, e.g. SECURITY/CASH" + (" (required)" if kind_required else ""))
        parser.add_argument("--name", default=None, help="Asset display name")
        parser.add_argument(
            "--display-code", default=None, dest="display_code",
            help="Short display code/ticker shown in the UI")
        parser.add_argument(
            "--quote-mode", default=None, dest="quote_mode", help="e.g. MANUAL/MARKET quote mode")
        parser.add_argument(
            "--quote-ccy", default=None, dest="quote_ccy", required=quote_ccy_required,
            help="ISO currency code the asset is quoted in" + (" (required)" if quote_ccy_required else ""))
        parser.add_argument("--instrument-type", default=None, dest="instrument_type")
        parser.add_argument("--instrument-symbol", default=None, dest="instrument_symbol")
        parser.add_argument("--instrument-exchange-mic", default=None, dest="instrument_exchange_mic")
        parser.add_argument("--notes", default=None, help="Free-form notes")
        parser.add_argument(
            "--metadata-json", default=None, dest="metadata_json",
            help="Inline JSON object, or a path to a JSON file, mapped to 'metadata'")
        parser.add_argument(
            "--provider-config-json", default=None, dest="provider_config_json",
            help="Inline JSON object, or a path to a JSON file, mapped to 'providerConfig'")

    wfr_asset_create_parser = sub.add_parser(
        "asset-create",
        help="Create an asset (write; requires --yes)",
        description=(
            "Create a Wealthfolio asset via POST /api/v1/assets "
            "(WealthfolioClient.create_asset). Without --yes, prints a "
            "preview of the camelCase fields that would be sent and makes "
            "no write. Pass --yes to actually create the asset. --kind/"
            "--quote-ccy are required -- the wire schema has no server-side "
            "default for either."
        ),
    )
    _add_asset_field_args(wfr_asset_create_parser, kind_required=True, quote_ccy_required=True)
    wfr_asset_create_parser.add_argument(
        "--yes", action="store_true", help="Confirm the write; without this, only a preview is printed")
    wfr_asset_create_parser.set_defaults(func=cmd_wealthfolio_rest_asset_create)

    wfr_asset_update_parser = sub.add_parser(
        "asset-update",
        help="Update an asset's profile (write; requires --yes)",
        description=(
            "Update a Wealthfolio asset's profile via PUT "
            "/api/v1/assets/profile/{id} (WealthfolioClient."
            "update_asset_profile). This endpoint is a full replacement on "
            "the wire, not a per-field patch: any field missing from the "
            "request resets it to null/its default. To prevent that, this "
            "always fetches the asset's current profile first (via "
            "get_asset) and fills in every field not explicitly passed "
            "with its current value (\"\" for --notes specifically), so "
            "only the flags actually passed end up changing. Pass --notes "
            "\"\" explicitly to actually clear notes. Without --yes, "
            "prints a preview and makes no write; pass --yes to actually "
            "apply it."
        ),
    )
    wfr_asset_update_parser.add_argument(
        "--asset-id", required=True, dest="asset_id", help="Id of the asset to update")
    _add_asset_field_args(wfr_asset_update_parser, kind_required=False, quote_ccy_required=False)
    wfr_asset_update_parser.add_argument(
        "--yes", action="store_true", help="Confirm the write; without this, only a preview is printed")
    wfr_asset_update_parser.set_defaults(func=cmd_wealthfolio_rest_asset_update)

    wfr_asset_delete_parser = sub.add_parser(
        "asset-delete",
        help="Delete an asset (write; requires --yes; NO undo path)",
        description=(
            "Delete a Wealthfolio asset via DELETE /api/v1/assets/{id} "
            "(WealthfolioClient.delete_asset). Always looks up and prints "
            "the asset (id/name/kind) first. Without --yes, makes no "
            "write. There is NO undo path -- once deleted, the asset "
            "cannot be restored via this client."
        ),
    )
    wfr_asset_delete_parser.add_argument(
        "--asset-id", required=True, dest="asset_id", help="Id of the asset to delete")
    wfr_asset_delete_parser.add_argument(
        "--yes", action="store_true", help="Confirm the delete; without this, only a preview is printed")
    wfr_asset_delete_parser.set_defaults(func=cmd_wealthfolio_rest_asset_delete)


def _register_activities_crud(sub):
    def _add_activity_field_args(parser, required=False):
        parser.add_argument(
            "--account-id", default=None, dest="account_id", required=required,
            help="Wealthfolio account id" + (" (required)" if required else ""))
        parser.add_argument(
            "--activity-type", default=None, dest="activity_type", required=required,
            help="e.g. BUY/SELL/DEPOSIT/DIVIDEND" + (" (required)" if required else ""))
        parser.add_argument(
            "--activity-date", default=None, dest="activity_date", required=required,
            help="ISO date/datetime string" + (" (required)" if required else ""))
        parser.add_argument(
            "--asset-id", default=None, dest="asset_id",
            help="Asset id -- translated internally to the nested symbol={\"id\": ...} object")
        parser.add_argument("--quantity", type=float, default=None)
        parser.add_argument("--unit-price", type=float, default=None, dest="unit_price")
        parser.add_argument("--currency", default=None, help="ISO currency code, e.g. EUR/USD")
        parser.add_argument("--fee", type=float, default=None)
        parser.add_argument("--tax", type=float, default=None)
        parser.add_argument(
            "--notes", "--comment", default=None, dest="notes", help="Free-form notes/comment")
        parser.add_argument(
            "--metadata-json", default=None, dest="metadata_json",
            help="Inline JSON object, or a path to a JSON file, mapped to 'metadata'")

    wfr_activities_create_parser = sub.add_parser(
        "activities-create",
        help="Create an activity (write; requires --yes)",
        description=(
            "Create a Wealthfolio activity via POST /api/v1/activities "
            "(WealthfolioClient.create_activity). Without --yes, prints a "
            "preview of the camelCase fields that would be sent (including "
            "the --asset-id -> nested symbol={\"id\": ...} translation) and "
            "makes no write. Pass --yes to actually create the activity."
        ),
    )
    _add_activity_field_args(wfr_activities_create_parser, required=True)
    wfr_activities_create_parser.add_argument(
        "--yes", action="store_true", help="Confirm the write; without this, only a preview is printed")
    wfr_activities_create_parser.set_defaults(func=cmd_wealthfolio_rest_activities_create)

    wfr_activities_update_parser = sub.add_parser(
        "activities-update",
        help="Update an activity (write; requires --yes)",
        description=(
            "Update a Wealthfolio activity via PUT /api/v1/activities "
            "(WealthfolioClient.update_activity) -- a full-replace write, "
            "not a patch. Any required field not explicitly passed as a "
            "flag is defaulted from the activity's current value (fetched "
            "via search_activities, there being no singular get-activity "
            "endpoint), so an update never silently blanks a field you "
            "didn't mean to touch. Without --yes, prints a preview and "
            "makes no write; pass --yes to actually apply it."
        ),
    )
    wfr_activities_update_parser.add_argument(
        "--activity-id", required=True, dest="activity_id", help="Id of the activity to update")
    _add_activity_field_args(wfr_activities_update_parser, required=False)
    wfr_activities_update_parser.add_argument(
        "--yes", action="store_true", help="Confirm the write; without this, only a preview is printed")
    wfr_activities_update_parser.set_defaults(func=cmd_wealthfolio_rest_activities_update)

    wfr_activities_delete_parser = sub.add_parser(
        "activities-delete",
        help="Delete an activity (write; requires --yes; NO undo path)",
        description=(
            "Delete a Wealthfolio activity via DELETE /api/v1/activities/{id} "
            "(WealthfolioClient.delete_activity). Always looks up and prints "
            "the activity (id/type/date/account) first. Without --yes, makes "
            "no write. There is NO undo path -- once deleted, the activity "
            "cannot be restored via this client."
        ),
    )
    wfr_activities_delete_parser.add_argument(
        "--activity-id", required=True, dest="activity_id", help="Id of the activity to delete")
    wfr_activities_delete_parser.add_argument(
        "--yes", action="store_true", help="Confirm the delete; without this, only a preview is printed")
    wfr_activities_delete_parser.set_defaults(func=cmd_wealthfolio_rest_activities_delete)

    wfr_activities_bulk_parser = sub.add_parser(
        "activities-bulk",
        help="Bulk create/update/delete activities in one call (write; requires --yes)",
        description=(
            "Create/update/delete many Wealthfolio activities in one call via "
            "POST /api/v1/activities/bulk (WealthfolioClient.save_activities). "
            "A per-item failure lands in the result's errors list rather than "
            "aborting the whole batch. Without --yes, prints a preview of the "
            "batch and makes no write; pass --yes to actually submit it."
        ),
    )
    wfr_activities_bulk_parser.add_argument(
        "--creates-json", default=None, dest="creates_json",
        help="Inline JSON list, or a path to a JSON file, of camelCase NewActivity field dicts")
    wfr_activities_bulk_parser.add_argument(
        "--updates-json", default=None, dest="updates_json",
        help="Inline JSON list, or a path to a JSON file, of camelCase ActivityUpdate field dicts")
    wfr_activities_bulk_parser.add_argument(
        "--delete-ids", action="append", default=None, dest="delete_ids",
        help="Repeatable; each occurrence may also be a comma-separated list of activity ids")
    wfr_activities_bulk_parser.add_argument(
        "--yes", action="store_true", help="Confirm the write; without this, only a preview is printed")
    wfr_activities_bulk_parser.set_defaults(func=cmd_wealthfolio_rest_activities_bulk)


def register_generic_subparsers_part1(sub):
    """Add every generic subcommand that comes BEFORE a host application's
    own repo-specific subcommand block, if it has one (accounts through
    categorization-rule-create). Called by both this package's own
    `build_parser()` and any host application's equivalent `register()`,
    so there is a single source of truth for this wiring."""
    _register_accounts(sub)
    _register_holdings(sub)
    _register_snapshots(sub)
    _register_cash_balances(sub)
    _register_performance(sub)
    _register_activities_search(sub)
    _register_net_worth(sub)
    _register_allocation(sub)
    _register_income(sub)
    _register_health(sub)
    _register_goals(sub)
    _register_limits(sub)
    _register_portfolios(sub)
    _register_taxonomies(sub)
    _register_classify(sub)
    _register_categorization(sub)


def register_generic_subparsers_part2(sub):
    """Add every generic subcommand that comes AFTER a host application's
    own repo-specific subcommand block, if it has one (import-mapping
    through activities-bulk). See `register_generic_subparsers_part1`."""
    _register_import(sub)
    _register_assets(sub)
    _register_activities_crud(sub)


def register_generic_subparsers(sub):
    """Add every generic subcommand in its natural order (no repo-specific
    commands interleaved) -- used by this package's own standalone
    `wealthfolio` CLI, which has no repo-specific commands at all."""
    register_generic_subparsers_part1(sub)
    register_generic_subparsers_part2(sub)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="wealthfolio",
        description=(
            "Generic Wealthfolio REST CLI -- thin pass-throughs to "
            "Wealthfolio's own HTTP API. Most subcommands are read-only "
            "and print the server's own JSON response verbatim; no "
            "calculations happen here. Writes are gated behind an "
            "explicit --yes confirmation flag and a preview of the change "
            "printed first (see each subcommand's own --help).\n\n"
            "Configure via the WEALTHFOLIO_PASSWORD (required) and "
            "optional WEALTHFOLIO_REST_URL environment variables, or a "
            ".env file -- see wealthfolio/config.py."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="subcommand", help="Wealthfolio subcommand")
    register_generic_subparsers(sub)
    return parser


def main():
    from wealthfolio.config import load_dotenv

    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
