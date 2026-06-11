"""External exchange rate provider clients."""

from abc import ABC, abstractmethod
from decimal import Decimal

import httpx

from app.core.config import get_settings
from app.core.currency import SUPPORTED_CURRENCIES
from app.core.exceptions import RateProviderError

USD_QUOTE_CURRENCIES = tuple(
    sorted(currency for currency in SUPPORTED_CURRENCIES if currency != "USD")
)


class RateProvider(ABC):
    """Abstract base for USD-based exchange rate providers."""

    @abstractmethod
    def fetch_rates(self) -> dict[str, Decimal]:
        """Return quote currency rates versus one USD."""
        raise NotImplementedError


class OpenExchangeRatesProvider(RateProvider):
    """Primary provider using Open Exchange Rates (USD base)."""

    def fetch_rates(self) -> dict[str, Decimal]:
        """Fetch latest USD-based rates."""
        settings = get_settings()
        if not settings.open_exchange_rates_app_id:
            raise RateProviderError("OPEN_EXCHANGE_RATES_APP_ID is not configured")

        url = "https://openexchangerates.org/api/latest.json"
        response = httpx.get(
            url,
            params={"app_id": settings.open_exchange_rates_app_id},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        rates = payload.get("rates")
        if not isinstance(rates, dict):
            raise RateProviderError("Open Exchange Rates response missing rates")

        return _parse_usd_quotes(rates)


class ExchangeRateApiProvider(RateProvider):
    """Fallback provider using ExchangeRate-API (USD base)."""

    def fetch_rates(self) -> dict[str, Decimal]:
        """Fetch latest USD-based rates."""
        settings = get_settings()
        if not settings.exchange_rate_api_key:
            raise RateProviderError("EXCHANGE_RATE_API_KEY is not configured")

        url = f"https://v6.exchangerate-api.com/v6/{settings.exchange_rate_api_key}/latest/USD"
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
        if payload.get("result") != "success":
            raise RateProviderError("ExchangeRate-API request was not successful")

        rates = payload.get("conversion_rates")
        if not isinstance(rates, dict):
            raise RateProviderError("ExchangeRate-API response missing conversion_rates")

        return _parse_usd_quotes(rates)


def _parse_usd_quotes(rates: dict[str, object]) -> dict[str, Decimal]:
    """Parse provider payload into Decimal quote rates versus USD."""
    parsed: dict[str, Decimal] = {}
    for currency in USD_QUOTE_CURRENCIES:
        value = rates.get(currency)
        if value is None:
            raise RateProviderError(f"Missing {currency} in provider response")
        parsed[currency] = Decimal(str(value))
    return parsed


def get_rate_providers() -> list[RateProvider]:
    """Return configured rate providers in priority order."""
    return [OpenExchangeRatesProvider(), ExchangeRateApiProvider()]
