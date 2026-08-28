"""Deterministic local tariff interpretation for immutable PriceVersion facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.billing.errors import BillingInvariantError
from app.billing.ports import BillingUsage, Money, PriceSnapshot

_SCHEMA = "local_tariff_v1"
_ALLOWED_METERS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "image_count",
        "video_seconds",
        "audio_seconds",
        "character_count",
        "audio_duration_ms",
        "video_duration_ms",
        "storage_bytes",
        "billable_units",
    }
)


@dataclass(frozen=True, slots=True)
class LocalTariff:
    """Validated integer-minor-unit tariff.

    ``reservation_minor`` is the admission-time wallet hold.  ``minimum`` and
    ``components`` define the eventual charge from normalized usage.  All
    rates are integer hundredths of one internal point per raw usage unit, so
    the result is exact and repeatable without floating-point or
    provider-side pricing behavior.
    """

    currency: str
    reservation_minor: int
    minimum_charge_minor: int
    components: Mapping[str, int]


def parse_local_tariff(price: PriceSnapshot) -> LocalTariff:
    pricing = price.pricing
    if pricing.get("schema") != _SCHEMA:
        raise BillingInvariantError
    if price.unit != "local_metered_usage":
        raise BillingInvariantError
    if pricing.get("currency") != price.currency:
        raise BillingInvariantError
    if pricing.get("rounding") != "integer_sum":
        raise BillingInvariantError
    reservation_minor = _positive_int(pricing.get("reservation_minor"))
    minimum_charge_minor = _positive_int(pricing.get("minimum_charge_minor"))
    if minimum_charge_minor > reservation_minor:
        raise BillingInvariantError
    raw_components = pricing.get("components")
    if not isinstance(raw_components, Mapping) or not raw_components:
        raise BillingInvariantError
    components: dict[str, int] = {}
    for meter, rate in raw_components.items():
        if meter not in _ALLOWED_METERS:
            raise BillingInvariantError
        components[meter] = _positive_int(rate)
    return LocalTariff(
        currency=price.currency,
        reservation_minor=reservation_minor,
        minimum_charge_minor=minimum_charge_minor,
        components=components,
    )


def reservation_amount(price: PriceSnapshot) -> Money:
    tariff = parse_local_tariff(price)
    return Money(tariff.reservation_minor, tariff.currency)


def charge_for_usage(price: PriceSnapshot, usage: BillingUsage) -> Money:
    tariff = parse_local_tariff(price)
    total = tariff.minimum_charge_minor
    for meter, rate in tariff.components.items():
        total += getattr(usage, meter) * rate
    if total <= 0:
        raise BillingInvariantError
    return Money(total, tariff.currency)


def pricing_version(price: PriceSnapshot) -> str:
    """Stable audit label for one immutable price key/version pair."""

    label = f"{price.price_key}@v{price.version}"
    if len(label) > 64:
        raise BillingInvariantError
    return label


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BillingInvariantError
    return value


__all__ = [
    "LocalTariff",
    "charge_for_usage",
    "parse_local_tariff",
    "pricing_version",
    "reservation_amount",
]
