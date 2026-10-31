from decimal import Decimal

from amiguprecio import PricingInput, calculate_price
from amiguprecio.analysis import calculate_market_statistics, create_price_chart
from amiguprecio.references import load_saved_references


def pricing_result():
    return calculate_price(
        PricingInput(
            product_name="Luna",
            product_type="Muñeca",
            materials_cost="12.50",
            hours_worked="5",
            hourly_rate="10",
            other_expenses="2.50",
            margin_percent="20",
        )
    )


def test_statistics_use_valid_references() -> None:
    stats = calculate_market_statistics(
        pricing_result(), load_saved_references("amigurumi"), calculated_currency="USD"
    )

    assert stats.valid_reference_count == 3
    assert stats.minimum == Decimal("35.0")
    assert stats.maximum == Decimal("41.0")
    assert stats.mean == Decimal("37.0")
    assert stats.median == Decimal("35.0")


def test_statistics_handle_no_references() -> None:
    stats = calculate_market_statistics(pricing_result(), [])

    assert stats.valid_reference_count == 0
    assert stats.mean is None


def test_statistics_do_not_mix_currencies() -> None:
    stats = calculate_market_statistics(pricing_result(), load_saved_references("amigurumi"))

    assert stats.valid_reference_count == 0
    assert stats.comparable_currency is None


def test_chart_is_created(tmp_path) -> None:
    output = create_price_chart(
        pricing_result(),
        load_saved_references("amigurumi"),
        tmp_path / "comparison.png",
        calculated_currency="USD",
    )

    assert output.exists()
    assert output.stat().st_size > 1_000
