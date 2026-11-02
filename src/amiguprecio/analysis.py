"""Análisis reproducible con pandas y Matplotlib."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Literal

import matplotlib
import pandas as pd
from pydantic import BaseModel

from amiguprecio.models import PricingInput, PricingResult
from amiguprecio.references import MarketReference

matplotlib.use("Agg")
from matplotlib import pyplot as plt


class MarketStatistics(BaseModel):
    """Estadísticas de referencias que comparten moneda, no comparabilidad comercial."""

    valid_reference_count: int
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    mean: Decimal | None = None
    median: Decimal | None = None
    calculated_price: Decimal
    comparable_currency: str | None = None


class ReferenceComparability(BaseModel):
    title: str
    status: Literal["comparable", "not_comparable", "undetermined"]
    reason: str


class CommercialComparability(BaseModel):
    """Evaluación prudente separada de las estadísticas por moneda."""

    currency_reference_count: int
    directly_comparable_count: int
    not_comparable_count: int
    undetermined_count: int
    sample_is_heterogeneous: bool
    conclusion: str
    limitations: list[str]
    references: list[ReferenceComparability]


_TYPE_GROUPS = {
    "doll": {"doll", "muneca", "kitty"},
    "comforter": {"comforter", "doudou", "lovie"},
    "rattle": {"rattle", "sonajero"},
    "plush": {"plush", "plushie", "peluche", "soft"},
}
_GENERIC_TERMS = {
    "amigurumi",
    "artesanal",
    "crochet",
    "doll",
    "doudou",
    "finished",
    "ganchillo",
    "handmade",
    "juguete",
    "lovie",
    "muneca",
    "peluche",
    "product",
    "plush",
    "plushie",
    "rattle",
    "sonajero",
    "soft",
    "comforter",
    "tejido",
    "toy",
}


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalized(value)))


def _product_kind(value: str) -> str | None:
    terms = _tokens(value)
    for kind, aliases in _TYPE_GROUPS.items():
        if terms & aliases:
            return kind
    return None


def _size_in_cm(value: str | None) -> Decimal | None:
    if not value:
        return None
    match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*cm\b", _normalized(value))
    return Decimal(match.group(1).replace(",", ".")) if match else None


def evaluate_commercial_comparability(
    product: PricingInput,
    references: list[MarketReference],
    calculated_currency: str = "EUR",
) -> CommercialComparability:
    """Clasifica referencias sin equiparar moneda con equivalencia comercial."""

    same_currency = [
        reference for reference in references if reference.currency == calculated_currency
    ]
    target_text = f"{product.product_name} {product.product_type}"
    target_kind = _product_kind(target_text)
    target_size = _size_in_cm(target_text)
    target_features = _tokens(target_text) - _GENERIC_TERMS
    results: list[ReferenceComparability] = []

    for reference in same_currency:
        reference_text = " ".join(
            filter(
                None,
                [
                    reference.title,
                    reference.category,
                    reference.product_type,
                    *reference.features,
                ],
            )
        )
        reference_kind = _product_kind(reference_text)
        reference_size = _size_in_cm(reference.size)
        reference_features = _tokens(reference_text) - _GENERIC_TERMS

        if target_kind and reference_kind and target_kind != reference_kind:
            status = "not_comparable"
            reason = "El tipo de producto no coincide con el producto valorado."
        elif target_kind is None or reference_kind is None:
            status = "undetermined"
            reason = "No hay información suficiente para contrastar el tipo de producto."
        elif target_size is None or reference_size is None:
            status = "undetermined"
            reason = "Falta el tamaño del producto o de la referencia."
        elif target_size != reference_size:
            status = "not_comparable"
            reason = "El tamaño publicado no coincide con el producto valorado."
        elif not (target_features & reference_features):
            status = "undetermined"
            reason = "No hay características descriptivas suficientes para una comparación directa."
        else:
            status = "comparable"
            reason = "Coinciden tipo, tamaño publicado y al menos una característica descriptiva."
        results.append(
            ReferenceComparability(title=reference.title, status=status, reason=reason)
        )

    directly_comparable = sum(item.status == "comparable" for item in results)
    not_comparable = sum(item.status == "not_comparable" for item in results)
    undetermined = sum(item.status == "undetermined" for item in results)
    categories = {
        _normalized(reference.category)
        for reference in same_currency
        if reference.category
    }
    heterogeneous = len(categories) > 1 or not_comparable > 0 or undetermined > 0
    limitations: list[str] = []
    if same_currency and heterogeneous:
        limitations.append(
            f"Las estadísticas describen una muestra {calculated_currency} heterogénea; "
            "compartir moneda no demuestra comparabilidad comercial."
        )
    if undetermined:
        limitations.append(
            "Faltan datos de tamaño o características para confirmar comparaciones directas."
        )
    if not_comparable:
        limitations.append(
            "La muestra contiene productos de tipo o tamaño no equivalente."
        )
    if 0 < directly_comparable < 3:
        limitations.append(
            "La muestra comercialmente comparable es demasiado pequeña para inferir posicionamiento."
        )
    if directly_comparable < 3:
        conclusion = "No es posible determinar el posicionamiento de mercado con estas referencias."
    elif heterogeneous:
        conclusion = (
            "La muestra contiene algunas referencias próximas, pero no permite una "
            "comparación comercial directa del conjunto."
        )
    else:
        conclusion = (
            "Las referencias cumplen los criterios descriptivos disponibles; sus precios "
            "siguen siendo precios anunciados, no evidencia de ventas o demanda."
        )
    return CommercialComparability(
        currency_reference_count=len(same_currency),
        directly_comparable_count=directly_comparable,
        not_comparable_count=not_comparable,
        undetermined_count=undetermined,
        sample_is_heterogeneous=heterogeneous,
        conclusion=conclusion,
        limitations=limitations,
        references=results,
    )


def calculate_market_statistics(
    pricing: PricingResult,
    references: list[MarketReference],
    calculated_currency: str = "EUR",
) -> MarketStatistics:
    same_currency = [
        reference for reference in references if reference.currency == calculated_currency
    ]
    if not same_currency:
        return MarketStatistics(valid_reference_count=0, calculated_price=pricing.calculated_price)
    series = pd.Series([float(reference.price) for reference in same_currency], dtype="float64")
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
    same_currency = [
        reference for reference in references if reference.currency == calculated_currency
    ]
    labels = [reference.title[:28] for reference in same_currency] + ["Precio calculado"]
    values = [float(reference.price) for reference in same_currency] + [
        float(pricing.calculated_price)
    ]
    colors = ["#6f8d7d"] * len(same_currency) + ["#b94f3d"]
    frame = pd.DataFrame({"Producto": labels, "Precio": values})
    figure, axis = plt.subplots(figsize=(8, 4.5))
    axis.barh(frame["Producto"], frame["Precio"], color=colors)
    axis.set_xlabel(f"Precio ({calculated_currency})")
    axis.set_title(f"Precio calculado y muestra en {calculated_currency}")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=140)
    plt.close(figure)
    return output_path
