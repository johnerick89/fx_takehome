"""Application exception stubs."""


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str) -> None:
        """Store the error message."""
        self.message = message
        super().__init__(message)


class CustomerNotFoundError(AppError):
    """Raised when a customer ID does not exist."""


class DuplicateEmailError(AppError):
    """Raised when a customer email is already registered."""


class InvalidAmountError(AppError):
    """Raised when an amount is zero, negative, or otherwise invalid."""


class UnsupportedCurrencyError(AppError):
    """Raised when a currency code is not supported."""
