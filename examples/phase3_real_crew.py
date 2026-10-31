"""Prueba externa mínima de los tres agentes; no imprime secretos."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from amiguprecio.agents import (
    PricingAnalysisTool,
    create_crew,
    create_llm,
    ensure_assessment_uses_authoritative_numbers,
    validate_commercial_assessment,
)


def smoke_test() -> None:
    """Valida credencial y modelo sin imprimir respuesta ni parámetros sensibles."""

    response = create_llm().call(
        [{"role": "user", "content": "Responde exactamente OK"}]
    )
    print("MINIMAL_GROQ_OK=true")
    print(f"RESPONSE_NONEMPTY={str(bool(str(response).strip())).lower()}")


def tool_schema_smoke_test() -> None:
    """Comprueba que Groq acepta el contrato real de la herramienta de cálculo."""

    structured_tool = PricingAnalysisTool().to_structured_tool()
    serialized = structured_tool.model_dump(mode="json")
    tools = [
        {
            "type": "function",
            "function": {
                "name": serialized["name"],
                "description": serialized["description"],
                "parameters": serialized["args_schema"],
            },
        }
    ]
    response = create_llm().call(
        [
            {
                "role": "user",
                "content": (
                    "Llama a calculate_and_compare_prices para Luna con materiales 12.50, "
                    "5 horas, tarifa 10, otros gastos 2.50, margen 20 y sin referencias."
                ),
            }
        ],
        tools=tools,
    )
    print("GROQ_TOOL_SCHEMA_ACCEPTED=true")
    print(f"TOOL_CALL_RETURNED={str(isinstance(response, list) and bool(response)).lower()}")


def main() -> None:
    output_dir = Path("output/logs")
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "crewai-real.json"
    pricing_trace_path = output_dir / "pricing-tool-real.json"
    os.environ["AMIGUPRECIO_PRICING_TRACE"] = str(pricing_trace_path)
    crew = create_crew(output_log_file=str(log_path))
    result = crew.kickoff(
        inputs={
            "product_type": "muñeca amigurumi terminada",
            "pricing_data": {
                "product_name": "Luna",
                "product_type": "muñeca amigurumi terminada",
                "materials_cost": "12.50",
                "hours_worked": "5",
                "hourly_rate": "10",
                "other_expenses": "2.50",
                "margin_percent": "20",
                "pricing_currency": "EUR",
                "chart_path": "output/charts/phase3-real.png",
            },
        }
    )
    assessment = validate_commercial_assessment(result.tasks_output[-1].raw)
    pricing_trace = json.loads(pricing_trace_path.read_text(encoding="utf-8"))
    ensure_assessment_uses_authoritative_numbers(assessment, pricing_trace)
    summary = {
        "agents": [agent.role for agent in crew.agents],
        "task_count": len(result.tasks_output),
        "assessment": assessment.model_dump(mode="json"),
        "pricing": pricing_trace["python_result"]["pricing"],
        "pricing_trace_path": str(pricing_trace_path),
        "usage": result.token_usage.model_dump(mode="json"),
        "log_path": str(log_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--tool-smoke", action="store_true")
    options = parser.parse_args()
    try:
        if options.smoke:
            smoke_test()
        elif options.tool_smoke:
            tool_schema_smoke_test()
        else:
            main()
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - frontera CLI segura
        print(f"REAL_CREW_FAILED={type(exc).__name__}")
        raise SystemExit(1) from None
