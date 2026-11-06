"""Regresión offline: enlaces largos de Google Shopping en el cálculo Python."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from amiguprecio.agents import ToolMarketReference
from amiguprecio.models import PricingInput
from amiguprecio.references import MarketReference
from amiguprecio.workflow import run_deterministic_analysis


def test_shopping_reference_preserves_title_and_source_with_long_url() -> None:
    url = "https://www.google.com/shopping/product/" + "x" * 250
    item = ToolMarketReference(
        title="Hello Kitty tejida a mano",
        source_name="Tienda artesanal",
        source_url=url,
        price="24.50",
        currency="EUR",
        checked_at="2026-11-06T12:00:00+00:00",
        provenance="serpapi_google_shopping",
    )
    reference = item.to_domain()
    assert reference.title == "Hello Kitty tejida a mano"
    assert reference.source_name == "Tienda artesanal"
    assert str(reference.source_url) == url


def test_legacy_tool_reference_without_new_fields_still_works() -> None:
    item = ToolMarketReference(
        source_url="https://www.example.com/item",
        price="24.50",
        currency="EUR",
        checked_at="2026-11-06T12:00:00+00:00",
        provenance="saved",
    )
    reference = item.to_domain()
    assert reference.title == "www.example.com"
    assert reference.source_name == "www.example.com"


def test_ten_shopping_references_complete_python_calculation(tmp_path: Path) -> None:
    product = PricingInput(
        product_name="Hello Kitty",
        product_type="muñeca",
        height_cm="25",
        materials_cost="20",
        hours_worked="1.5",
        hourly_rate="20",
        other_expenses="1.50",
        margin_percent="20",
    )
    refs = [
        MarketReference(
            title=f"Hello Kitty amigurumi {i}",
            price=Decimal("12.00") + i,
            currency="EUR",
            source_url="https://www.google.com/shopping/product/"
            + str(i)
            + "x" * 250,
            checked_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
            source_name=f"Tienda {i}",
            provenance="serpapi_google_shopping",
            category="muñeca",
            product_type="finished_product",
        )
        for i in range(10)
    ]
    result = run_deterministic_analysis(product, refs, tmp_path / "chart.png")
    assert result.pricing.production_cost == Decimal("51.50")
    assert result.pricing.calculated_price == Decimal("64.38")
    assert result.statistics.valid_reference_count == 10
    assert [ref.title for ref in result.references] == [ref.title for ref in refs]
    assert Path(result.chart_path).is_file()
