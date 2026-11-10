# python-wealthfolio

A hand-rolled Python REST client and CLI for [Wealthfolio](https://wealthfolio.app)'s
own HTTP API — accounts, activities, holdings, performance, net worth, income,
goals, contribution limits, health, portfolios, asset taxonomies, transaction
categorization, cash balances, asset allocation, activity import, holdings
snapshots, and assets. No dependency on any particular application; it only
talks to a Wealthfolio server you point it at.

## Install

```bash
pip install "python-wealthfolio @ git+https://github.com/inercia/python-wealthfolio.git@v0.1.0"
# or, for local development from a checkout:
pip install -e .
```

Requires Python 3.9+. The only runtime dependency is `requests`.
Install from Git; this project is not currently published to PyPI.

## Authentication

This client supports Wealthfolio REST session-cookie login with a single
password, not API-token authentication. Configure it via two environment variables:

| Variable               | Required | Meaning                                   |
|-------------------------|----------|--------------------------------------------|
| `WEALTHFOLIO_PASSWORD`  | yes      | Login password for your Wealthfolio server |
| `WEALTHFOLIO_REST_URL`  | yes      | Base URL, e.g. `https://wealthfolio.example.com` |

**This package does not read `.env` files as part of resolving client
config.** A generic library shouldn't silently reach into the filesystem
looking for a specific application's dotfile — `load_rest_config` and
`WealthfolioClient.from_env()` consult only explicit arguments and
`os.environ`. If you want `.env`-file support, call the optional
`wealthfolio.config.load_dotenv()` helper yourself once at startup (it
mirrors the well-known `python-dotenv` convention: it searches the current
directory and its parents for a `.env` file, and copies its values into
`os.environ` without overriding variables you've already set). The bundled
`wealthfolio` console script does this automatically in its own `main()`.

## Quick start (library)

```python
from wealthfolio import WealthfolioClient

with WealthfolioClient.from_env() as client:
    accounts = client.get_accounts()
    for account in accounts.accounts:
        print(account.id, account.name, account.currency)

    holdings = client.get_holdings(account_id=accounts.accounts[0].id)
    for holding in holdings.holdings:
        print(holding.instrument.symbol, holding.quantity)
```

You can also pass config explicitly instead of relying on the environment:

```python
from wealthfolio import WealthfolioClient
from wealthfolio.config import WealthfolioRestConfig

config = WealthfolioRestConfig(base_url="https://wealthfolio.example.com", password="...")
with WealthfolioClient(config) as client:
    ...
```

Every read method returns a typed, lenient result object (every field is
`Optional`, unknown/missing keys never raise) with the original parsed JSON
always available on `.raw`. Errors are raised as `WealthfolioConfigError`
(bad/missing config) or `WealthfolioAPIError` (HTTP/network failure, with
`.status_code`/`.body` when available) — see `wealthfolio/exceptions.py`.

## CLI usage

Installing this package also installs a `wealthfolio` console script — a
thin pass-through CLI over the same client, printing the server's own JSON
verbatim (no client-side calculations):

```bash
export WEALTHFOLIO_PASSWORD=...
export WEALTHFOLIO_REST_URL=https://wealthfolio.example.com

wealthfolio accounts
wealthfolio holdings --account-id <id>
wealthfolio performance --account-id <id> --start-date 2025-01-01 --end-date 2025-12-31
wealthfolio activities --account-id <id> --date-from 2025-01-01
```

Run `wealthfolio --help` for the full subcommand list, and `wealthfolio
<subcommand> --help` for that subcommand's options. Writes (`accounts-create`,
`accounts-update`, `accounts-delete`, `asset-create`, `asset-update`,
`asset-delete`, `activities-create`, `activities-update`,
`activities-delete`, `activities-bulk`, `classify-commit`) are gated behind
an explicit `--yes` flag and print a preview of the change first.

## Agent skill

[`skills/wealthfolio-cli/SKILL.md`](skills/wealthfolio-cli/SKILL.md) provides
agent instructions for the standalone `wealthfolio` CLI: command discovery,
configuration, queries, validation, and explicitly authorized writes. It covers
only this library's domain, with no host-application or personal-finance rules.
To use it, copy the `skills/wealthfolio-cli/` directory into your agent's skills
directory. Installing the Python package alone does not install the agent skill.
The skill includes a [uv](https://docs.astral.sh/uv/) launcher with PEP 723 inline
dependencies tracking the library's `main` branch. It runs without installing the package
into your project's environment:

```bash
uv run --no-project --script skills/wealthfolio-cli/scripts/wealthfolio_cli.py --help
```

uv and Git are required. The public dependency repository needs no GitHub login.
First use may download Python and dependencies; subsequent runs reuse uv's cache.
The launcher preserves the caller's working directory for relative input paths.
It requires `WEALTHFOLIO_REST_URL` and `WEALTHFOLIO_PASSWORD` in the process
environment and does not load `.env` files; help needs no credentials.
Upstream changes on `main` can change CLI behavior; this setup is not locked to
a fixed revision. uv may reuse a cached revision. To refresh the library, run:

```bash
uv run --no-project --upgrade-package python-wealthfolio --script skills/wealthfolio-cli/scripts/wealthfolio_cli.py --help
```

Transitive dependencies are not fully locked either.

## Host application integration

`register_generic_subparsers_part1`/`register_generic_subparsers_part2`
(and the combined `register_generic_subparsers`) let a host application wire
every generic subcommand into its own `argparse` parser, optionally
interleaving its own repo-specific subcommands between the two parts. A host
application can also register a write hook (e.g. to invalidate its own
read-through cache) via `wealthfolio.cli.set_write_hook(fn)`, invoked after
every successful write made through the CLI layer.

## Development

```bash
pip install -e .
python -m unittest discover -s tests -p 'test_*.py'
```

See `CHANGELOG.md` for release history.

## License

MIT — see `LICENSE`.
