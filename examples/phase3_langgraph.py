"""Ejecución interactiva real del grafo; requiere credenciales válidas de Groq."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from langgraph.types import Command

from amiguprecio.langgraph_workflow import (
    build_amiguprecio_graph,
    create_production_services,
    initial_graph_state,
)
from amiguprecio.models import PricingInput


def main() -> None:
    output_dir = Path("output/langgraph")
    graph = build_amiguprecio_graph(create_production_services(output_dir))
    config = {"configurable": {"thread_id": f"amiguprecio-{uuid4()}"}}
    state = initial_graph_state(
        PricingInput(
            product_name="Luna",
            product_type="muñeca amigurumi terminada",
            materials_cost="12.50",
            hours_worked="5",
            hourly_rate="10",
            other_expenses="2.50",
            margin_percent="20",
        ),
        "muñeca amigurumi terminada",
        output_dir,
    )
    paused = graph.invoke(state, config)
    if not paused.get("__interrupt__"):
        print(f"GRAPH_STATUS={paused['review_status']}")
        print(f"ERROR_COUNT={len(paused['errors'])}")
        return

    answer = input("¿Guardar el informe aprobado? [s/N]: ").strip().casefold()
    completed = graph.invoke(Command(resume={"approved": answer == "s"}), config)
    print(f"HUMAN_DECISION={completed['human_decision']}")
    print(f"REPORT_STATUS={completed['report_status']}")
    if completed["report_path"]:
        print(f"REPORT_PATH={completed['report_path']}")


if __name__ == "__main__":
    main()
