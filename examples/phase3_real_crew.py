"""Prueba externa mínima de los tres agentes; no imprime secretos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from amiguprecio import PricingInput
from amiguprecio.agents import (
    PricingAnalysisTool,
    create_llm,
)
from amiguprecio.workflow import run_hybrid_workflow


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
    output_dir = Path("output/hybrid")
    result = run_hybrid_workflow(
        pricing_input=PricingInput(
            product_name="Luna",
            product_type="muñeca amigurumi terminada",
            materials_cost="12.50",
            hours_worked="5",
            hourly_rate="10",
            other_expenses="2.50",
            margin_percent="20",
        ),
        query="muñeca amigurumi terminada",
        output_dir=output_dir,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "workflow-result.json"
    result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if not result.completed:
        raise RuntimeError("El flujo híbrido no completó los tres agentes")


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
