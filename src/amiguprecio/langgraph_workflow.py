"""Orquestación LangGraph del flujo híbrido con aprobación humana persistente."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from amiguprecio.agents import (
    CommercialAssessment,
    MCPReferenceSearchTool,
    VisionAnalysisTool,
    create_agents,
    ensure_assessment_uses_authoritative_numbers,
)
from amiguprecio.models import PricingInput
from amiguprecio.references import ReferenceSearchResult
from amiguprecio.reporting import render_markdown_report, save_markdown_report
from amiguprecio.vision import PreparedImage, VisualAnalysis
from amiguprecio.workflow import (
    DeterministicAnalysis,
    enforce_supported_commercial_assessment,
    run_advisor_agent,
    run_analyst_agent,
    run_deterministic_analysis,
    run_research_agent,
    validate_analyst_observations,
)

ReviewStatus = Literal["pending", "retry", "approved", "error"]
HumanDecision = Literal["pending", "approved", "rejected"]
ReportStatus = Literal["pending", "saved", "not_saved", "error"]
RetryStage = Literal["analyst", "advisor"]


class AmiguPrecioGraphState(TypedDict):
    """Estado compartido, tipado y persistible del flujo de entrega."""

    product: dict[str, object]
    query: str
    pricing_currency: str
    output_dir: str
    requested_report_path: str
    references: dict[str, object] | None
    deterministic_analysis: dict[str, object] | None
    chart_path: str | None
    analyst_observations: str | None
    commercial_assessment: dict[str, object] | None
    errors: list[str]
    review_status: ReviewStatus
    retry_stage: RetryStage | None
    retry_count: int
    human_decision: HumanDecision
    report_status: ReportStatus
    report_path: str | None
    research_attempts: int
    calculation_attempts: int
    analyst_attempts: int
    advisor_attempts: int
    visual_requested: bool
    visual_status: Literal["not_requested", "pending", "completed", "failed"]
    visual_analysis: dict[str, object] | None
    visual_error: str | None


@dataclass(frozen=True)
class WorkflowServices:
    """Fronteras sustituibles para producción y pruebas deterministas."""

    research: Callable[[str, str], ReferenceSearchResult]
    calculate: Callable[
        [PricingInput, list, Path, str], DeterministicAnalysis
    ]
    analyze: Callable[[DeterministicAnalysis, str], str]
    advise: Callable[
        [DeterministicAnalysis, str, str], CommercialAssessment
    ]
    save_report: Callable[[Path, str], Path] = save_markdown_report
    get_visual_analysis: Callable[[], VisualAnalysis | None] | None = None
    get_visual_error: Callable[[], str | None] | None = None


def create_production_services(
    output_dir: Path, prepared_image: PreparedImage | None = None
) -> WorkflowServices:
    """Conecta el grafo con los tres agentes y el cálculo ya existentes."""

    research_tool = MCPReferenceSearchTool()
    vision_tool = VisionAnalysisTool(prepared_image) if prepared_image else None
    researcher, analyst, advisor = create_agents(
        research_tool=research_tool,
        vision_tool=vision_tool,
    )
    crew_log = str(output_dir / "langgraph-crewai.json")

    def research(query: str, pricing_currency: str) -> ReferenceSearchResult:
        result, _ = run_research_agent(
            researcher,
            research_tool,
            query,
            pricing_currency=pricing_currency,
            output_log_file=crew_log,
        )
        return result

    def calculate(
        product: PricingInput,
        references: list,
        chart_path: Path,
        pricing_currency: str,
    ) -> DeterministicAnalysis:
        return run_deterministic_analysis(
            product,
            references,
            chart_path,
            pricing_currency,
        )

    def analyze(analysis: DeterministicAnalysis, pricing_currency: str) -> str:
        observations, _ = run_analyst_agent(
            analyst,
            analysis,
            output_log_file=crew_log,
            pricing_currency=pricing_currency,
        )
        return observations

    def advise(
        analysis: DeterministicAnalysis,
        observations: str,
        pricing_currency: str,
    ) -> CommercialAssessment:
        assessment, _ = run_advisor_agent(
            advisor,
            analysis,
            observations,
            output_log_file=crew_log,
            pricing_currency=pricing_currency,
            use_vision=(
                vision_tool is not None
                and vision_tool.last_result is None
                and vision_tool.last_error is None
            ),
        )
        return assessment

    return WorkflowServices(
        research=research,
        calculate=calculate,
        analyze=analyze,
        advise=advise,
        get_visual_analysis=(
            (lambda: vision_tool.last_result) if vision_tool is not None else None
        ),
        get_visual_error=(
            (lambda: vision_tool.last_error) if vision_tool is not None else None
        ),
    )


def initial_graph_state(
    product: PricingInput,
    query: str,
    output_dir: Path,
    *,
    pricing_currency: str = "EUR",
    report_path: Path | None = None,
    visual_requested: bool = False,
) -> AmiguPrecioGraphState:
    """Crea un estado inicial explícito y listo para checkpoint."""

    destination = report_path or output_dir / "amiguprecio-report.md"
    return AmiguPrecioGraphState(
        product=product.model_dump(mode="json"),
        query=query,
        pricing_currency=pricing_currency,
        output_dir=str(output_dir),
        requested_report_path=str(destination),
        references=None,
        deterministic_analysis=None,
        chart_path=None,
        analyst_observations=None,
        commercial_assessment=None,
        errors=[],
        review_status="pending",
        retry_stage=None,
        retry_count=0,
        human_decision="pending",
        report_status="pending",
        report_path=None,
        research_attempts=0,
        calculation_attempts=0,
        analyst_attempts=0,
        advisor_attempts=0,
        visual_requested=visual_requested,
        visual_status="pending" if visual_requested else "not_requested",
        visual_analysis=None,
        visual_error=None,
    )


def _with_error(state: AmiguPrecioGraphState, stage: str, exc: Exception) -> list[str]:
    return [*state["errors"], f"{stage}: {type(exc).__name__}"]


def _retry_or_error(
    state: AmiguPrecioGraphState,
    stage: RetryStage,
    message: str,
) -> dict[str, object]:
    errors = [*state["errors"], message]
    if state["retry_count"] < 1:
        return {
            "errors": errors,
            "review_status": "retry",
            "retry_stage": stage,
            "retry_count": state["retry_count"] + 1,
        }
    return {
        "errors": errors,
        "review_status": "error",
        "retry_stage": None,
        "report_status": "error",
    }


def build_amiguprecio_graph(
    services: WorkflowServices,
    *,
    checkpointer: object | None = None,
):
    """Compila el grafo con revisión condicional e interrupción humana real."""

    def research_node(state: AmiguPrecioGraphState) -> dict[str, object]:
        if state["references"] is not None:
            return {}
        try:
            references = services.research(
                state["query"], state["pricing_currency"]
            )
        except Exception as exc:  # noqa: BLE001 - frontera CrewAI/MCP
            return {
                "errors": _with_error(state, "investigación", exc),
                "review_status": "error",
                "report_status": "error",
                "research_attempts": state["research_attempts"] + 1,
            }
        return {
            "references": references.model_dump(mode="json"),
            "research_attempts": state["research_attempts"] + 1,
        }

    def calculation_node(state: AmiguPrecioGraphState) -> dict[str, object]:
        if state["deterministic_analysis"] is not None:
            return {}
        references_data = state["references"]
        if references_data is None:
            return {
                "errors": [*state["errors"], "cálculo: faltan referencias verificadas"],
                "review_status": "error",
                "report_status": "error",
            }
        chart_path = Path(state["output_dir"]) / "market-comparison.png"
        try:
            references = ReferenceSearchResult.model_validate(references_data)
            analysis = services.calculate(
                PricingInput.model_validate(state["product"]),
                references.references,
                chart_path,
                state["pricing_currency"],
            )
        except Exception as exc:  # noqa: BLE001 - frontera Python preservada
            return {
                "errors": _with_error(state, "cálculo", exc),
                "review_status": "error",
                "report_status": "error",
                "calculation_attempts": state["calculation_attempts"] + 1,
            }
        return {
            "deterministic_analysis": analysis.model_dump(mode="json"),
            "chart_path": analysis.chart_path,
            "calculation_attempts": state["calculation_attempts"] + 1,
        }

    def analyst_node(state: AmiguPrecioGraphState) -> dict[str, object]:
        analysis_data = state["deterministic_analysis"]
        if analysis_data is None:
            return {}
        analysis = DeterministicAnalysis.model_validate(analysis_data)
        try:
            observations = services.analyze(analysis, state["pricing_currency"])
        except Exception as exc:  # noqa: BLE001 - salida recuperable del agente
            return {
                "analyst_observations": None,
                "commercial_assessment": None,
                "errors": _with_error(state, "analista", exc),
                "analyst_attempts": state["analyst_attempts"] + 1,
            }
        return {
            "analyst_observations": observations,
            "commercial_assessment": None,
            "analyst_attempts": state["analyst_attempts"] + 1,
        }

    def advisor_node(state: AmiguPrecioGraphState) -> dict[str, object]:
        analysis_data = state["deterministic_analysis"]
        observations = state["analyst_observations"]
        if analysis_data is None or not observations:
            return {}
        analysis = DeterministicAnalysis.model_validate(analysis_data)
        try:
            assessment = services.advise(
                analysis,
                observations,
                state["pricing_currency"],
            )
        except Exception as exc:  # noqa: BLE001 - salida recuperable del agente
            return {
                "commercial_assessment": None,
                "errors": _with_error(state, "asesor", exc),
                "advisor_attempts": state["advisor_attempts"] + 1,
            }
        result: dict[str, object] = {
            "commercial_assessment": assessment.model_dump(mode="json"),
            "advisor_attempts": state["advisor_attempts"] + 1,
        }
        if state["visual_requested"]:
            visual = (
                services.get_visual_analysis()
                if services.get_visual_analysis is not None
                else None
            )
            visual_error = (
                services.get_visual_error()
                if services.get_visual_error is not None
                else "La herramienta visual no está disponible"
            )
            if visual is not None:
                result.update(
                    visual_status="completed",
                    visual_analysis=visual.model_dump(mode="json"),
                    visual_error=None,
                )
            else:
                result.update(
                    visual_status="failed",
                    visual_error=visual_error or "El asesor no ejecutó la herramienta visual",
                )
        return result

    def review_node(state: AmiguPrecioGraphState) -> dict[str, object]:
        references_data = state["references"]
        analysis_data = state["deterministic_analysis"]
        if references_data is None or analysis_data is None:
            return {
                "review_status": "error",
                "retry_stage": None,
                "report_status": "error",
                "errors": [*state["errors"], "revisión: faltan resultados esenciales"],
            }
        references = ReferenceSearchResult.model_validate(references_data)
        analysis = DeterministicAnalysis.model_validate(analysis_data)
        if references.references != analysis.references:
            return {
                "review_status": "error",
                "retry_stage": None,
                "report_status": "error",
                "errors": [
                    *state["errors"],
                    "revisión: se perdió la trazabilidad de las referencias",
                ],
            }
        if state["chart_path"] != analysis.chart_path:
            return {
                "review_status": "error",
                "retry_stage": None,
                "report_status": "error",
                "errors": [*state["errors"], "revisión: el gráfico actual no coincide"],
            }
        observations = state["analyst_observations"] or ""
        try:
            validate_analyst_observations(observations, analysis)
        except Exception as exc:  # noqa: BLE001 - decide el reintento acotado
            return _retry_or_error(
                state,
                "analyst",
                f"revisión del analista: {type(exc).__name__}",
            )
        assessment_data = state["commercial_assessment"]
        if assessment_data is None:
            return _retry_or_error(
                state,
                "advisor",
                "revisión del asesor: salida ausente",
            )
        try:
            validated = CommercialAssessment.model_validate(assessment_data)
            ensure_assessment_uses_authoritative_numbers(
                validated,
                analysis.model_dump(mode="json"),
            )
            validated = enforce_supported_commercial_assessment(validated, analysis)
        except Exception as exc:  # noqa: BLE001 - decide el reintento acotado
            return _retry_or_error(
                state,
                "advisor",
                f"revisión del asesor: {type(exc).__name__}",
            )
        return {
            "commercial_assessment": validated.model_dump(mode="json"),
            "review_status": "approved",
            "retry_stage": None,
        }

    def approval_node(state: AmiguPrecioGraphState) -> dict[str, object]:
        decision = interrupt(
            {
                "question": "¿Apruebas la generación del informe de AmiguPrecio?",
                "product": str(state["product"]["product_name"]),
                "calculated_price": str(
                    state["deterministic_analysis"]["pricing"]["calculated_price"]
                ),
                "currency": state["pricing_currency"],
            }
        )
        approved = (
            decision is True
            or isinstance(decision, dict)
            and decision.get("approved") is True
        )
        if approved:
            return {"human_decision": "approved"}
        return {"human_decision": "rejected", "report_status": "not_saved"}

    def report_node(state: AmiguPrecioGraphState) -> dict[str, object]:
        if state["human_decision"] != "approved":
            return {"report_status": "not_saved"}
        references_data = state["references"]
        analysis_data = state["deterministic_analysis"]
        observations = state["analyst_observations"]
        assessment_data = state["commercial_assessment"]
        if not all([references_data, analysis_data, observations, assessment_data]):
            return {
                "report_status": "error",
                "errors": [*state["errors"], "informe: faltan datos aprobados"],
            }
        references = ReferenceSearchResult.model_validate(references_data)
        analysis = DeterministicAnalysis.model_validate(analysis_data)
        assessment = CommercialAssessment.model_validate(assessment_data)
        content = render_markdown_report(
            PricingInput.model_validate(state["product"]),
            references,
            analysis,
            observations,
            assessment,
            pricing_currency=state["pricing_currency"],
            visual_analysis=(
                VisualAnalysis.model_validate(state["visual_analysis"])
                if state["visual_analysis"] is not None
                else None
            ),
            visual_error=state["visual_error"],
        )
        try:
            path = services.save_report(
                Path(state["requested_report_path"]), content
            )
        except Exception as exc:  # noqa: BLE001 - frontera de persistencia
            return {
                "report_status": "error",
                "errors": _with_error(state, "informe", exc),
            }
        return {"report_status": "saved", "report_path": str(path)}

    def after_research(state: AmiguPrecioGraphState) -> str:
        return "calculation" if state["references"] is not None else "review"

    def after_calculation(state: AmiguPrecioGraphState) -> str:
        return "analyst" if state["deterministic_analysis"] is not None else "review"

    def after_analyst(state: AmiguPrecioGraphState) -> str:
        return "advisor" if state["analyst_observations"] else "review"

    def after_review(state: AmiguPrecioGraphState) -> str:
        if state["review_status"] == "approved":
            return "approval"
        if state["review_status"] == "retry":
            return state["retry_stage"] or "end"
        return "end"

    def after_approval(state: AmiguPrecioGraphState) -> str:
        return "report" if state["human_decision"] == "approved" else "end"

    builder = StateGraph(AmiguPrecioGraphState)
    builder.add_node("research", research_node)
    builder.add_node("calculation", calculation_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("advisor", advisor_node)
    builder.add_node("review", review_node)
    builder.add_node("approval", approval_node)
    builder.add_node("report", report_node)
    builder.add_edge(START, "research")
    builder.add_conditional_edges(
        "research", after_research, {"calculation": "calculation", "review": "review"}
    )
    builder.add_conditional_edges(
        "calculation", after_calculation, {"analyst": "analyst", "review": "review"}
    )
    builder.add_conditional_edges(
        "analyst", after_analyst, {"advisor": "advisor", "review": "review"}
    )
    builder.add_edge("advisor", "review")
    builder.add_conditional_edges(
        "review",
        after_review,
        {"analyst": "analyst", "advisor": "advisor", "approval": "approval", "end": END},
    )
    builder.add_conditional_edges(
        "approval", after_approval, {"report": "report", "end": END}
    )
    builder.add_edge("report", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())
