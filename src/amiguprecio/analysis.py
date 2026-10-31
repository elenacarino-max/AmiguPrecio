"""Análisis reproducible con pandas y Matplotlib."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import matplotlib
import pandas as pd
from pydantic import BaseModel

from amiguprecio.models import PricingResult
from amiguprecio.references import MarketReference

matplotlib.use("Agg")
from matplotlib import pyplot as plt


class MarketStatistics(BaseModel):
    valid_reference_count: int
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    mean: Decimal | None = None
    median: Decimal | None = None
    calculated_price: Decimal
    comparable_currency: str | None = None


def calculate_market_statistics(
    pricing: PricingResult,
    references: list[MarketReference],
    calculated_currency: str = "EUR",
) -> MarketStatistics:
    comparable = [
        reference for reference in references if reference.currency == calculated_currency
    ]
    if not comparable:
        return MarketStatistics(valid_reference_count=0, calculated_price=pricing.calculated_price)
    series = pd.Series([float(reference.price) for reference in comparable], dtype="float64")
    return MarketStatistics(
        valid_reference_count=int(series.count()),
        minimum=Decimal(str(round(series.min(), 2))),
        maximum=Decimal(str(round(series.max(), 2))),
        mean=Decimal(str(round(series.mean(), 2))),
        median=Decimal(str(round(series.median(), 2))),
        calculated_price=pricing.calculated_price,
        comparable_currency=calculated_currency,
    )


def create_price_chart(
    pricing: PricingResult,
    references: list[MarketReference],
    output_path: Path,
    calculated_currency: str = "EUR",
) -> Path:
    comparable = [
        reference for reference in references if reference.currency == calculated_currency
    ]
    labels = [reference.title[:28] for reference in comparable] + ["Precio calculado"]
    values = [float(reference.price) for reference in comparable] + [
        float(pricing.calculated_price)
    ]
    colors = ["#6f8d7d"] * len(comparable) + ["#b94f3d"]
    frame = pd.DataFrame({"Producto": labels, "Precio": values})
    figure, axis = plt.subplots(figsize=(8, 4.5))
    axis.barh(frame["Producto"], frame["Precio"], color=colors)
    axis.set_xlabel(f"Precio ({calculated_currency})")
    axis.set_title("Precio calculado y referencias válidas")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=140)
    plt.close(figure)
    return output_path
