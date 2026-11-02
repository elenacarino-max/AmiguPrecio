from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from amiguprecio.references import MarketReference, load_saved_references, search_references


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
