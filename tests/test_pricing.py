from decimal import Decimal

import pytest

from amiguprecio import PricingInput, calculate_price


def valid_input(**overrides: object) -> PricingInput:
    values: dict[str, object] = {
        "product_name": "Luna",
        "product_type": "Muñeca",
        "materials_cost": "12.50",
        "hours_worked": "5",
        "hourly_rate": "10",
        "other_expenses": "2.50",
        "margin_percent": "20",
    }
    values.update(overrides)
    return PricingInput(**values)


def test_calculates_production_cost_and_sales_margin() -> None:
    result = calculate_price(valid_input())

    assert result.labor_cost == Decimal("50.00")
    assert result.production_cost == Decimal("65.00")
    assert result.calculated_price == Decimal("81.25")
    assert result.gross_profit == Decimal("16.25")


def test_zero_margin_returns_production_cost() -> None:
    result = calculate_price(valid_input(margin_percent="0"))

    assert result.calculated_price == result.production_cost


def test_rounds_money_half_up() -> None:
    result = calculate_price(
        valid_input(materials_cost="0", hours_worked="0.01", hourly_rate="0.50", other_expenses="0")
    )

    assert result.labor_cost == Decimal("0.01")


@pytest.mark.parametrize("margin", ["100", "101", "-0.01"])
def test_rejects_invalid_margin(margin: str) -> None:
    with pytest.raises(ValueError):
        valid_input(margin_percent=margin)


@pytest.mark.parametrize(
    "field", ["materials_cost", "hours_worked", "hourly_rate", "other_expenses"]
)
def test_rejects_negative_cost_inputs(field: str) -> None:
    with pytest.raises(ValueError):
        valid_input(**{field: "-1"})


def test_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        valid_input(product_name="   ")


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        valid_input(hidden_fee="10")


def test_optional_height_accepts_positive_decimals_without_changing_price() -> None:
    without_height = calculate_price(valid_input())
    product = valid_input(height_cm="27.5")

    assert product.height_cm == Decimal("27.5")
    assert calculate_price(product) == without_height


@pytest.mark.parametrize("height", ["0", "-1", "NaN", "Infinity"])
def test_optional_height_rejects_non_positive_or_non_finite_values(height: str) -> None:
    with pytest.raises(ValueError):
        valid_input(height_cm=height)
