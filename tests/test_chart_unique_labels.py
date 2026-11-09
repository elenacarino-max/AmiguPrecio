"""Regresion: los titulos largos no deben ocultar barras del grafico."""

from decimal import Decimal

from matplotlib.axes import Axes

from amiguprecio import PricingInput, calculate_price
from amiguprecio.analysis import create_price_chart
from amiguprecio.references import MarketReference


def test_chart_shows_every_reference_when_titles_share_prefix(tmp_path, monkeypatch) -> None:
    base = MarketReference(
        title="Arte a Fio Amigurumi Inspirado em Arlequina",
        price="28.00",
        currency="EUR",
        source_url="https://example.com/product/0",
        checked_at="2026-11-09T12:00:00+01:00",
        source_name="Arte a Fio",
        provenance="serpapi_google_shopping",
    )
    references = [
        base.model_copy(
            update={
                "title": f"Arte a Fio Amigurumi Inspirado em variante {index}",
                "price": Decimal(20 + index),
                "source_url": f"https://example.com/product/{index}",
            }
        )
        for index in range(7)
    ]
    plotted_labels: list[str] = []
    original_barh = Axes.barh

    def record_labels(axis, y, width, **kwargs):
        plotted_labels.extend(y)
        return original_barh(axis, y, width, **kwargs)

    monkeypatch.setattr(Axes, "barh", record_labels)
    pricing = calculate_price(
        PricingInput(
            product_name="Muñeca",
            product_type="muñeca amigurumi",
            materials_cost="25",
            hours_worked="3.5",
            hourly_rate="20",
            other_expenses="5",
            margin_percent="20",
        )
    )

    output = create_price_chart(pricing, references, tmp_path / "barras.png")

    assert output.is_file()
    assert len(plotted_labels) == 8  # 7 referencias y el precio calculado
    assert len(set(plotted_labels)) == 8
    assert plotted_labels[-1] == "Precio calculado"
