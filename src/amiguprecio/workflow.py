"""Coordinación híbrida: agentes reales alrededor de un núcleo determinista."""

from __future__ import annotations

import json
from pathlib import Path

from crewai import LLM, Agent, Crew, Process, Task
from pydantic import BaseModel, Field

from amiguprecio.agents import (
    CommercialAssessment,
    MCPReferenceSearchTool,
    PricingAnalysisTool,
    create_agents,
    ensure_assessment_uses_authoritative_numbers,
    ensure_text_uses_authoritative_numbers,
    validate_commercial_assessment,
)
from amiguprecio.analysis import MarketStatistics
from amiguprecio.models import PricingInput, PricingResult
from amiguprecio.references import MarketReference, ReferenceSearchResult


class DeterministicAnalysis(BaseModel):
    """Fuente oficial de cifras, referencias y gráfico de una ejecución."""

    pricing: PricingResult
    statistics: MarketStatistics
    references: list[MarketReference]
    chart_path: str


class WorkflowAction(BaseModel):
    actor: str
    action: str
    execution: str
    status: str


class HybridWorkflowResult(BaseModel):
    references: ReferenceSearchResult | None = None
    deterministic_analysis: DeterministicAnalysis | None = None
    analyst_observations: str | None = None
    commercial_assessment: CommercialAssessment | None = None
    actions: list[WorkflowAction] = Field(default_factory=list)
    usage: dict[str, dict[str, object]] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    completed: bool = False


class AgentOutputError(ValueError):
    """Un agente no produjo una salida utilizable y verificable."""


def run_deterministic_analysis(
    pricing_input: PricingInput,
    references: list[MarketReference],
    chart_path: Path,
    pricing_currency: str = "EUR",
) -> DeterministicAnalysis:
    """Ejecuta la herramienta Python directamente, sin decisión del LLM."""

    pricing_data = pricing_input.model_dump(mode="json")
    tool_references = [
        {
            "source_url": str(reference.source_url),
            "price": str(reference.price),
            "currency": reference.currency,
            "checked_at": reference.checked_at.isoformat(),
            "provenance": reference.provenance,
        }
        for reference in references
    ]
    raw_result = PricingAnalysisTool()._run(
        **pricing_data,
        references=tool_references,
        pricing_currency=pricing_currency,
        chart_path=str(chart_path),
    )
    return DeterministicAnalysis(
        pricing=PricingResult.model_validate(raw_result["pricing"]),
        statistics=MarketStatistics.model_validate(raw_result["statistics"]),
        references=references,
        chart_path=raw_result["chart_path"],
    )


def validate_analyst_observations(
    raw_output: str, deterministic_analysis: DeterministicAnalysis
) -> str:
    """Acepta interpretación no vacía que no contradiga las cifras Python."""

    observations = raw_output.strip()
    if not observations:
        raise AgentOutputError("El analista devolvió una respuesta vacía")
    ensure_text_uses_authoritative_numbers(
        observations,
        deterministic_analysis.model_dump(mode="json"),
    )
    return observations


def _usage_dict(crew_output: object) -> dict[str, object]:
    token_usage = getattr(crew_output, "token_usage", None)
    if token_usage is None:
        return {}
    if hasattr(token_usage, "model_dump"):
        return token_usage.model_dump(mode="json")
    return {}


def _safe_agent_error(stage: str, exc: Exception) -> str:
    return f"{stage}: {type(exc).__name__}"


def run_research_agent(
    researcher: Agent,
    research_tool: MCPReferenceSearchTool,
    query: str,
    *,
    pricing_currency: str = "EUR",
    output_log_file: str | None = None,
) -> tuple[ReferenceSearchResult, dict[str, object]]:
    """Ejecuta una única investigación CrewAI y conserva el resultado MCP tipado."""

    task = Task(
        description=(
            "Usa search_market_references exactamente una vez con query={query}, "
            "max_results=3, live=false y currency={pricing_currency}. Devuelve el resultado "
            "de la herramienta sin reconstruir precios, monedas ni fuentes."
        ),
        expected_output="Resultado JSON exacto del servidor MCP.",
        agent=researcher,
    )
    output = Crew(
        agents=[researcher],
        tasks=[task],
        process=Process.sequential,
        output_log_file=output_log_file,
        verbose=False,
    ).kickoff(inputs={"query": query, "pricing_currency": pricing_currency})
    if research_tool.last_result is None:
        raise AgentOutputError("El investigador no ejecutó la herramienta MCP")
    return research_tool.last_result, _usage_dict(output)


def analyst_payload(
    analysis: DeterministicAnalysis, pricing_currency: str = "EUR"
) -> dict[str, object]:
    """Reduce la entrada narrativa a resultados oficiales y comparabilidad."""

    return {
        "production_cost": str(analysis.pricing.production_cost),
        "calculated_price": str(analysis.pricing.calculated_price),
        "margin_percent": str(analysis.pricing.margin_percent),
        "pricing_currency": pricing_currency,
        "valid_reference_count": analysis.statistics.valid_reference_count,
        "reference_currencies": sorted(
            {reference.currency for reference in analysis.references}
        ),
        "market_mean": (
            str(analysis.statistics.mean)
            if analysis.statistics.mean is not None
            else None
        ),
    }


def run_analyst_agent(
    analyst: Agent,
    analysis: DeterministicAnalysis,
    *,
    output_log_file: str | None = None,
    pricing_currency: str = "EUR",
) -> tuple[str, dict[str, object]]:
    """Ejecuta solo la interpretación CrewAI, sin herramientas ni recálculo."""

    payload = json.dumps(
        analyst_payload(analysis, pricing_currency), ensure_ascii=False
    )
    task = Task(
        description=(
            f"Interpreta estos resultados oficiales de Python: {payload}. "
            "No recalcules ni cambies cifras. Si no hay referencias comparables, dilo "
            "expresamente y no inventes una media. Responde en menos de 80 palabras."
        ),
        expected_output="Interpretación comercial breve basada únicamente en Python.",
        agent=analyst,
    )
    output = Crew(
        agents=[analyst],
        tasks=[task],
        process=Process.sequential,
        output_log_file=output_log_file,
        verbose=False,
    ).kickoff()
    return validate_analyst_observations(output.raw, analysis), _usage_dict(output)


def run_advisor_agent(
    advisor: Agent,
    analysis: DeterministicAnalysis,
    observations: str,
    *,
    output_log_file: str | None = None,
    pricing_currency: str = "EUR",
    use_vision: bool = False,
) -> tuple[CommercialAssessment, dict[str, object]]:
    """Ejecuta solo la valoración CrewAI y valida localmente su JSON."""

    payload = json.dumps(
        {
            "analysis": analyst_payload(analysis, pricing_currency),
            "analyst_observations": observations,
        },
        ensure_ascii=False,
    )
    vision_instruction = (
        " Usa analyze_uploaded_amigurumi_image exactamente una vez. Limita las "
        "observaciones visuales a su resultado; si falla, continúa con los datos no "
        "visuales e incluye esa limitación. Las limitaciones visuales significan solo "
        "que un dato no puede inferirse de la foto: no declares desconocido un coste, "
        "precio o margen que sí figure en el resultado oficial de Python."
        if use_vision
        else ""
    )
    task = Task(
        description=(
            f"Valora exclusivamente estos datos: {payload}. No recalcules ni sustituyas "
            "cifras. Devuelve solo JSON válido con comparability, market_position, "
            "recommendation y limitations. limitations debe ser siempre un array JSON "
            "de cadenas, incluso cuando solo exista una limitación."
            f"{vision_instruction}"
        ),
        expected_output="JSON textual compatible con CommercialAssessment.",
        agent=advisor,
    )
    output = Crew(
        agents=[advisor],
        tasks=[task],
        process=Process.sequential,
        output_log_file=output_log_file,
        verbose=False,
    ).kickoff()
    assessment = validate_commercial_assessment(output.raw)
    ensure_assessment_uses_authoritative_numbers(
        assessment, analysis.model_dump(mode="json")
    )
    return assessment, _usage_dict(output)


def run_hybrid_workflow(
    pricing_input: PricingInput,
    query: str,
    output_dir: Path,
    llm: LLM | None = None,
) -> HybridWorkflowResult:
    """Ejecuta investigación, cálculo, interpretación y asesoría sin repetir etapas."""

    output_dir.mkdir(parents=True, exist_ok=True)
    result = HybridWorkflowResult()
    research_tool = MCPReferenceSearchTool()
    researcher, analyst, advisor = create_agents(llm=llm, research_tool=research_tool)
    crew_log = str(output_dir / "hybrid-crewai.json")

    try:
        references_result, result.usage["researcher"] = run_research_agent(
            researcher,
            research_tool,
            query,
            pricing_currency="EUR",
            output_log_file=crew_log,
        )
    except Exception as exc:  # noqa: BLE001 - frontera externa redactada
        result.errors.append(_safe_agent_error("investigador", exc))
        result.actions.append(
            WorkflowAction(
                actor=researcher.role,
                action="search_market_references mediante cliente MCP",
                execution="autónoma por agente CrewAI",
                status="error",
            )
        )
        return result

    result.references = references_result
    result.actions.append(
        WorkflowAction(
            actor=researcher.role,
            action="search_market_references mediante cliente MCP",
            execution="autónoma por agente CrewAI",
            status="completada",
        )
    )

    try:
        analysis = run_deterministic_analysis(
            pricing_input,
            references_result.references,
            output_dir / "market-comparison.png",
        )
    except Exception as exc:  # noqa: BLE001 - resultado parcial preservado
        result.errors.append(_safe_agent_error("coordinador Python", exc))
        return result
    result.deterministic_analysis = analysis
    result.actions.append(
        WorkflowAction(
            actor="Coordinador Python",
            action="PricingAnalysisTool: cálculo, estadísticas y gráfico",
            execution="invocación determinista directa; no autónoma por LLM",
            status="completada",
        )
    )

    try:
        result.analyst_observations, result.usage["analyst"] = run_analyst_agent(
            analyst,
            analysis,
            output_log_file=crew_log,
        )
    except Exception as exc:  # noqa: BLE001 - no se repiten MCP ni cálculo
        result.errors.append(_safe_agent_error("analista", exc))
        result.actions.append(
            WorkflowAction(
                actor=analyst.role,
                action="interpretación del resultado Python",
                execution="agente CrewAI real, sin herramientas",
                status="error",
            )
        )
        return result
    result.actions.append(
        WorkflowAction(
            actor=analyst.role,
            action="interpretación del resultado Python",
            execution="agente CrewAI real, sin herramientas",
            status="completada",
        )
    )

    try:
        result.commercial_assessment, result.usage["advisor"] = run_advisor_agent(
            advisor,
            analysis,
            result.analyst_observations,
            output_log_file=crew_log,
        )
    except Exception as exc:  # noqa: BLE001 - salida externa validada y redactada
        result.errors.append(_safe_agent_error("asesor", exc))
        result.actions.append(
            WorkflowAction(
                actor=advisor.role,
                action="valoración comercial JSON",
                execution="agente CrewAI real, validación Pydantic posterior",
                status="error",
            )
        )
        return result
    result.actions.append(
        WorkflowAction(
            actor=advisor.role,
            action="valoración comercial JSON",
            execution="agente CrewAI real, validación Pydantic posterior",
            status="completada",
        )
    )
    result.completed = True
    return result
