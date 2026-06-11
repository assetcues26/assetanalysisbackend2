"""Client-facing valuation shape — display currency for regional deployments."""

from __future__ import annotations

from app.models.responses import MoneyRange, NbvEstimate, Valuation, ValuationAmount


def _clear_usd(amount: ValuationAmount) -> ValuationAmount:
    return amount.model_copy(update={"usd": MoneyRange()})


def _clear_nbv_usd(nbv: NbvEstimate) -> NbvEstimate:
    return nbv.model_copy(update={"usd": MoneyRange()})


def client_valuation(valuation: Valuation) -> Valuation:
    """Strip internal USD amounts; clients use display (+ inr for India backward compat)."""
    nbv = valuation.nbv
    if nbv is not None:
        nbv = _clear_nbv_usd(nbv)
    return valuation.model_copy(
        update={
            "as_is": _clear_usd(valuation.as_is),
            "like_new_reference": _clear_usd(valuation.like_new_reference),
            "nbv": nbv,
        }
    )
