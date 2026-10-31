"""Demo determinista; añade --run-llm para ejecutar la crew con credenciales."""

from __future__ import annotations

import argparse
from pathlib import Path

from amiguprecio import PricingInput, calculate_price
from amiguprecio.agents import CommercialAssessment, create_crew
from amiguprecio.analysis import calculate_market_statistics, create_price_chart
from amiguprecio.mcp_client import search_references_mcp_sync


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-llm", action="store_true")
    args = parser.parse_args()
    result = search_references_mcp_sync("amigurumi", live=False)
    print(result.model_dump_json(indent=2))
    pricing_input = PricingInput(
        product_name="Luna",
        product_type="muñeca",
        materials_cost="12.50",
        hours_worked="5",
        hourly_rate="10",
        other_expenses="2.50",
        margin_percent="20",
    )
    pricing = calculate_price(pricing_input)
    statistics = calculate_market_statistics(pricing, result.references)
    chart = create_price_chart(pricing, result.references, Path("output/charts/phase2_demo.png"))
    assessment_preview = CommercialAssessment(
        comparability="Insuficiente: las referencias están en USD y el cálculo está en EUR.",
        market_position="No calculable sin conversión de moneda y revisión de características.",
        recommendation="Conservar el precio rentable y recopilar referencias comparables en EUR.",
        limitations=[
            "Sin conversión USD/EUR",
            "Catálogo guardado",
            "Sin datos de ventas o demanda",
        ],
    )
    print(pricing.model_dump_json(indent=2))
    print(statistics.model_dump_json(indent=2))
    print(assessment_preview.model_dump_json(indent=2))
    print(f"Gráfico reproducible: {chart}")
    if args.run_llm:
        crew = create_crew(output_log_file="output/logs/crewai-real.json")
        output = crew.kickoff(
            inputs={
                "product_type": "muñeca amigurumi",
                "pricing_data": {
                    "product_name": "Luna",
                    "product_type": "muñeca",
                    "materials_cost": "12.50",
                    "hours_worked": "5",
                    "hourly_rate": "10",
                    "other_expenses": "2.50",
                    "margin_percent": "20",
                },
            }
        )
        print(output)
    else:
        print("CrewAI configurado; usa --run-llm para ejecutar llamadas externas.")


if __name__ == "__main__":
    main()
