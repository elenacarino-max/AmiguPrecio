from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from amiguprecio.agents import (
    AssessmentValidationError,
    MCPReferenceSearchTool,
)
from amiguprecio.models import PricingInput
from amiguprecio.references import MarketReference, ReferenceSearchResult
from amiguprecio.workflow import (
    AgentOutputError,
    analyst_payload,
    run_deterministic_analysis,
    validate_analyst_observations,
)


def _pricing_input() -> PricingInput:
    return PricingInput(
        product_name="Luna",
        product_type="muñeca",
        materials_cost="12.50",
        hours_worked="5",
        hourly_rate="10",
        other_expenses="2.50",
        margin_percent="20",
    )


def _reference(currency: str = "EUR") -> MarketReference:
    return MarketReference(
        title="Muñeca artesanal verificada",
        price="24.90",
        currency=currency,
        features=["algodón", "producto terminado"],
        source_url="https://example.com/verified-doll",
        checked_at=datetime.now(UTC),
        source_name="Tienda artesanal",
        provenance="saved",
        category="muñeca",
        size="20 cm",
        product_type="finished_product",
    )


def test_deterministic_stage_preserves_references_and_runs_without_llm(tmp_path) -> None:
    reference = _reference()
    chart_path = tmp_path / "current-run.png"

    analysis = run_deterministic_analysis(
        _pricing_input(), [reference], chart_path=chart_path
    )

    assert analysis.pricing.calculated_price == Decimal("81.25")
    assert analysis.statistics.valid_reference_count == 1
    assert analysis.references == [reference]
    assert analysis.references[0].features == ["algodón", "producto terminado"]
    assert analysis.references[0].source_name == "Tienda artesanal"
    assert Path(analysis.chart_path) == chart_path
    assert chart_path.exists() and chart_path.stat().st_size > 0


def test_deterministic_stage_excludes_incompatible_currencies(tmp_path) -> None:
    analysis = run_deterministic_analysis(
        _pricing_input(),
        [_reference(currency="USD")],
        chart_path=tmp_path / "no-comparable.png",
    )

    assert analysis.statistics.valid_reference_count == 0
    assert analysis.statistics.mean is None
    assert analysis.statistics.comparable_currency is None


def test_empty_analyst_output_keeps_official_python_result(tmp_path) -> None:
    analysis = run_deterministic_analysis(
        _pricing_input(), [], chart_path=tmp_path / "empty-agent.png"
    )

    with pytest.raises(AgentOutputError, match="respuesta vacía"):
        validate_analyst_observations("   ", analysis)

    assert analysis.pricing.calculated_price == Decimal("81.25")
    assert Path(analysis.chart_path).exists()


def test_analyst_cannot_replace_official_8125_with_7800(tmp_path) -> None:
    analysis = run_deterministic_analysis(
        _pricing_input(), [], chart_path=tmp_path / "contradiction.png"
    )

    with pytest.raises(AssessmentValidationError, match="78.00"):
        validate_analyst_observations("El precio correcto es 78,00 EUR", analysis)

    assert analysis.pricing.calculated_price == Decimal("81.25")


def test_research_tool_preserves_typed_mcp_result(monkeypatch) -> None:
    reference = _reference()
    expected = ReferenceSearchResult(query="muñeca", references=[reference])

    def fake_mcp_search(**kwargs: object) -> ReferenceSearchResult:
        assert kwargs == {"query": "muñeca", "max_results": 3, "live": False}
        return expected

    monkeypatch.setattr(
        "amiguprecio.agents.search_references_mcp_sync", fake_mcp_search
    )
    tool = MCPReferenceSearchTool()

    payload = tool._run(query="muñeca", max_results=3, live=False)

    assert tool.last_result == expected
    assert payload["references"][0]["source_name"] == "Tienda artesanal"
    assert payload["references"][0]["source_url"] == str(reference.source_url)


def test_analyst_payload_is_short_and_preserves_control_case(tmp_path) -> None:
    analysis = run_deterministic_analysis(
        _pricing_input(),
        [_reference(currency="USD")],
        chart_path=tmp_path / "short-payload.png",
    )

    payload = analyst_payload(analysis)

    assert payload == {
        "production_cost": "65.00",
        "calculated_price": "81.25",
        "margin_percent": "20",
        "pricing_currency": "EUR",
        "valid_reference_count": 0,
        "reference_currencies": ["USD"],
        "market_mean": None,
    }
