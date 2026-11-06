import logging
import traceback
from datetime import datetime
from decimal import Decimal

import httpx
import pytest

from amiguprecio.serpapi_shopping import (
    SerpApiConfigurationError,
    _suppress_sensitive_http_logging,
    calculate_shopping_statistics,
    classify_comparability,
    parse_shopping_results,
    rank_and_deduplicate_products,
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
            _record(
                title="Pack Hello Kitty 99, My Melody y Amigurumi",
                product_link="https://x.test/pack",
            ),
            _record(price="Desde 12 €", extracted_price=12, product_link="https://x.test/4"),
        ]
    }

    raw_count, products = parse_shopping_results(payload, checked_at=CHECKED_AT)

    assert raw_count == 6
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


def test_sensitive_http_url_logging_is_suppressed_and_restored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("httpx")
    original_level = logger.level
    with caplog.at_level(
        logging.INFO, logger="httpx"
    ), _suppress_sensitive_http_logging():
        logger.info("https://serpapi.com/search.json?api_key=unit-test-secret")

    assert "unit-test-secret" not in caplog.text
    assert logger.level == original_level


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("429", "HTTP 429"),
        ("timeout", "ReadTimeout"),
        ("network", "ConnectError"),
        ("invalid_json", "JSON inválido"),
    ],
)
def test_provider_failures_never_retain_key_in_exception_or_traceback(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected: str,
) -> None:
    fake_key = "unit-test-secret-never-real"

    def fake_get(self: httpx.Client, url: str, **kwargs: object) -> httpx.Response:
        request = httpx.Request("GET", url, params=kwargs["params"])
        if failure == "429":
            return httpx.Response(429, request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if failure == "network":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, request=request, content=b"not-json")

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    with pytest.raises(RuntimeError, match=expected) as captured:
        search_google_shopping(
            "consulta",
            target_theme="Hello Kitty",
            api_key=fake_key,
        )

    rendered = "".join(
        traceback.format_exception(
            type(captured.value), captured.value, captured.value.__traceback__
        )
    )
    assert fake_key not in str(captured.value)
    assert fake_key not in repr(captured.value)
    assert fake_key not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_provider_error_payload_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_key = "unit-test-secret-never-real"

    def fake_get(self: httpx.Client, url: str, **kwargs: object) -> httpx.Response:
        request = httpx.Request("GET", url, params=kwargs["params"])
        return httpx.Response(
            200,
            request=request,
            json={"error": f"invalid api_key {fake_key}"},
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    with pytest.raises(RuntimeError, match="error de proveedor") as captured:
        search_google_shopping(
            "consulta",
            target_theme="Hello Kitty",
            api_key=fake_key,
        )

    assert fake_key not in str(captured.value)


def test_real_cases_are_ranked_by_theme_and_duplicate_offers_are_removed() -> None:
    payload = {
        "shopping_results": [
            _record(
                title="Peluche de gato de ganchillo hecho a mano amigurumi",
                product_link="https://x.test/generic",
            ),
            _record(product_id="hello-kitty-1"),
            _record(
                product_id="hello-kitty-1",
                source="Otra oferta del mismo producto",
                product_link="https://x.test/duplicate",
            ),
            _record(
                title="Hello Kitty amigurumi hecho a mano 25 cm",
                source="Artesanía Ejemplo",
                extracted_price=49.9,
                product_link="https://x.test/same-offer",
            ),
        ]
    }
    _, parsed = parse_shopping_results(payload, checked_at=CHECKED_AT)

    products = rank_and_deduplicate_products(parsed, target_theme="Hello Kitty")

    assert len(products) == 2
    assert products[0].title.startswith("Hello Kitty")
    assert products[1].title.startswith("Peluche de gato")
