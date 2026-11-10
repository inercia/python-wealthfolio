"""Hand-rolled Python REST client for Wealthfolio's own HTTP API.

Public API surface: `WealthfolioClient` (the client itself),
`WealthfolioRestConfig`/`load_rest_config`/`load_dotenv` (config
resolution -- see `wealthfolio.config`'s module docstring), and the
exception hierarchy (`WealthfolioError`, `WealthfolioConfigError`,
`WealthfolioAPIError`). Typed response models live in `wealthfolio.models`
and are returned by `WealthfolioClient`'s own methods rather than imported
directly in typical usage.
"""

from .client import WealthfolioClient
from .config import WealthfolioRestConfig, load_dotenv, load_rest_config
from .exceptions import WealthfolioAPIError, WealthfolioConfigError, WealthfolioError

__version__ = "0.1.0"

__all__ = [
    "WealthfolioClient",
    "WealthfolioRestConfig",
    "load_dotenv",
    "load_rest_config",
    "WealthfolioError",
    "WealthfolioConfigError",
    "WealthfolioAPIError",
    "__version__",
]
