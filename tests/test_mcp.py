import asyncio
from decimal import Decimal

import pytest

from amiguprecio.mcp_client import _mcp_server_environment, search_references_mcp
from amiguprecio.mcp_server import search_market_references
from amiguprecio.references import ReferenceSearchResult


def test_stdio_client_connects_and_calls_real_tool() -> None:
    result = asyncio.run(search_references_mcp("amigurumi", live=False))

    assert result.used_fallback is True
    assert len(result.references) == 3
    assert all(reference.provenance == "saved" for reference in result.references)


def test_mcp_contract_forwards_product_identity_to_serpapi_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_candidates(**kwargs: object) -> ReferenceSearchResult:
        captured.update(kwargs)
        return ReferenceSearchResult(query="Hello Kitty muñeca")

    monkeypatch.setattr(
        "amiguprecio.mcp_server.search_market_candidates", fake_candidates
    )

    payload = search_market_references(
        query="Hello Kitty muñeca amigurumi crochet producto terminado 25 cm",
        product_name="Hello Kitty",
        category="muñeca",
        height_cm="25",
        currency="EUR",
        max_results=10,
        use_serpapi=True,
    )

    assert captured["product_name"] == "Hello Kitty"
    assert captured["category"] == "muñeca"
    assert captured["height_cm"] == Decimal(25)
    assert captured["currency"] == "EUR"
    assert captured["max_results"] == 10
    assert captured["use_serpapi"] is True
    assert payload["references"] == []


def test_mcp_subprocess_receives_serpapi_activation_without_logging_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "unit-test-secret")
    monkeypatch.setenv("SERPAPI_SEARCH_ENABLED", "true")

    environment = _mcp_server_environment()

    assert environment["SERPAPI_API_KEY"] == "unit-test-secret"
    assert environment["SERPAPI_SEARCH_ENABLED"] == "true"


def test_disabled_mcp_subprocess_does_not_receive_serpapi_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "unit-test-secret")
    monkeypatch.setenv("SERPAPI_SEARCH_ENABLED", "false")

    environment = _mcp_server_environment()

    assert environment["SERPAPI_SEARCH_ENABLED"] == "false"
    assert "SERPAPI_API_KEY" not in environment
