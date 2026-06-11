"""Supported currency constants."""

from decimal import ROUND_HALF_UP

SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"USD", "EUR", "KES", "NGN"})
DECIMAL_PLACES: dict[str, int] = {"USD": 2, "EUR": 2, "KES": 2, "NGN": 2}
ROUNDING_MODE = ROUND_HALF_UP
