from decimal import Decimal

from amiguprecio import PricingInput, calculate_price
from amiguprecio.analysis import (
    calculate_market_statistics,
    create_price_chart,
    evaluate_commercial_comparability,
)
from amiguprecio.references import MarketReference, load_saved_references


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
        pricing_result(),
        load_saved_references("amigurumi", currency="USD"),
        calculated_currency="USD",
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


def test_height_improves_comparability_without_becoming_sufficient_alone() -> None:
    product = PricingInput(
        product_name="Luna",
        product_type="Muñeca amigurumi",
        height_cm="30",
        materials_cost="12.50",
        hours_worked="5",
        hourly_rate="10",
        other_expenses="2.50",
        margin_percent="20",
    )
    reference = MarketReference.model_validate(
        {
            "title": "Muñeca artesanal",
            "price": "45.00",
            "currency": "EUR",
            "features": [],
            "source_url": "https://example.com/doll",
            "checked_at": "2026-11-05T09:00:00+01:00",
            "source_name": "Tienda",
            "provenance": "saved",
            "category": "muñeca",
            "size": "30 cm",
            "product_type": "finished_product",
        }
    )

    result = evaluate_commercial_comparability(product, [reference])

    assert result.references[0].status == "undetermined"
    assert "características" in result.references[0].reason


def test_multiple_unlabelled_dimensions_are_not_assumed_to_be_height() -> None:
    product = PricingInput(
        product_name="Luna",
        product_type="Muñeca amigurumi",
        height_cm="15",
        materials_cost="12.50",
        hours_worked="5",
        hourly_rate="10",
        other_expenses="2.50",
        margin_percent="20",
    )
    reference = MarketReference.model_validate(
        {
            "title": "Muñeca artesanal",
            "price": "45.00",
            "currency": "EUR",
            "features": ["muñeca"],
            "source_url": "https://example.com/doll",
            "checked_at": "2026-11-05T09:00:00+01:00",
            "source_name": "Tienda",
            "provenance": "saved",
            "category": "muñeca",
            "size": "15 x 9 x 9 cm",
            "product_type": "finished_product",
        }
    )

    result = evaluate_commercial_comparability(product, [reference])

    assert result.references[0].status == "undetermined"
    assert "altura inequívoca" in result.references[0].reason
