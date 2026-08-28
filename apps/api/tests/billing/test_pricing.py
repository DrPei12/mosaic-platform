from uuid import uuid4

import pytest

from app.billing.errors import BillingInvariantError
from app.billing.ports import BillingUsage, PriceSnapshot
from app.billing.pricing import charge_for_usage, pricing_version, reservation_amount


def _price(**pricing: object) -> PriceSnapshot:
    return PriceSnapshot(
        price_version_id=uuid4(),
        price_key="qwen-3-5-plus:local-v1",
        version=1,
        currency="PTS",
        unit="local_metered_usage",
        pricing={
            "schema": "local_tariff_v1",
            "currency": "PTS",
            "rounding": "integer_sum",
            "reservation_minor": 100,
            "minimum_charge_minor": 1,
            "components": {"input_tokens": 1, "output_tokens": 2},
            **pricing,
        },
    )


def test_local_tariff_is_integer_deterministic_and_nonzero() -> None:
    price = _price()
    usage = BillingUsage(input_tokens=3, output_tokens=4)

    assert reservation_amount(price).amount_minor == 100
    assert charge_for_usage(price, usage).amount_minor == 12
    assert charge_for_usage(price, BillingUsage()).amount_minor == 1
    assert charge_for_usage(price, usage) == charge_for_usage(price, usage)
    assert pricing_version(price) == "qwen-3-5-plus:local-v1@v1"


@pytest.mark.parametrize(
    "pricing",
    [
        {"reservation_minor": 0},
        {"minimum_charge_minor": 0},
        {"minimum_charge_minor": 101},
        {"components": {"input_tokens": 0}},
        {"schema": "provider_metered"},
    ],
)
def test_invalid_or_zero_local_tariff_fails_closed(pricing: dict[str, object]) -> None:
    with pytest.raises(BillingInvariantError):
        reservation_amount(_price(**pricing))
