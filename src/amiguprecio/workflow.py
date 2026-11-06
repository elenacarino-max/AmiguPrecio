"""Coordinación híbrida: agentes reales alrededor de un núcleo determinista."""

from __future__ import annotations

import json
import re
from pathlib import Path

from crewai import LLM, Agent, Crew, Process, Task
from pydantic import BaseModel, Field

from amiguprecio.agents import (
    CommercialAssessment,
    CommercialAssessmentSubmissionTool,
    MCPReferenceSearchTool,
    PricingAnalysisTool,
    create_agents,
    ensure_assessment_uses_authoritative_numbers,
    ensure_text_uses_authoritative_numbers,
    validate_commercial_assessment,
)
from amiguprecio.analysis import (
    CommercialComparability,
    MarketStatistics,
    evaluate_commercial_comparability,
)
from amiguprecio.models import PricingInput, PricingResult
from amiguprecio.references import MarketReference, ReferenceSearchResult


class DeterministicAnalysis(BaseModel):
    """Fuente oficial de cifras, referencias y gráfico de una ejecución."""

    pricing: PricingResult
    statistics: MarketStatistics
    commercial_comparability: CommercialComparability
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

    # La altura pertenece al producto y a la comparación comercial, no al
    # contrato monetario de la herramienta Python.
    pricing_data = pricing_input.model_dump(mode="json", exclude={"height_cm"})
    tool_references = [
        {
            "title": reference.title,
            "source_name": reference.source_name,
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
        commercial_comparability=evaluate_commercial_comparability(
            pricing_input,
            references,
            pricing_currency,
        ),
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
    comparison = deterministic_analysis.commercial_comparability
    if (
        comparison.sample_is_heterogeneous
        or comparison.directly_comparable_count < 3
        or _UNSUPPORTED_COMMERCIAL_CLAIMS.search(observations)
    ):
        pricing = deterministic_analysis.pricing
        statistics = deterministic_analysis.statistics
        sample_text = (
            f" La media de la muestra monetaria es {statistics.mean:.2f} EUR, pero no "
            "representa una media de productos directamente comparables."
            if statistics.mean is not None
            else " No existe una muestra en EUR para calcular una media."
        )
        return (
            f"Python fija {pricing.production_cost:.2f} EUR de coste y "
            f"{pricing.calculated_price:.2f} EUR de precio con un margen objetivo del "
            f"{pricing.margin_percent:.2f} %.{sample_text} "
            "No es posible determinar el posicionamiento de mercado con estas referencias."
        )
    return observations


_UNSUPPORTED_COMMERCIAL_CLAIMS = re.compile(
    r"\b(premium|lujo|alta\s+gama)\b|"
    r"margen.{0,35}posicion|posicion.{0,35}margen|"
    r"(?:ventas|demanda).{0,25}(?:prueba|demuestra)|"
    r"(?:prueba|demuestra).{0,25}(?:ventas|demanda)|"
    r"\b(?:alta|fuerte)\s+demanda\b|demanda\s+(?:alta|fuerte|demostrada)|"
    r"ventas\s+(?:altas|demostradas|garantizadas)|"
    r"mantener\s+(?:el\s+)?precio|"
    r"no\s+(?:hay|existen)\s+discrepancias",
    flags=re.IGNORECASE,
)


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(value.split()).strip()
        key = cleaned.casefold().rstrip(".")
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def enforce_supported_commercial_assessment(
    assessment: CommercialAssessment,
    analysis: DeterministicAnalysis,
) -> CommercialAssessment:
    """Sustituye afirmaciones no respaldadas sin realizar otra llamada al LLM."""

    comparison = analysis.commercial_comparability
    narrative = (
        f"{assessment.comparability} {assessment.market_position} "
        f"{assessment.recommendation}"
    )
    sufficient = (
        comparison.directly_comparable_count >= 3
        and not comparison.sample_is_heterogeneous
    )
    unsupported_claim = bool(_UNSUPPORTED_COMMERCIAL_CLAIMS.search(narrative))
    if sufficient and not unsupported_claim:
        return assessment.model_copy(
            update={
                "limitations": _ordered_unique(
                    [
                        *assessment.limitations,
                        "Los precios anunciados no prueban ventas ni demanda.",
                        "El margen objetivo no determina el posicionamiento de mercado.",
                    ]
                )
            }
        )

    limitations = _ordered_unique(
        [
            *comparison.limitations,
            *assessment.limitations,
            "Los precios anunciados no prueban ventas ni demanda.",
            "El margen objetivo no determina el posicionamiento de mercado.",
        ]
    )
    return CommercialAssessment(
        comparability=(
            "Insuficiente: las referencias comparten moneda, pero no existe evidencia "
            "suficiente de equivalencia por tipo, tamaño y características."
        ),
        market_position="No es posible determinar el posicionamiento de mercado con estas referencias.",
        recommendation=(
            "Usar el precio calculado como base de costes y reunir referencias más "
            "equivalentes antes de tomar una decisión comercial."
        ),
        limitations=limitations,
    )


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
    product_name: str | None = None,
    category: str | None = None,
    height_cm: str | None = None,
    output_log_file: str | None = None,
) -> tuple[ReferenceSearchResult, dict[str, object]]:
    """Ejecuta una única investigación CrewAI y conserva el resultado MCP tipado."""

    if product_name and category:
        tool_instruction = (
            "Usa search_market_references exactamente una vez con query={query}, "
            "product_name={product_name}, category={category}, "
        )
        if height_cm is not None:
            tool_instruction += "height_cm={height_cm}, "
        else:
            tool_instruction += "omite por completo el argumento opcional height_cm, "
        tool_instruction += "max_results=10, live=true y currency={pricing_currency}. "
    else:
        tool_instruction = (
            "Usa search_market_references exactamente una vez con query={query}, "
            "max_results=3, live=false y currency={pricing_currency}. "
        )
    task = Task(
        description=(
            tool_instruction
            + "Devuelve el resultado "
            "de la herramienta sin reconstruir precios, monedas ni fuentes."
        ),
        expected_output="Resultado JSON exacto del servidor MCP.",
        agent=researcher,
    )
    crew_inputs = {
        "query": query,
        "pricing_currency": pricing_currency,
        "product_name": product_name or query,
        "category": category or query,
    }
    if height_cm is not None:
        crew_inputs["height_cm"] = height_cm
    output = Crew(
        agents=[researcher],
        tasks=[task],
        process=Process.sequential,
        output_log_file=output_log_file,
        verbose=False,
    ).kickoff(inputs=crew_inputs)
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
        "currency_sample_count": analysis.statistics.valid_reference_count,
        "reference_currencies": sorted(
            {reference.currency for reference in analysis.references}
        ),
        "currency_sample_mean": (
            str(analysis.statistics.mean)
            if analysis.statistics.mean is not None
            else None
        ),
        "commercial_comparability": analysis.commercial_comparability.model_dump(
            mode="json"
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
            "No recalcules ni cambies cifras. Distingue muestra por moneda de productos "
            "directamente comparables. No infieras posicionamiento, ventas o demanda, ni "
            "relaciones el margen con el posicionamiento. Responde en menos de 80 palabras."
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
        " Usa primero analyze_uploaded_amigurumi_image exactamente una vez. Limita las "
        "observaciones visuales a su resultado; si falla, continúa con los datos no "
        "visuales e incluye esa limitación. Las limitaciones visuales significan solo "
        "que un dato no puede inferirse de la foto: no declares desconocido un coste, "
        "precio o margen que sí figure en el resultado oficial de Python. Después "
        "entrega la valoración con submit_commercial_assessment."
        if use_vision
        else " Usa submit_commercial_assessment exactamente una vez para entregar el resultado."
    )
    task = Task(
        description=(
            f"Valora exclusivamente estos datos: {payload}. No recalcules ni sustituyas "
            "cifras. Compartir moneda no implica comparabilidad por tipo, tamaño o "
            "características. Una diferencia frente a una media pequeña no demuestra un "
            "posicionamiento premium. El margen objetivo no determina posicionamiento. "
            "Los precios anunciados no prueban ventas ni demanda. No recomiendes mantener "
            "un precio actual que la persona no haya aportado. Si la comparabilidad es "
            "insuficiente, indica que no puede determinarse el posicionamiento. La entrega "
            "final debe contener comparability, market_position, recommendation y "
            "limitations; limitations debe ser siempre un array de cadenas. No uses "
            "output_pydantic ni añadas campos."
            f"{vision_instruction}"
        ),
        expected_output="JSON textual compatible con CommercialAssessment.",
        agent=advisor,
    )
    submission_tool = next(
        (
            tool
            for tool in advisor.tools
            if isinstance(tool, CommercialAssessmentSubmissionTool)
        ),
        None,
    )
    if submission_tool is not None:
        submission_tool.reset_result()
    output = Crew(
        agents=[advisor],
        tasks=[task],
        process=Process.sequential,
        output_log_file=output_log_file,
        verbose=False,
    ).kickoff()
    assessment = (
        submission_tool.last_result
        if submission_tool is not None and submission_tool.last_result is not None
        else validate_commercial_assessment(output.raw)
    )
    ensure_assessment_uses_authoritative_numbers(
        assessment, analysis.model_dump(mode="json")
    )
    return enforce_supported_commercial_assessment(assessment, analysis), _usage_dict(output)


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
