"""Controlador de sesión Streamlit sobre una única ejecución persistente del grafo."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from amiguprecio.langgraph_workflow import (
    build_amiguprecio_graph,
    create_production_services,
    initial_graph_state,
)
from amiguprecio.models import PricingInput
from amiguprecio.vision import PreparedImage


@dataclass
class WorkflowExecution:
    """Conserva grafo, checkpoint, thread y resultados durante los reruns de Streamlit."""

    graph: Any
    config: dict[str, dict[str, str]]
    initial_state: dict[str, object]
    output_dir: Path
    thread_id: str
    completed_stages: list[str] = field(default_factory=list)
    started: bool = False

    @classmethod
    def production(
        cls,
        product: PricingInput,
        query: str,
        output_root: Path,
        prepared_image: PreparedImage | None,
    ) -> WorkflowExecution:
        execution_id = uuid4().hex
        output_dir = output_root / execution_id
        output_dir.mkdir(parents=True, exist_ok=True)
        services = create_production_services(output_dir, prepared_image)
        graph = build_amiguprecio_graph(services)
        thread_id = f"amiguprecio-{execution_id}"
        state = initial_graph_state(
            product,
            query,
            output_dir,
            report_path=output_dir / "informe-amiguprecio.md",
            visual_requested=prepared_image is not None,
        )
        return cls(
            graph=graph,
            config={"configurable": {"thread_id": thread_id}},
            initial_state=state,
            output_dir=output_dir,
            thread_id=thread_id,
        )

    def start(self) -> Iterator[str]:
        if self.started:
            return
        self.started = True
        for update in self.graph.stream(
            self.initial_state,
            self.config,
            stream_mode="updates",
        ):
            for stage in update:
                if stage.startswith("__"):
                    continue
                self.completed_stages.append(stage)
                yield stage

    def resume(self, approved: bool) -> dict[str, object]:
        """Reanuda el mismo checkpoint; no crea una ejecución nueva."""

        return self.graph.invoke(Command(resume={"approved": approved}), self.config)

    @property
    def snapshot(self) -> Any:
        return self.graph.get_state(self.config)

    @property
    def values(self) -> dict[str, object]:
        return dict(self.snapshot.values)

    @property
    def waiting_for_approval(self) -> bool:
        return self.snapshot.next == ("approval",)
