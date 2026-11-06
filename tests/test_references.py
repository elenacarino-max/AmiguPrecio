from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from amiguprecio.references import (
    MarketReference,
    build_market_query,
    load_saved_references,
    search_market_candidates,
    search_references,
)
from amiguprecio.serpapi_shopping import (
    ProductComparability,
    ShoppingProduct,
    ShoppingSearchResult,
)


def test_saved_catalog_is_explicitly_saved_and_limited() -> None:
    references = load_saved_references("amigurumi", max_results=10)

    assert 1 <= len(references) <= 3
    assert all(reference.provenance == "saved" for reference in references)
    assert all(reference.source_url for reference in references)


def test_reference_rejects_non_positive_price() -> None:
    with pytest.raises(ValidationError):
        MarketReference(
            title="Producto",
            price=Decimal(0),
            currency="EUR",
            source_url="https://example.com/product",
            checked_at="2026-10-31T10:00:00+01:00",
            source_name="Example",
            provenance="saved",
        )


def test_inaccessible_live_source_reports_error_and_uses_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> list[MarketReference]:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("amiguprecio.references.fetch_live_references", fail)
    result = search_references("amigurumi", live=True)

    assert result.used_fallback is True
    assert result.references
    assert result.errors and "inaccesible" in result.errors[0]


def test_absent_reference_returns_empty_list() -> None:
    result = search_references("producto-que-no-existe-xyz", live=False)

    assert result.references == []
    assert result.used_fallback is True


def test_eur_references_are_prioritized_by_category_without_conversion() -> None:
    result = search_references(
        "muñeca amigurumi", live=False, currency="EUR", max_results=3
    )

    assert len(result.references) == 3
    assert all(reference.currency == "EUR" for reference in result.references)
    assert [reference.title for reference in result.references[:2]] == [
        "Anne Claire Petit Bunny Crochet Doll",
        "Anne Claire Petit Dog Crochet Doll",
    ]


def test_live_usd_results_fall_back_to_saved_eur(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usd = MarketReference(
        title="Producto USD",
        price="30.00",
        currency="USD",
        source_url="https://example.com/usd",
        checked_at="2026-11-01T12:00:00+01:00",
        source_name="Tienda USD",
        provenance="live",
        product_type="finished_product",
    )
    monkeypatch.setattr(
        "amiguprecio.references.fetch_live_references",
        lambda *args, **kwargs: [usd],
    )

    result = search_references("amigurumi", live=True, currency="EUR")

    assert result.used_fallback is True
    assert result.references
    assert all(reference.currency == "EUR" for reference in result.references)
    assert any("no devolvió referencias en EUR" in error for error in result.errors)


def test_specific_market_query_uses_name_category_and_known_height() -> None:
    query = build_market_query("Hello Kitty", "muñeca", Decimal("25.5"))

    assert "Hello Kitty" in query
    assert "muñeca" in query
    assert "25.5 cm" in query
    assert "producto terminado" in query


def test_serpapi_candidates_keep_thumbnail_provenance_and_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    product = ShoppingProduct(
        title="Hello Kitty amigurumi hecho a mano 25 cm",
        price="34.00",
        currency="EUR",
        store="Artesanía",
        url="https://www.google.com/shopping/product/123",
        thumbnail_url="https://images.example.com/kitty.webp",
        checked_at="2026-11-05T12:00:00+01:00",
        size="25 cm",
        height_cm="25",
        handmade_claimed=True,
    )

    def fake_search(query: str, **kwargs: object) -> ShoppingSearchResult:
        calls.append(query)
        return ShoppingSearchResult(
            query=query,
            api_product_count=1,
            products=[product],
            comparability=[
                ProductComparability(
                    title=product.title,
                    status="comparable",
                    reason="Coinciden tipo, tema, altura y fabricación declarada.",
                )
            ],
            searches_used=1,
        )

    monkeypatch.setenv("SERPAPI_API_KEY", "unit-test-secret")
    monkeypatch.setenv("SERPAPI_SEARCH_ENABLED", "true")
    monkeypatch.setattr("amiguprecio.references.search_google_shopping", fake_search)

    result = search_market_candidates(
        product_name="Hello Kitty",
        category="muñeca",
        height_cm=Decimal(25),
        use_serpapi=True,
    )

    assert len(calls) == 1
    assert result.searches_used == 1
    assert result.used_fallback is False
    assert result.references[0].provenance == "serpapi_google_shopping"
    assert result.references[0].comparability_status == "comparable"
    assert str(result.references[0].thumbnail_url).endswith("kitty.webp")


def test_empty_first_search_allows_only_one_broader_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_search(query: str, **kwargs: object) -> ShoppingSearchResult:
        calls.append(query)
        return ShoppingSearchResult(query=query, searches_used=1)

    monkeypatch.setenv("SERPAPI_API_KEY", "unit-test-secret")
    monkeypatch.setenv("SERPAPI_SEARCH_ENABLED", "true")
    monkeypatch.setattr("amiguprecio.references.search_google_shopping", fake_search)

    result = search_market_candidates(
        product_name="Hello Kitty",
        category="muñeca",
        use_serpapi=True,
    )

    assert len(calls) == 2
    assert result.searches_used == 2
    assert result.used_fallback is True
    assert all(reference.provenance == "saved" for reference in result.references)


def test_disabled_serpapi_uses_existing_fallback_without_online_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> ShoppingSearchResult:
        raise AssertionError("SerpApi no debe ejecutarse")

    monkeypatch.setattr("amiguprecio.references.search_google_shopping", forbidden)

    result = search_market_candidates(
        product_name="Hello Kitty",
        category="muñeca",
        use_serpapi=False,
        live=False,
    )

    assert result.searches_used == 0
    assert result.used_fallback is True
    assert all(reference.provenance == "saved" for reference in result.references)


def test_mcp_argument_cannot_override_disabled_serpapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> ShoppingSearchResult:
        raise AssertionError("El argumento MCP no debe anular el interruptor")

    monkeypatch.setenv("SERPAPI_API_KEY", "unit-test-secret")
    monkeypatch.setenv("SERPAPI_SEARCH_ENABLED", "false")
    monkeypatch.setattr("amiguprecio.references.search_google_shopping", forbidden)

    result = search_market_candidates(
        product_name="Hello Kitty",
        category="muñeca",
        use_serpapi=True,
        live=False,
    )

    assert result.searches_used == 0
    assert result.used_fallback is True
    assert all(reference.provenance == "saved" for reference in result.references)
