"""Exception hierarchy for the Wealthfolio REST client."""


class WealthfolioError(Exception):
    """Base class for all Wealthfolio REST client errors."""


class WealthfolioConfigError(WealthfolioError):
    """Raised when the REST client configuration (base URL/password) cannot
    be resolved."""


class WealthfolioAPIError(WealthfolioError):
    """Raised for a failed HTTP call: login failure, a non-2xx response from
    the API, or a wrapped network-level error (`requests.RequestException`).

    `status_code` is the HTTP status code when one is available (`None` for
    a network-level failure with no response at all). `body` is the raw
    response text/body when available (`None` otherwise).
    """

    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body
