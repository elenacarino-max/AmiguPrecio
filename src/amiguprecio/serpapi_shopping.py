"""Adaptador aislado para investigar productos en Google Shopping mediante SerpApi.

Los resultados representan anuncios/listados agregados por Google Shopping. No implican
que AmiguPrecio haya verificado directamente la ficha de la tienda ni que exista una venta.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
SERPAPI_PROVENANCE = "serpapi_google_shopping"


@contextmanager
def _suppress_sensitive_http_logging() -> Iterator[None]:
    """Evita que el parámetro de autenticación aparezca en logs de URL."""

    loggers = [logging.getLogger("httpx"), logging.getLogger("httpcore")]
    previous_levels = [logger.level for logger in loggers]
    try:
        for logger in loggers:
            logger.setLevel(logging.WARNING)
        yield
    finally:
        for logger, level in zip(loggers, previous_levels, strict=True):
            logger.setLevel(level)


class SerpApiConfigurationError(RuntimeError):
    """La búsqueda en línea no está configurada de forma segura."""


class ShoppingProduct(BaseModel):
    """Producto terminado publicado en Google Shopping y normalizado localmente."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    store: str = Field(min_length=1, max_length=150)
    url: HttpUrl
    thumbnail_url: HttpUrl | None = None
    checked_at: datetime
    provenance: Literal["serpapi_google_shopping"] = SERPAPI_PROVENANCE
    product_type: Literal["finished_product"] = "finished_product"
    size: str | None = None
    height_cm: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    handmade_claimed: bool = False
    provider_product_id: str | None = None

    @field_validator("price", "height_cm")
    @classmethod
    def finite_decimals(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("Los valores decimales deben ser finitos")
        return value


class ProductComparability(BaseModel):
    title: str
    status: Literal["comparable", "not_comparable", "undetermined"]
    reason: str


class ShoppingSearchResult(BaseModel):
    query: str
    api_product_count: int = 0
    products: list[ShoppingProduct] = Field(default_factory=list)
    comparability: list[ProductComparability] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    searches_used: int = 0


class ShoppingStatistics(BaseModel):
    """Separa toda la muestra EUR de la submuestra realmente comparable."""

    eur_product_count: int
    comparable_eur_count: int
    eur_mean: Decimal | None = None
    comparable_eur_mean: Decimal | None = None


_EXCLUDED_TERMS = {
    "accessory",
    "accesorio",
    "clothes",
    "clothing",
    "outfit",
    "pack",
    "keychain",
    "llavero",
    "kit",
    "pattern",
    "patron",
    "pdf",
    "tutorial",
}
_INDUSTRIAL_TERMS = {
    "funko",
    "lego",
    "plastic",
    "plastico",
    "vinyl",
    "vinilo",
}
_FINISHED_SIGNALS = {
    "amigurumi",
    "crochet doll",
    "crochet plush",
    "crochet toy",
    "muneca de ganchillo",
    "peluche de ganchillo",
}
_HANDMADE_SIGNALS = {
    "artesanal",
    "hand made",
    "handmade",
    "hecho a mano",
}


def _normalized(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _words(value: object) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalized(value)))


def _product_text(record: Mapping[str, Any]) -> str:
    extensions = record.get("extensions") or []
    if not isinstance(extensions, list):
        extensions = []
    return " ".join(
        str(value)
        for value in [record.get("title"), record.get("snippet"), *extensions]
        if value
    )


def _is_finished_product(record: Mapping[str, Any]) -> bool:
    text = _normalized(_product_text(record))
    terms = _words(text)
    if terms & (_EXCLUDED_TERMS | _INDUSTRIAL_TERMS):
        return False
    return any(signal in text for signal in _FINISHED_SIGNALS)


def _currency_from_price(price_text: object) -> str | None:
    text = str(price_text or "").upper()
    if "€" in text or re.search(r"\bEUR\b", text):
        return "EUR"
    if "$" in text or re.search(r"\bUSD\b", text):
        return "USD"
    if "£" in text or re.search(r"\bGBP\b", text):
        return "GBP"
    return None


def _unambiguous_price(record: Mapping[str, Any]) -> tuple[Decimal, str] | None:
    price_text = str(record.get("price") or "")
    normalized = _normalized(price_text)
    ambiguous_markers = ("desde", "from", "a partir", "/mes", "/month", " - ")
    if any(marker in normalized for marker in ambiguous_markers) or record.get("installment"):
        return None
    currency = _currency_from_price(price_text)
    raw_price = record.get("extracted_price")
    if currency is None or raw_price is None or isinstance(raw_price, bool):
        return None
    try:
        price = Decimal(str(raw_price))
    except InvalidOperation:
        return None
    if not price.is_finite() or price <= 0:
        return None
    return price.quantize(Decimal("0.01")), currency


def _extract_height(text: str) -> tuple[str | None, Decimal | None]:
    normalized = _normalized(text)
    if re.search(r"\d+(?:[.,]\d+)?\s*(?:cm)?\s*[x×]\s*\d", normalized):
        return None, None
    matches = re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*cm\b", normalized)
    if len(matches) != 1:
        return None, None
    value = Decimal(matches[0].replace(",", "."))
    if not value.is_finite() or value <= 0:
        return None, None
    return f"{value.normalize()} cm", value


def parse_shopping_results(
    payload: Mapping[str, Any], *, checked_at: datetime | None = None
) -> tuple[int, list[ShoppingProduct]]:
    """Normaliza una respuesta sin descargar imágenes ni visitar fichas de tiendas."""

    raw_results = payload.get("shopping_results") or []
    if not isinstance(raw_results, list):
        raise TypeError("shopping_results no es una lista")
    timestamp = checked_at or datetime.now().astimezone()
    products: list[ShoppingProduct] = []
    for raw in raw_results:
        if not isinstance(raw, Mapping) or not _is_finished_product(raw):
            continue
        parsed_price = _unambiguous_price(raw)
        title = str(raw.get("title") or "").strip()
        store = str(raw.get("source") or "").strip()
        url = raw.get("product_link")
        if parsed_price is None or not title or not store or not url:
            continue
        size, height = _extract_height(_product_text(raw))
        text = _normalized(_product_text(raw))
        product = ShoppingProduct(
            title=title,
            price=parsed_price[0],
            currency=parsed_price[1],
            store=store,
            url=url,
            thumbnail_url=raw.get("thumbnail") or None,
            checked_at=timestamp,
            size=size,
            height_cm=height,
            handmade_claimed=any(signal in text for signal in _HANDMADE_SIGNALS),
            provider_product_id=(
                str(raw["product_id"]).strip() if raw.get("product_id") else None
            ),
        )
        products.append(product)
    return len(raw_results), products


def rank_and_deduplicate_products(
    products: list[ShoppingProduct], *, target_theme: str, limit: int = 10
) -> list[ShoppingProduct]:
    """Prioriza el personaje solicitado y elimina ofertas repetidas de forma estable."""

    theme_terms = _words(target_theme)
    ranked: list[tuple[int, int, ShoppingProduct]] = []
    seen_product_ids: set[str] = set()
    seen_offers: set[tuple[object, ...]] = set()
    for position, product in enumerate(products):
        offer_identity = (
            _normalized(product.title),
            _normalized(product.store),
            product.price,
            product.currency,
        )
        if (
            product.provider_product_id in seen_product_ids
            if product.provider_product_id
            else False
        ) or offer_identity in seen_offers:
            continue
        if product.provider_product_id:
            seen_product_ids.add(product.provider_product_id)
        seen_offers.add(offer_identity)
        terms = _words(product.title)
        theme_score = 4 if theme_terms and theme_terms.issubset(terms) else 0
        evidence_score = int(product.height_cm is not None) + int(product.handmade_claimed)
        ranked.append((theme_score + evidence_score, position, product))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[: min(max(limit, 1), 10)]]


def classify_comparability(
    products: list[ShoppingProduct],
    *,
    target_theme: str,
    target_height_cm: Decimal | None,
    handmade_required: bool = True,
) -> list[ProductComparability]:
    """Clasifica con prudencia: una coincidencia aislada nunca basta."""

    theme_terms = _words(target_theme)
    results: list[ProductComparability] = []
    for product in products:
        product_terms = _words(product.title)
        if theme_terms and not theme_terms.issubset(product_terms):
            status = "undetermined"
            reason = "El título no confirma el personaje o tema completo solicitado."
        elif target_height_cm is not None and product.height_cm is not None:
            difference = abs(product.height_cm - target_height_cm) / target_height_cm
            if difference > Decimal("0.15"):
                status = "not_comparable"
                reason = "La altura publicada difiere más de un 15 % del producto objetivo."
            elif handmade_required and not product.handmade_claimed:
                status = "undetermined"
                reason = "La ficha agregada no confirma que el producto sea hecho a mano."
            else:
                status = "comparable"
                reason = (
                    "Coinciden el tipo terminado, el tema, una altura similar y la "
                    "declaración de fabricación disponible."
                )
        elif target_height_cm is not None:
            status = "undetermined"
            reason = "La publicación no aporta una altura inequívoca."
        elif handmade_required and not product.handmade_claimed:
            status = "undetermined"
            reason = "La ficha agregada no confirma que el producto sea hecho a mano."
        else:
            status = "undetermined"
            reason = "No hay suficientes atributos para confirmar equivalencia comercial."
        results.append(ProductComparability(title=product.title, status=status, reason=reason))
    return results


def calculate_shopping_statistics(
    products: list[ShoppingProduct], comparability: list[ProductComparability]
) -> ShoppingStatistics:
    if len(products) != len(comparability):
        raise ValueError("Cada producto debe tener una clasificación de comparabilidad")
    eur = [product.price for product in products if product.currency == "EUR"]
    comparable = [
        product.price
        for product, assessment in zip(products, comparability, strict=True)
        if product.currency == "EUR" and assessment.status == "comparable"
    ]

    def mean(values: list[Decimal]) -> Decimal | None:
        if not values:
            return None
        return (sum(values) / Decimal(len(values))).quantize(Decimal("0.01"))

    return ShoppingStatistics(
        eur_product_count=len(eur),
        comparable_eur_count=len(comparable),
        eur_mean=mean(eur),
        comparable_eur_mean=mean(comparable),
    )


def search_google_shopping(
    query: str,
    *,
    target_theme: str,
    target_height_cm: Decimal | None = None,
    api_key: str | None = None,
    timeout_seconds: float = 8.0,
) -> ShoppingSearchResult:
    """Realiza exactamente una consulta; nunca incluye la clave en mensajes de error."""

    secret = api_key or os.getenv("SERPAPI_API_KEY")
    if not secret:
        raise SerpApiConfigurationError("SERPAPI_API_KEY no está configurada")
    try:
        with (
            _suppress_sensitive_http_logging(),
            httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client,
        ):
            response = client.get(
                SERPAPI_ENDPOINT,
                params={
                    "engine": "google_shopping",
                    "q": query,
                    "gl": "es",
                    "hl": "es",
                    "api_key": secret,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise RuntimeError("SerpApi devolvió HTTP 429; cuota o frecuencia limitada") from exc
        raise RuntimeError(f"SerpApi devolvió HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"No se pudo consultar SerpApi: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise RuntimeError("SerpApi devolvió JSON inválido") from exc
    if not isinstance(payload, Mapping):
        raise TypeError("SerpApi devolvió una respuesta inesperada")
    if payload.get("error"):
        raise RuntimeError("SerpApi devolvió un error de proveedor")
    raw_count, parsed_products = parse_shopping_results(payload)
    products = rank_and_deduplicate_products(
        parsed_products,
        target_theme=target_theme,
        limit=10,
    )
    comparisons = classify_comparability(
        products,
        target_theme=target_theme,
        target_height_cm=target_height_cm,
    )
    return ShoppingSearchResult(
        query=query,
        api_product_count=raw_count,
        products=products,
        comparability=comparisons,
        searches_used=1,
    )
