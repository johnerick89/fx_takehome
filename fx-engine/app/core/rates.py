"""Exchange rate constants and pair helpers."""

from app.core.currency import SUPPORTED_CURRENCIES

STALE_WARN_SECONDS = 600
STALE_BLOCK_SECONDS = 3600
RATE_DECIMAL_PLACES = 8
DEFAULT_SPREAD = "0.005"

# SPEC §2 direct pairs (6) plus inverses (12 ordered pairs total).
DIRECT_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (base, quote)
    for base in sorted(SUPPORTED_CURRENCIES)
    for quote in sorted(SUPPORTED_CURRENCIES)
    if base != quote
)
