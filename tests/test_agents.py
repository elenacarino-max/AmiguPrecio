import importlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from crewai import LLM
from pydantic import ValidationError

from amiguprecio import PricingInput, calculate_price
from amiguprecio.references import load_saved_references


def _offline_llm() -> LLM:
    return LLM(model="openai/gpt-4o-mini", api_key="unit-test-placeholder")


def test_exactly_three_agents_are_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("appdirs.user_data_dir", lambda *args, **kwargs: str(tmp_path))
    agents_module = importlib.import_module("amiguprecio.agents")
    researcher, analyst, advisor = agents_module.create_agents(llm=_offline_llm())

    assert [researcher.role, analyst.role, advisor.role] == [
        "Investigador de mercado de amigurumis",
        "Analista de costes y precios",
        "Asesor comercial de producto artesanal",
    ]
    assert len(researcher.tools) == 1
    assert researcher.tools[0].name == "search_market_references"
    assert analyst.tools == []
    assert advisor.tools == []


def test_crew_uses_sequential_process(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("appdirs.user_data_dir", lambda *args, **kwargs: str(tmp_path))
    agents_module = importlib.import_module("amiguprecio.agents")
    crew = agents_module.create_crew(llm=_offline_llm())

    assert len(crew.agents) == 3
    assert len(crew.tasks) == 3
    assert crew.process == agents_module.Process.sequential
    assert crew.agents[0].tools[0].result_as_answer is True
    assert crew.tasks[-1].output_pydantic is None
    assert crew.tasks[-1].output_json is None


def test_groq_messages_do_not_include_cache_breakpoint() -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    llm = agents_module.GroqCompatibleLLM(
        model="groq/openai/gpt-oss-20b",
        api_key="unit-test-placeholder",
    )
    original = [
        {
            "role": "system",
            "content": "Conserva este contenido",
            "cache_breakpoint": True,
        }
    ]

    formatted = llm._format_messages_for_provider(original)

    assert formatted == [{"role": "system", "content": "Conserva este contenido"}]
    assert original[0]["cache_breakpoint"] is True


def test_adjusted_analyst_parameters_reach_litellm_contract(monkeypatch) -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-placeholder")
    llm = agents_module.create_llm(
        model_env="GROQ_ANALYST_MODEL",
        max_tokens=1200,
        reasoning_effort="low",
        include_reasoning=False,
        max_retries=0,
    )

    params = llm._prepare_completion_params(
        [{"role": "user", "content": "Resumen breve"}], tools=None
    )

    assert params["model"] == "groq/openai/gpt-oss-20b"
    assert params["max_tokens"] == 1200
    assert params["reasoning_effort"] == "low"
    assert params["include_reasoning"] is False
    assert params["stream"] is False
    assert "tools" not in params
    assert "response_format" not in params


def test_tool_schema_uses_simple_decimal_strings_for_groq() -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    from crewai.utilities.agent_utils import convert_tools_to_openai_schema

    openai_tools, _, _ = convert_tools_to_openai_schema(
        [agents_module.PricingAnalysisTool()]
    )
    exposed_function = openai_tools[0]["function"]
    schema = exposed_function["parameters"]
    reference_schema = schema["properties"]["references"]["items"]
    reference_price = reference_schema["properties"]["price"]

    assert exposed_function["strict"] is True
    assert reference_schema["additionalProperties"] is False
    assert set(reference_schema["required"]) == {
        "source_url",
        "price",
        "currency",
        "checked_at",
        "provenance",
    }
    assert set(reference_schema["properties"]) == set(reference_schema["required"])
    assert reference_price["type"] == "string"
    assert "pattern" not in reference_price
    for field in (
        "materials_cost",
        "hours_worked",
        "hourly_rate",
        "other_expenses",
        "margin_percent",
    ):
        assert schema["properties"][field]["type"] == "string"
    assert "(?" not in str(schema)


def test_tool_keeps_decimal_pricing_result(tmp_path) -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    pricing_data = {
        "product_name": "Luna",
        "product_type": "muñeca",
        "materials_cost": "12.50",
        "hours_worked": "5",
        "hourly_rate": "10",
        "other_expenses": "2.50",
        "margin_percent": "20",
    }
    expected = calculate_price(PricingInput(**pricing_data)).model_dump(mode="json")

    result = agents_module.PricingAnalysisTool()._run(
        **pricing_data,
        references=[
            {
                "price": "24.90",
                "currency": "EUR",
                "source_url": "https://example.com/doll",
                "checked_at": datetime.now(UTC).isoformat(),
                "provenance": "saved",
            }
        ],
        chart_path=str(tmp_path / "comparison.png"),
    )

    assert result["pricing"] == expected
    assert result["statistics"]["valid_reference_count"] == 1
    assert Decimal(result["statistics"]["mean"]) == Decimal("24.90")


def test_tool_accepts_exact_minimal_reference_from_failed_groq_call(tmp_path) -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    result = agents_module.PricingAnalysisTool()._run(
        product_name="Luna",
        product_type="muñeca amigurumi terminada",
        materials_cost="12.50",
        hours_worked="5",
        hourly_rate="10",
        other_expenses="2.50",
        margin_percent="20",
        pricing_currency="EUR",
        references=[
            {
                "source_url": "https://sweetlavenderco.com/products/amigurumi_elephant",
                "price": "35.00",
                "currency": "USD",
                "checked_at": "2026-10-31T17:30:00+01:00",
                "provenance": "saved",
            }
        ],
        chart_path=str(tmp_path / "minimal-reference.png"),
    )

    assert result["pricing"]["calculated_price"] == "81.25"
    assert result["statistics"]["valid_reference_count"] == 0
    assert result["statistics"]["mean"] is None


def test_tool_rejects_invalid_reference_price() -> None:
    agents_module = importlib.import_module("amiguprecio.agents")

    try:
        agents_module.PricingToolInput.model_validate(
            {
                "product_name": "Luna",
                "product_type": "muñeca",
                "materials_cost": "12.50",
                "hours_worked": "5",
                "hourly_rate": "10",
                "margin_percent": "20",
                "references": [
                    {
                        "source_url": "https://example.com/doll",
                        "price": "no-es-un-precio",
                        "currency": "EUR",
                        "checked_at": "2026-10-31T17:30:00+01:00",
                        "provenance": "saved",
                    }
                ],
            }
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("La referencia con precio inválido debía rechazarse")


def test_saved_commercial_metadata_remains_available() -> None:
    reference = load_saved_references("", max_results=1)[0]

    assert reference.title
    assert reference.source_name
    assert reference.category
    assert reference.product_type == "finished_product"


def test_advisor_json_is_validated_after_agent_execution() -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    assessment = agents_module.validate_commercial_assessment(
        """```json
        {
          "comparability": "Insuficiente por monedas diferentes",
          "market_position": "No determinable",
          "recommendation": "Mantener el precio calculado por Python",
          "limitations": ["No hay datos de ventas"]
        }
        ```"""
    )

    assert assessment.comparability.startswith("Insuficiente")


def test_advisor_limitations_list_is_preserved() -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    limitations = ["Sin referencias EUR", "Muestra insuficiente"]

    assessment = agents_module.CommercialAssessment(
        comparability="Insuficiente",
        market_position="No determinable",
        recommendation="Mantener el precio oficial",
        limitations=limitations,
    )

    assert assessment.limitations == limitations


def test_real_advisor_string_limitation_is_normalized_without_rewriting() -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    real_limitation = (
        "Lack of market mean, no valid references, only internal margin used; "
        "currency reference USD mentioned but no data provided."
    )
    raw_output = json.dumps(
        {
            "comparability": "No comparable market data available.",
            "market_position": "No external benchmark.",
            "recommendation": "Seek external market data.",
            "limitations": real_limitation,
        }
    )

    assessment = agents_module.validate_commercial_assessment(raw_output)

    assert assessment.limitations == [real_limitation]


def test_advisor_incompatible_limitations_type_is_rejected() -> None:
    agents_module = importlib.import_module("amiguprecio.agents")

    with pytest.raises(ValidationError, match="limitations"):
        agents_module.CommercialAssessment(
            comparability="Insuficiente",
            market_position="No determinable",
            recommendation="Mantener el precio oficial",
            limitations={"reason": "Sin referencias EUR"},
        )


def test_invalid_advisor_json_is_rejected() -> None:
    agents_module = importlib.import_module("amiguprecio.agents")

    try:
        agents_module.validate_commercial_assessment('{"recommendation": "incompleto"}')
    except agents_module.AssessmentValidationError:
        pass
    else:
        raise AssertionError("La valoración incompleta debía rechazarse")


def test_advisor_contract_is_extracted_from_tool_output_without_relaxing_schema() -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    raw_output = """Resultado de analyze_uploaded_amigurumi_image:
    {"status": "completed", "analysis": {"apparent_type": "muñeca"}}
    Valoración final:
    {
      "comparability": "Insuficiente por falta de equivalencia descriptiva",
      "market_position": "No determinable",
      "recommendation": "Reunir referencias equivalentes",
      "limitations": ["La muestra es heterogénea"]
    }
    """

    assessment = agents_module.validate_commercial_assessment(raw_output)

    assert assessment.market_position == "No determinable"
    assert assessment.limitations == ["La muestra es heterogénea"]


def test_advisor_cannot_replace_python_price_8125_with_7800() -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    assessment = agents_module.CommercialAssessment(
        comparability="Media",
        market_position="El precio calculado es 78,00 EUR",
        recommendation="Revisar posicionamiento",
        limitations=[],
    )
    python_trace = {"python_result": {"pricing": {"calculated_price": "81.25"}}}

    try:
        agents_module.ensure_assessment_uses_authoritative_numbers(
            assessment, python_trace
        )
    except agents_module.AssessmentValidationError as exc:
        assert "78.00" in str(exc)
    else:
        raise AssertionError("La cifra contradictoria debía rechazarse")


def test_pricing_tool_trace_contains_exact_arguments_and_python_result(
    monkeypatch, tmp_path
) -> None:
    agents_module = importlib.import_module("amiguprecio.agents")
    trace_path = tmp_path / "pricing-trace.json"
    monkeypatch.setenv("AMIGUPRECIO_PRICING_TRACE", str(trace_path))
    pricing_data = {
        "product_name": "Luna",
        "product_type": "muñeca",
        "materials_cost": "12.50",
        "hours_worked": "5",
        "hourly_rate": "10",
        "other_expenses": "2.50",
        "margin_percent": "20",
    }

    agents_module.PricingAnalysisTool()._run(
        **pricing_data,
        chart_path=str(tmp_path / "trace-chart.png"),
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    assert trace["arguments"]["materials_cost"] == "12.50"
    assert trace["arguments"]["other_expenses"] == "2.50"
    assert trace["python_result"]["pricing"]["calculated_price"] == "81.25"
