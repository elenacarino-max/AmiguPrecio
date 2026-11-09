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
    comparable_mean: Decimal | None = None
    comparable_median: Decimal | None = None
    comparable_currency: str | None = None


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


def _height_in_cm(value: str | None) -> Decimal | None:
    """Extrae solo alturas inequívocas; no interpreta listas de dimensiones."""

    if not value:
        return None
    normalized = _normalized(value).strip()
    if " x " in normalized or re.search(r"\d\s*[x×]\s*\d", normalized):
        return None
    single = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*cm", normalized)
    if single:
        return Decimal(single.group(1).replace(",", "."))
    labelled = re.search(
        r"(?:altura|alto|height|high|tall)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*cm\b|"
        r"\b(\d+(?:[.,]\d+)?)\s*cm\s*(?:de\s+alto|high|tall)\b",
        normalized,
    )
    if labelled:
        raw_value = labelled.group(1) or labelled.group(2)
        return Decimal(raw_value.replace(",", "."))
    return None


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
    target_height = product.height_cm
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
        reference_height = _height_in_cm(reference.size)
        reference_features = _tokens(reference_text) - _GENERIC_TERMS

        if reference.comparability_status is not None:
            status = reference.comparability_status
            reason = reference.comparability_reason or (
                "Clasificación determinista conservada desde la fuente de descubrimiento."
            )
        elif target_kind and reference_kind and target_kind != reference_kind:
            status = "not_comparable"
            reason = "El tipo de producto no coincide con el producto valorado."
        elif target_kind is None or reference_kind is None:
            status = "undetermined"
            reason = "No hay información suficiente para contrastar el tipo de producto."
        elif target_height is None or reference_height is None:
            status = "undetermined"
            reason = "Falta una altura inequívoca del producto o de la referencia."
        elif target_height != reference_height:
            status = "not_comparable"
            reason = "La altura publicada no coincide con el producto valorado."
        elif not (target_features & reference_features):
            status = "undetermined"
            reason = "No hay características descriptivas suficientes para una comparación directa."
        else:
            status = "comparable"
            reason = "Coinciden tipo, altura publicada y al menos una característica descriptiva."
        results.append(ReferenceComparability(title=reference.title, status=status, reason=reason))

    directly_comparable = sum(item.status == "comparable" for item in results)
    not_comparable = sum(item.status == "not_comparable" for item in results)
    undetermined = sum(item.status == "undetermined" for item in results)
    categories = {
        _normalized(reference.category) for reference in same_currency if reference.category
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
            "Faltan datos inequívocos de altura o características para confirmar comparaciones directas."
        )
    if not_comparable:
        limitations.append("La muestra contiene productos de tipo o altura no equivalente.")
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
    comparable_prices = [
        reference.price
        for reference, result in zip(same_currency, results, strict=True)
        if result.status == "comparable"
    ]
    comparable_mean = None
    comparable_median = None
    if comparable_prices:
        comparable_mean = (
            sum(comparable_prices) / Decimal(len(comparable_prices))
        ).quantize(Decimal("0.01"))
        ordered = sorted(comparable_prices)
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            comparable_median = ordered[midpoint]
        else:
            comparable_median = (
                (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)
            ).quantize(Decimal("0.01"))
    return CommercialComparability(
        currency_reference_count=len(same_currency),
        directly_comparable_count=directly_comparable,
        not_comparable_count=not_comparable,
        undetermined_count=undetermined,
        sample_is_heterogeneous=heterogeneous,
        conclusion=conclusion,
        limitations=limitations,
        references=results,
        comparable_mean=comparable_mean,
        comparable_median=comparable_median,
        comparable_currency=calculated_currency if comparable_prices else None,
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
    labels = [
        f"{index}. "
        + (
            reference.source_name
            if reference.title.startswith(("http://", "https://"))
            else reference.title
        )[:28]
        for index, reference in enumerate(same_currency, start=1)
    ] + ["Precio calculado"]
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
