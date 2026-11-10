"""Utilities for loading Wealthfolio REST client config (base URL + login
password).

`load_rest_config`/`WealthfolioClient.from_env` consult only explicit
arguments and the process environment (`os.environ`) -- this package does
not read `.env` files as part of resolving client config. A generic
library should not silently reach into the filesystem looking for a
specific host application's dotfile; that decision belongs to the
application. `load_dotenv` below is an optional, explicitly-invoked helper
(never called automatically by anything in this module) that a host
application or a CLI's own `main()` can call at startup if it wants
`.env`-file support, mirroring the well-known `python-dotenv` convention.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .exceptions import WealthfolioConfigError

DEFAULT_ENV_FILENAME = ".env"
DEFAULT_URL_ENV_VAR = "WEALTHFOLIO_REST_URL"
DEFAULT_PASSWORD_ENV_VAR = "WEALTHFOLIO_PASSWORD"


@dataclass
class WealthfolioRestConfig:
    """Resolved connection details for the Wealthfolio REST API."""

    base_url: str
    password: str
    password_source: str = ""
    """Where the resolved `password` came from -- `"explicit"` (passed
    directly to `load_rest_config`) or `"env"` (read from `os.environ`,
    regardless of how it got there -- a real shell export or a prior
    `load_dotenv()` call look identical here). Purely diagnostic: never
    derived from, and never reveals, the password value itself."""


def find_env_file(start=None, filename=DEFAULT_ENV_FILENAME) -> Optional[Path]:
    """Search `start` (default: current directory) and its parents for a
    `.env` file. A `.env` file is entirely optional, so this returns `None`
    instead of raising when none is found. Not called by `load_rest_config`
    -- see `load_dotenv`."""
    current = Path(start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


def _parse_env_file(path: Path) -> dict:
    """Parse a `.env` file into a plain `{KEY: VALUE}` dict, without
    touching `os.environ`: simple `KEY=VALUE` lines, blank/`#` lines
    skipped, surrounding quotes stripped."""
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_dotenv(path=None, *, override=False) -> Optional[Path]:
    """Optional convenience, never invoked automatically by this module:
    find (via `find_env_file` when `path` is not given) and parse a `.env`
    file, then copy its values into `os.environ` -- by default only for
    keys not already set, so real process environment variables always win
    over the file (pass `override=True` to reverse that). Returns the
    `.env` path actually used, or `None` if none was found/given.

    Call this once at startup -- e.g. a CLI's own `main()`, or a host
    application's bootstrap code -- before building a client, if you want
    `.env`-file support; `load_rest_config`/`WealthfolioClient.from_env`
    never call it for you."""
    resolved = Path(path) if path else find_env_file()
    if resolved is None:
        return None
    for key, value in _parse_env_file(resolved).items():
        if override or key not in os.environ:
            os.environ[key] = value
    return resolved


def load_rest_config(
    *,
    env_url_var=DEFAULT_URL_ENV_VAR,
    env_password_var=DEFAULT_PASSWORD_ENV_VAR,
    base_url=None,
    password=None,
) -> WealthfolioRestConfig:
    """Load and resolve the Wealthfolio REST client config from explicit
    arguments and/or the process environment, in that precedence order.
    Consults `os.environ` only -- call `load_dotenv()` first if you want a
    `.env` file merged into it.

    Raises `WealthfolioConfigError` if no usable base URL or password can
    be resolved.
    """
    resolved_base_url = base_url or os.environ.get(env_url_var)
    if not resolved_base_url:
        raise WealthfolioConfigError(
            f"No Wealthfolio base URL found. Set {env_url_var} in the "
            f"process environment, or pass base_url explicitly."
        )

    resolved_password = password or os.environ.get(env_password_var)
    if not resolved_password:
        raise WealthfolioConfigError(
            f"No Wealthfolio login password found. Set {env_password_var} "
            f"in the process environment, or pass password explicitly."
        )

    return WealthfolioRestConfig(
        base_url=resolved_base_url.rstrip("/"),
        password=resolved_password,
        password_source="explicit" if password else "env",
    )
