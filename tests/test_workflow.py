from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from amiguprecio.agents import (
    AssessmentValidationError,
    CommercialAssessment,
    MCPReferenceSearchTool,
)
from amiguprecio.models import PricingInput
from amiguprecio.references import (
    MarketReference,
    ReferenceSearchResult,
    load_saved_references,
)
from amiguprecio.reporting import collect_presented_limitations
from amiguprecio.workflow import (
    AgentOutputError,
    analyst_payload,
    enforce_supported_commercial_assessment,
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
        assert kwargs == {
            "query": "muñeca",
            "max_results": 3,
            "live": False,
            "currency": None,
        }
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

    assert payload["production_cost"] == "65.00"
    assert payload["calculated_price"] == "81.25"
    assert payload["margin_percent"] == "20"
    assert payload["pricing_currency"] == "EUR"
    assert payload["currency_sample_count"] == 0
    assert payload["reference_currencies"] == ["USD"]
    assert payload["currency_sample_mean"] is None
    assert payload["commercial_comparability"]["directly_comparable_count"] == 0


def test_hello_kitty_keeps_money_but_rejects_unsupported_positioning(tmp_path) -> None:
    product = PricingInput(
        product_name="Hello Kitty",
        product_type="muñeca amigurumi",
        materials_cost="10",
        hours_worked="1.5",
        hourly_rate="20",
        other_expenses="0",
        margin_percent="20",
    )
    references = load_saved_references("muñeca amigurumi", currency="EUR")
    analysis = run_deterministic_analysis(
        product,
        references,
        chart_path=tmp_path / "hello-kitty.png",
    )

    assert analysis.pricing.production_cost == Decimal("40.00")
    assert analysis.pricing.calculated_price == Decimal("50.00")
    assert analysis.statistics.valid_reference_count == 3
    assert analysis.statistics.mean == Decimal("41.55")
    assert analysis.commercial_comparability.directly_comparable_count == 0
    assert analysis.commercial_comparability.not_comparable_count == 1
    assert analysis.commercial_comparability.undetermined_count == 2
    assert analysis.commercial_comparability.sample_is_heterogeneous is True

    unsafe = CommercialAssessment(
        comparability="Las tres referencias permiten una comparación directa.",
        market_position="El margen del 20 % confirma un posicionamiento premium.",
        recommendation="Mantener el precio actual porque no existen discrepancias.",
        limitations=["La fotografía no permite determinar el material exacto."],
    )
    safe = enforce_supported_commercial_assessment(unsafe, analysis)

    assert safe.market_position == (
        "No es posible determinar el posicionamiento de mercado con estas referencias."
    )
    assert "premium" not in safe.model_dump_json().casefold()
    assert "mantener el precio actual" not in safe.recommendation.casefold()
    assert any("margen objetivo" in item.casefold() for item in safe.limitations)

    analyst_text = validate_analyst_observations(
        "El precio de 50,00 EUR supera la media de 41,55 EUR y es premium con margen 20,00 %.",
        analysis,
    )
    assert "premium" not in analyst_text.casefold()
    assert "muestra monetaria" in analyst_text.casefold()


def test_presented_limitations_are_grouped_without_mutating_sources() -> None:
    advisor = [
        "La fotografía no permite determinar el material exacto.",
        "Los precios anunciados no prueban ventas ni demanda.",
    ]
    visual = ["La fotografía no permite determinar el material exacto."]

    presented = collect_presented_limitations(advisor, visual)

    assert presented == advisor
    assert visual == ["La fotografía no permite determinar el material exacto."]
