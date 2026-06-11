"""Client valuation is INR-only."""

from app.models.responses import MoneyRange, Valuation, ValuationAmount
from app.services.valuation_display import client_valuation


def test_client_valuation_strips_usd():
    val = Valuation(
        as_is=ValuationAmount(
            usd=MoneyRange(min=100, max=120),
            inr=MoneyRange(min=8300, max=9960),
            display=MoneyRange(min=8300, max=9960),
            display_currency="INR",
        ),
        like_new_reference=ValuationAmount(
            usd=MoneyRange(min=500, max=600),
            inr=MoneyRange(min=41500, max=49800),
            display=MoneyRange(min=41500, max=49800),
            display_currency="INR",
        ),
    )
    out = client_valuation(val)
    assert out.as_is.inr.min == 8300
    assert out.as_is.usd.min is None
    assert out.like_new_reference.usd.max is None
