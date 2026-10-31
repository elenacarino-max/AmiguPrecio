"""Calculos puros: no se delegan cifras a un modelo de lenguaje."""

from decimal import ROUND_HALF_UP, Decimal

from amiguprecio.models import PricingInput, PricingResult

CENT = Decimal("0.01")
ONE_HUNDRED = Decimal(100)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_price(data: PricingInput) -> PricingResult:
    """Calcula coste y precio usando margen sobre ventas, no recargo.

    Formula: precio = coste / (1 - margen / 100).
    """

    labor_cost = data.hours_worked * data.hourly_rate
    production_cost = data.materials_cost + labor_cost + data.other_expenses
    margin_ratio = data.margin_percent / ONE_HUNDRED
    calculated_price = production_cost / (Decimal(1) - margin_ratio)

    rounded_production = _money(production_cost)
    rounded_price = _money(calculated_price)
    return PricingResult(
        labor_cost=_money(labor_cost),
        production_cost=rounded_production,
        calculated_price=rounded_price,
        gross_profit=_money(rounded_price - rounded_production),
        margin_percent=data.margin_percent,
    )
