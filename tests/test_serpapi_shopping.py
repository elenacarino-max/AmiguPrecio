from datetime import datetime
from decimal import Decimal

import httpx
import pytest

from amiguprecio.serpapi_shopping import (
    SerpApiConfigurationError,
    calculate_shopping_statistics,
    classify_comparability,
    parse_shopping_results,
    search_google_shopping,
)

CHECKED_AT = datetime.fromisoformat("2026-11-05T10:00:00+01:00")


def _record(**changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "title": "Hello Kitty amigurumi hecho a mano 25 cm",
        "source": "Artesanía Ejemplo",
        "price": "49,90 €",
        "extracted_price": 49.9,
        "product_link": "https://www.google.com/shopping/product/123?gl=es",
        "thumbnail": "https://images.example.com/hello-kitty.webp",
    }
    record.update(changes)
    return record


def test_parser_keeps_only_unambiguous_finished_products() -> None:
    payload = {
        "shopping_results": [
            _record(),
            _record(title="Patrón PDF Hello Kitty amigurumi", product_link="https://x.test/1"),
            _record(title="Kit crochet Hello Kitty", product_link="https://x.test/2"),
            _record(title="Llavero amigurumi Hello Kitty", product_link="https://x.test/3"),
            _record(price="Desde 12 €", extracted_price=12, product_link="https://x.test/4"),
        ]
    }

    raw_count, products = parse_shopping_results(payload, checked_at=CHECKED_AT)

    assert raw_count == 5
    assert len(products) == 1
    assert products[0].price == Decimal("49.90")
    assert products[0].currency == "EUR"
    assert products[0].height_cm == Decimal(25)
    assert products[0].provenance == "serpapi_google_shopping"
    assert str(products[0].thumbnail_url).startswith("https://images.example.com/")


def test_parser_does_not_invent_height_from_multiple_dimensions() -> None:
    payload = {
        "shopping_results": [
            _record(title="Hello Kitty amigurumi hecho a mano 25 x 18 x 12 cm")
        ]
    }

    _, products = parse_shopping_results(payload, checked_at=CHECKED_AT)

    assert products[0].size is None
    assert products[0].height_cm is None


def test_comparability_requires_theme_height_and_manufacturing_evidence() -> None:
    payload = {
        "shopping_results": [
            _record(),
            _record(
                title="Hello Kitty amigurumi hecho a mano 40 cm",
                product_link="https://x.test/large",
            ),
            _record(
                title="Hello Kitty amigurumi 25 cm",
                product_link="https://x.test/unknown-making",
            ),
            _record(
                title="Gato amigurumi hecho a mano 25 cm",
                product_link="https://x.test/cat",
            ),
        ]
    }
    _, products = parse_shopping_results(payload, checked_at=CHECKED_AT)

    comparisons = classify_comparability(
        products,
        target_theme="Hello Kitty",
        target_height_cm=Decimal(25),
    )

    assert [item.status for item in comparisons] == [
        "comparable",
        "not_comparable",
        "undetermined",
        "undetermined",
    ]


def test_statistics_separate_eur_sample_from_comparable_subset() -> None:
    payload = {
        "shopping_results": [
            _record(extracted_price=40, price="40 €"),
            _record(
                title="Hello Kitty amigurumi hecho a mano 40 cm",
                extracted_price=60,
                price="60 €",
                product_link="https://x.test/large",
            ),
            _record(
                extracted_price=50,
                price="$50",
                product_link="https://x.test/usd",
            ),
        ]
    }
    _, products = parse_shopping_results(payload, checked_at=CHECKED_AT)
    comparisons = classify_comparability(
        products, target_theme="Hello Kitty", target_height_cm=Decimal(25)
    )

    statistics = calculate_shopping_statistics(products, comparisons)

    assert statistics.eur_product_count == 2
    assert statistics.eur_mean == Decimal("50.00")
    assert statistics.comparable_eur_count == 1
    assert statistics.comparable_eur_mean == Decimal("40.00")


def test_missing_key_does_not_contact_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    with pytest.raises(SerpApiConfigurationError, match="no está configurada"):
        search_google_shopping("consulta", target_theme="Hello Kitty")


def test_request_uses_spain_spanish_and_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_get(self: httpx.Client, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            request=request,
            json={"shopping_results": [_record()]},
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = search_google_shopping(
        "Hello Kitty amigurumi crochet hecho a mano",
        target_theme="Hello Kitty",
        target_height_cm=Decimal(25),
        api_key="test-secret",
    )

    assert len(calls) == 1
    assert calls[0]["params"] == {
        "engine": "google_shopping",
        "q": "Hello Kitty amigurumi crochet hecho a mano",
        "gl": "es",
        "hl": "es",
        "api_key": "test-secret",
    }
    assert result.searches_used == 1
    assert result.api_product_count == 1
