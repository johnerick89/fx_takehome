"""Application domain exceptions with SPEC error codes."""


class AppError(Exception):
    """Base application error with HTTP mapping metadata."""

    error_code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str) -> None:
        """Store the error message."""
        self.message = message
        super().__init__(message)


class CustomerNotFoundError(AppError):
    """Raised when a customer ID does not exist."""

    error_code = "CUSTOMER_NOT_FOUND"
    http_status = 404


class DuplicateEmailError(AppError):
    """Raised when a customer email is already registered."""

    error_code = "DUPLICATE_EMAIL"
    http_status = 409


class InvalidAmountError(AppError):
    """Raised when an amount is zero, negative, or otherwise invalid."""

    error_code = "INVALID_AMOUNT"
    http_status = 422


class UnsupportedCurrencyError(AppError):
    """Raised when a currency code is not supported."""

    error_code = "UNSUPPORTED_CURRENCY"
    http_status = 422


class InvalidCurrencyPairError(AppError):
    """Raised when source and destination currencies are identical."""

    error_code = "INVALID_CURRENCY_PAIR"
    http_status = 422


class RateProviderError(AppError):
    """Raised when an external rate provider fails."""

    error_code = "INTERNAL_ERROR"
    http_status = 500


class RatesStaleError(AppError):
    """Raised when cached rates are too old to use."""

    error_code = "RATES_STALE"
    http_status = 503


class SpreadNotFoundError(AppError):
    """Raised when no spread configuration exists for a pair."""

    error_code = "SPREAD_NOT_FOUND"
    http_status = 404


class RouteUnavailableError(AppError):
    """Raised when no conversion route exists for a currency pair."""

    error_code = "ROUTE_UNAVAILABLE"
    http_status = 422


class QuoteExpiredError(AppError):
    """Raised when a quote has passed its expiry time."""

    error_code = "QUOTE_EXPIRED"
    http_status = 422


class QuoteAlreadyExecutedError(AppError):
    """Raised when a quote has already been executed."""

    error_code = "QUOTE_ALREADY_EXECUTED"
    http_status = 409


class QuoteNotFoundError(AppError):
    """Raised when a quote ID does not exist."""

    error_code = "QUOTE_NOT_FOUND"
    http_status = 404


class InsufficientBalanceError(AppError):
    """Raised when a customer lacks funds for execution."""

    error_code = "INSUFFICIENT_BALANCE"
    http_status = 422


class IdempotencyKeyConflictError(AppError):
    """Raised when an idempotency key is reused for a different quote."""

    error_code = "IDEMPOTENCY_KEY_CONFLICT"
    http_status = 422


class MissingIdempotencyKeyError(AppError):
    """Raised when the Idempotency-Key header is missing on execute."""

    error_code = "MISSING_IDEMPOTENCY_KEY"
    http_status = 422


class TransactionNotFoundError(AppError):
    """Raised when a transaction ID does not exist."""

    error_code = "TRANSACTION_NOT_FOUND"
    http_status = 404
