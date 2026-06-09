"""Client-facing valuation shape (INR-only for India deployments)."""

from __future__ import annotations

from app.models.responses import MoneyRange, NbvEstimate, Valuation, ValuationAmount


def _clear_usd(amount: ValuationAmount) -> ValuationAmount:
    return amount.model_copy(update={"usd": MoneyRange()})


def client_valuation(valuation: Valuation) -> Valuation:
    """Strip USD amounts from API responses; clients see INR (₹) only."""
    nbv = valuation.nbv
    if nbv is not None:
        nbv = nbv.model_copy(update={"usd": MoneyRange()})
    return valuation.model_copy(
        update={
            "as_is": _clear_usd(valuation.as_is),
            "like_new_reference": _clear_usd(valuation.like_new_reference),
            "nbv": nbv,
        }
    )
