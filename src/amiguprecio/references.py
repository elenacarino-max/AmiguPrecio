"""Referencias comerciales validadas, sin inventar datos ausentes."""

from __future__ import annotations

import csv
import unicodedata
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

SHOP_URL = "https://sweetlavenderco.com"
LIVE_ENDPOINT = f"{SHOP_URL}/collections/amigurumi-toys/products.json"
DEFAULT_CATALOG = Path(__file__).parents[2] / "data" / "amigurumis_referencias.csv"


class MarketReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    features: list[str] = Field(default_factory=list, max_length=20)
    source_url: HttpUrl
    checked_at: datetime
    source_name: str = Field(min_length=1, max_length=100)
    provenance: Literal["live", "saved"]
    category: str | None = None
    size: str | None = None
    product_type: str | None = None

    @field_validator("price")
    @classmethod
    def finite_price(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("El precio debe ser finito")
        return value


class ReferenceSearchResult(BaseModel):
    query: str
    references: list[MarketReference] = Field(default_factory=list, max_length=3)
    errors: list[str] = Field(default_factory=list)
    used_fallback: bool = False


def load_saved_references(
    query: str,
    max_results: int = 3,
    catalog_path: Path = DEFAULT_CATALOG,
    currency: str | None = None,
) -> list[MarketReference]:
    """Busca en el catálogo guardado; nunca lo presenta como consulta en directo."""

    def normalized(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        return "".join(char for char in decomposed if not unicodedata.combining(char))

    alias_groups = {
        "muneca": {"muneca", "doll"},
        "peluche": {"peluche", "plush", "lovie", "comforter", "soft toy"},
        "animal": {"animal"},
        "amigurumi": {"amigurumi", "crochet"},
    }
    raw_terms = {normalized(term) for term in query.split() if term.strip()}
    terms: set[str] = set()
    for term in raw_terms:
        terms.update(alias_groups.get(term, {term}))
    requested_currency = currency.upper() if currency else None
    ranked: list[tuple[int, int, MarketReference]] = []
    with catalog_path.open(encoding="utf-8", newline="") as stream:
        records = csv.DictReader(stream)
        for position, record in enumerate(records):
            if requested_currency and record["currency"] != requested_currency:
                continue
            if record["product_type"] != "finished_product":
                continue
            searchable = normalized(
                " ".join(
                    [record["name"], record["category"], record["product_type"]]
                )
            )
            score = sum(1 for term in terms if term in searchable)
            size = record["size"].strip() or None
            reference = MarketReference(
                title=record["name"],
                price=record["price"],
                currency=record["currency"],
                features=[value for value in [record["category"], size] if value],
                source_url=record["url"],
                checked_at=record["checked_at"],
                source_name=record["store"],
                provenance="saved",
                category=record["category"],
                size=size,
                product_type=record["product_type"],
            )
            if score or not terms:
                ranked.append((score, position, reference))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[: min(max_results, 3)]]


def fetch_live_references(
    query: str, max_results: int = 3, timeout_seconds: float = 8.0
) -> list[MarketReference]:
    """Consulta el catálogo JSON público de una tienda Shopify permitida."""

    limit = min(max(max_results, 1), 3)
    headers = {"User-Agent": "AmiguPrecio/0.1 (educational market research)"}
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = client.get(LIVE_ENDPOINT, params={"limit": 30})
        response.raise_for_status()
    products = response.json().get("products", [])
    terms = {term.casefold() for term in query.split() if term.strip()}
    references: list[MarketReference] = []
    for product in products:
        title = product.get("title", "")
        product_type = product.get("product_type", "")
        product_kind = f"{title} {product_type}".casefold()
        if any(term in product_kind for term in ("pattern", "kit", "outfit", "clothes")):
            continue
        searchable = " ".join(
            [title, *product.get("tags", []), product_type]
        ).casefold()
        if terms and not any(term in searchable for term in terms):
            continue
        variants = product.get("variants") or []
        if not variants or not variants[0].get("price"):
            continue
        references.append(
            MarketReference(
                title=title,
                price=variants[0]["price"],
                currency="USD",
                features=[str(tag) for tag in product.get("tags", [])[:8]],
                source_url=f"{SHOP_URL}/products/{product['handle']}",
                checked_at=datetime.now().astimezone(),
                source_name="SweetLavenderCo public Shopify catalog",
                provenance="live",
                category=product_type or None,
                product_type="finished_product",
            )
        )
        if len(references) == limit:
            break
    return references


def search_references(
    query: str,
    max_results: int = 3,
    live: bool = True,
    currency: str | None = None,
) -> ReferenceSearchResult:
    """Busca en directo y usa datos guardados solo si la consulta falla o queda vacía."""

    errors: list[str] = []
    limit = min(max(max_results, 1), 3)
    requested_currency = currency.upper() if currency else None
    live_references: list[MarketReference] = []
    if live:
        try:
            live_references = fetch_live_references(query, max_results=limit)
            same_currency_live = [
                reference
                for reference in live_references
                if requested_currency is None or reference.currency == requested_currency
            ]
            if same_currency_live and len(same_currency_live) == limit:
                return ReferenceSearchResult(query=query, references=same_currency_live)
            if live_references and requested_currency and not same_currency_live:
                errors.append(
                    f"La fuente en directo no devolvió referencias en {requested_currency}."
                )
            errors.append(
                "La fuente en directo no devolvió suficientes referencias en la moneda solicitada."
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"Fuente en directo inaccesible: {type(exc).__name__}: {exc}")
    saved = load_saved_references(
        query,
        max_results=limit,
        currency=requested_currency,
    )
    if saved:
        return ReferenceSearchResult(
            query=query,
            references=saved,
            errors=errors,
            used_fallback=True,
        )
    return ReferenceSearchResult(
        query=query,
        references=live_references[:limit],
        errors=errors,
        used_fallback=not live,
    )
