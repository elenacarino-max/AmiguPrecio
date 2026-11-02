"""Tres agentes CrewAI configurables para ejecución real y limitada."""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from crewai import LLM, Agent, Crew, Process, Task
from crewai.llms.cache import CACHE_BREAKPOINT_KEY
from crewai.tools import BaseTool
from dotenv import load_dotenv
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
)

from amiguprecio.analysis import calculate_market_statistics, create_price_chart
from amiguprecio.mcp_client import search_references_mcp_sync
from amiguprecio.models import PricingInput
from amiguprecio.pricing import calculate_price
from amiguprecio.references import MarketReference, ReferenceSearchResult
from amiguprecio.vision import (
    PreparedImage,
    VisionProviderError,
    VisualAnalysis,
    analyze_image_with_groq,
)


def _parse_finite_decimal(value: str, *, positive: bool = False) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("El valor debe ser una cadena decimal válida") from exc
    if not parsed.is_finite():
        raise ValueError("El valor debe ser un número finito")
    if positive and parsed <= 0:
        raise ValueError("El valor debe ser mayor que cero")
    if not positive and parsed < 0:
        raise ValueError("El valor no puede ser negativo")
    return parsed


class ToolMarketReference(BaseModel):
    """Referencia mínima y trazable para cálculos monetarios."""

    model_config = ConfigDict(extra="forbid")

    price: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    source_url: str
    checked_at: str
    provenance: Literal["live", "saved"]

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: str) -> str:
        _parse_finite_decimal(value, positive=True)
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("La referencia necesita una URL HTTP verificable")
        return value

    def to_domain(self) -> MarketReference:
        source_host = urlsplit(self.source_url).hostname
        if not source_host:
            raise ValueError("No se pudo identificar la fuente de la referencia")
        return MarketReference(
            title=self.source_url,
            price=_parse_finite_decimal(self.price, positive=True),
            currency=self.currency,
            source_url=self.source_url,
            checked_at=self.checked_at,
            source_name=source_host,
            provenance=self.provenance,
        )


class PricingToolInput(BaseModel):
    product_name: str
    product_type: str
    materials_cost: str
    hours_worked: str
    hourly_rate: str
    other_expenses: str = "0"
    margin_percent: str
    references: list[ToolMarketReference] = Field(default_factory=list)
    pricing_currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    chart_path: str = "output/charts/market_comparison.png"

    @field_validator(
        "materials_cost", "hours_worked", "hourly_rate", "other_expenses"
    )
    @classmethod
    def validate_nonnegative_decimal(cls, value: str) -> str:
        _parse_finite_decimal(value)
        return value

    @field_validator("margin_percent")
    @classmethod
    def validate_margin(cls, value: str) -> str:
        parsed = _parse_finite_decimal(value)
        if parsed >= 100:
            raise ValueError("El margen debe ser menor que 100")
        return value


class PricingAnalysisTool(BaseTool):
    name: str = "calculate_and_compare_prices"
    description: str = (
        "Calcula costes con la fórmula validada y estadísticas de la muestra por moneda."
    )
    args_schema: type[BaseModel] = PricingToolInput
    result_as_answer: bool = True

    def _run(self, **kwargs: object) -> dict:
        tool_input = PricingToolInput.model_validate(kwargs)
        pricing = calculate_price(
            PricingInput(
                product_name=tool_input.product_name,
                product_type=tool_input.product_type,
                materials_cost=_parse_finite_decimal(tool_input.materials_cost),
                hours_worked=_parse_finite_decimal(tool_input.hours_worked),
                hourly_rate=_parse_finite_decimal(tool_input.hourly_rate),
                other_expenses=_parse_finite_decimal(tool_input.other_expenses),
                margin_percent=_parse_finite_decimal(tool_input.margin_percent),
            )
        )
        references = [reference.to_domain() for reference in tool_input.references]
        statistics = calculate_market_statistics(
            pricing, references, tool_input.pricing_currency
        )
        chart = create_price_chart(
            pricing,
            references,
            Path(tool_input.chart_path),
            tool_input.pricing_currency,
        )
        result = {
            "pricing": pricing.model_dump(mode="json"),
            "statistics": statistics.model_dump(mode="json"),
            "chart_path": str(chart),
        }
        trace_path = os.getenv("AMIGUPRECIO_PRICING_TRACE")
        if trace_path:
            destination = Path(trace_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(
                    {
                        "arguments": tool_input.model_dump(mode="json"),
                        "python_result": result,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        return result


class MCPReferenceSearchInput(BaseModel):
    query: str
    max_results: int = Field(default=3, ge=1, le=3)
    live: bool = False
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class MCPReferenceSearchTool(BaseTool):
    """Herramienta CrewAI que conserva el resultado tipado del cliente MCP real."""

    name: str = "search_market_references"
    description: str = (
        "Consulta una vez el servidor MCP y devuelve referencias comerciales verificadas."
    )
    args_schema: type[BaseModel] = MCPReferenceSearchInput
    result_as_answer: bool = True
    max_usage_count: int | None = 1
    _last_result: ReferenceSearchResult | None = PrivateAttr(default=None)

    @property
    def last_result(self) -> ReferenceSearchResult | None:
        return self._last_result

    def _run(self, **kwargs: object) -> dict:
        tool_input = MCPReferenceSearchInput.model_validate(kwargs)
        self._last_result = search_references_mcp_sync(
            query=tool_input.query,
            max_results=tool_input.max_results,
            live=tool_input.live,
            currency=tool_input.currency,
        )
        return self._last_result.model_dump(mode="json")


class VisionAnalysisInput(BaseModel):
    action: Literal["analyze"] = "analyze"


class VisionAnalysisTool(BaseTool):
    """Herramienta visual acotada al archivo validado de esta ejecución."""

    name: str = "analyze_uploaded_amigurumi_image"
    description: str = (
        "Analiza una vez la fotografía ya validada y devuelve solo rasgos visibles y "
        "limitaciones. No estima costes, tamaño, materiales, calidad o demanda."
    )
    args_schema: type[BaseModel] = VisionAnalysisInput
    max_usage_count: int | None = 1
    _image: PreparedImage = PrivateAttr()
    _last_result: VisualAnalysis | None = PrivateAttr(default=None)
    _last_error: str | None = PrivateAttr(default=None)

    def __init__(self, image: PreparedImage, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._image = image

    @property
    def last_result(self) -> VisualAnalysis | None:
        return self._last_result

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _run(self, **kwargs: object) -> dict[str, object]:
        VisionAnalysisInput.model_validate(kwargs)
        try:
            call = analyze_image_with_groq(self._image)
        except VisionProviderError as exc:
            self._last_error = str(exc)
            return {"status": "failed", "error": self._last_error}
        self._last_result = call.analysis
        self._last_error = None
        return {
            "status": "completed",
            "analysis": call.analysis.model_dump(mode="json"),
        }


class CommercialAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparability: str = Field(description="Alta, media, baja o insuficiente, con motivo")
    market_position: str
    recommendation: str
    limitations: list[str]

    @field_validator("limitations", mode="before")
    @classmethod
    def normalize_single_limitation(cls, value: object) -> object:
        """Normaliza solo el caso real de una limitación textual única."""

        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            return [value]
        raise ValueError("limitations debe ser un array JSON de cadenas no vacío")


class AssessmentValidationError(ValueError):
    """La valoración del asesor no cumple el contrato verificable."""


def validate_commercial_assessment(raw_output: str) -> CommercialAssessment:
    """Valida JSON textual del tercer agente sin una llamada adicional al LLM."""

    text = raw_output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return CommercialAssessment.model_validate_json(text)
    except (ValidationError, ValueError) as exc:
        raise AssessmentValidationError(
            "La salida del asesor no es JSON válido para CommercialAssessment"
        ) from exc


_DECIMAL_CLAIM = re.compile(r"(?<![\d.])\d+[.,]\d{2}(?!\d)")


def _collect_authoritative_decimals(value: object) -> set[Decimal]:
    collected: set[Decimal] = set()
    if isinstance(value, dict):
        for nested in value.values():
            collected.update(_collect_authoritative_decimals(nested))
    elif isinstance(value, list):
        for nested in value:
            collected.update(_collect_authoritative_decimals(nested))
    elif isinstance(value, (Decimal, int, float, str)) and not isinstance(value, bool):
        try:
            parsed = Decimal(str(value).replace(",", "."))
        except InvalidOperation:
            pass
        else:
            if parsed.is_finite():
                collected.add(parsed.quantize(Decimal("0.01")))
    return collected


def ensure_assessment_uses_authoritative_numbers(
    assessment: CommercialAssessment, python_trace: dict[str, object]
) -> None:
    """Rechaza cifras decimales del asesor que no aparezcan en la traza Python."""

    narrative = " ".join(
        [
            assessment.comparability,
            assessment.market_position,
            assessment.recommendation,
            *assessment.limitations,
        ]
    )
    ensure_text_uses_authoritative_numbers(narrative, python_trace)


def ensure_text_uses_authoritative_numbers(
    narrative: str, python_trace: dict[str, object]
) -> None:
    """Impide que una redacción del LLM introduzca decimales no oficiales."""

    allowed = _collect_authoritative_decimals(python_trace)
    claims = {
        Decimal(match.replace(",", ".")).quantize(Decimal("0.01"))
        for match in _DECIMAL_CLAIM.findall(narrative)
    }
    contradictions = sorted(claims - allowed)
    if contradictions:
        values = ", ".join(str(value) for value in contradictions)
        raise AssessmentValidationError(
            f"La valoración contiene cifras no respaldadas por Python: {values}"
        )


class GroqCompatibleLLM(LLM):
    """Adaptación temporal para crewAI#5886, aislada al proveedor Groq."""

    def _format_messages_for_provider(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        formatted = super()._format_messages_for_provider(messages)
        if not self.model.lower().startswith("groq/"):
            return formatted
        return [
            {key: value for key, value in message.items() if key != CACHE_BREAKPOINT_KEY}
            for message in formatted
        ]


def create_llm(
    *,
    model_env: str = "GROQ_MODEL",
    max_tokens: int = 600,
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"]
    | None = None,
    include_reasoning: bool | None = None,
    max_retries: int = 1,
) -> LLM:
    """Construye un LLM Groq configurable sin registrar credenciales."""

    load_dotenv()
    model = os.getenv(model_env) or os.getenv(
        "GROQ_MODEL", "groq/openai/gpt-oss-20b"
    )
    api_key = os.getenv("GROQ_API_KEY")
    if model.startswith("groq/") and not api_key:
        raise RuntimeError("Falta GROQ_API_KEY para ejecutar CrewAI con Groq")
    llm_class = GroqCompatibleLLM if model.startswith("groq/") else LLM
    kwargs: dict[str, object] = {
        "model": model,
        "api_key": api_key,
        "temperature": 0,
        "max_tokens": max_tokens,
        "timeout": 60,
        "max_retries": max_retries,
        "stream": False,
    }
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    if include_reasoning is not None:
        kwargs["include_reasoning"] = include_reasoning
    return llm_class(
        **kwargs,
    )


def create_agents(
    llm: LLM | None = None,
    research_tool: MCPReferenceSearchTool | None = None,
    analyst_llm: LLM | None = None,
    advisor_llm: LLM | None = None,
    vision_tool: VisionAnalysisTool | None = None,
) -> tuple[Agent, Agent, Agent]:
    researcher_llm = llm or create_llm()
    analyst_llm = analyst_llm or (
        llm
        or create_llm(
            model_env="GROQ_ANALYST_MODEL",
            max_tokens=1200,
            reasoning_effort="low",
            include_reasoning=False,
            max_retries=0,
        )
    )
    advisor_llm = advisor_llm or (
        llm
        or create_llm(
            model_env="GROQ_ADVISOR_MODEL",
            max_tokens=1200,
            reasoning_effort="low",
            include_reasoning=False,
            max_retries=0,
        )
    )
    research_tool = research_tool or MCPReferenceSearchTool()
    researcher = Agent(
        role="Investigador de mercado de amigurumis",
        goal="Obtener hasta tres referencias comerciales verificables y distinguir datos en directo de guardados.",
        backstory="Especialista prudente en investigación comercial que nunca inventa precios ni fuentes.",
        tools=[research_tool],
        llm=researcher_llm,
        allow_delegation=False,
        max_iter=2,
        max_retry_limit=1,
        verbose=False,
    )
    analyst = Agent(
        role="Analista de costes y precios",
        goal="Interpretar cálculos Python validados sin recalcular ni sustituir sus cifras.",
        backstory="Analista cuantitativo que distingue resultados oficiales de observaciones comerciales.",
        tools=[],
        llm=analyst_llm,
        allow_delegation=False,
        max_iter=1,
        max_retry_limit=0,
        verbose=False,
    )
    advisor = Agent(
        role="Asesor comercial de producto artesanal",
        goal="Evaluar comparabilidad y redactar una valoración estructurada sin inventar demanda ni ventas.",
        backstory="Asesor escéptico que explicita limitaciones y evita conclusiones cuando faltan datos.",
        tools=[vision_tool] if vision_tool else [],
        llm=advisor_llm,
        allow_delegation=False,
        max_iter=2 if vision_tool else 1,
        max_retry_limit=0,
        verbose=False,
    )
    return researcher, analyst, advisor


def create_crew(llm: LLM | None = None, output_log_file: str | None = None) -> Crew:
    researcher, analyst, advisor = create_agents(llm=llm)
    research_task = Task(
        description=(
            "Debes usar la herramienta MCP search_market_references exactamente una vez para buscar "
            "hasta tres referencias de {product_type}. Usa live=false para esta prueba controlada. "
            "Conserva URL, precio, moneda, fecha, procedencia y todos los metadatos descriptivos "
            "que estén disponibles, sin inventar campos."
        ),
        expected_output="JSON con referencias verificables y errores de fuente.",
        agent=researcher,
    )
    analysis_task = Task(
        description=(
            "Debes usar calculate_and_compare_prices exactamente una vez con {pricing_data} y las "
            "referencias obtenidas por el investigador. Para cada referencia pasa exclusivamente "
            "source_url, price, currency, checked_at y provenance. Compara solo referencias con la "
            "misma moneda y no presentes esa coincidencia monetaria como equivalencia comercial."
        ),
        expected_output="Cálculo y estadísticas numéricas reproducibles.",
        agent=analyst,
        context=[research_task],
    )
    advice_task = Task(
        description=(
            "Evalúa comparabilidad, posición y limitaciones usando únicamente los resultados "
            "anteriores. No recalcules ni sustituyas cifras de Python y evita repetir importes. "
            "No declares posicionamiento premium por superar una media pequeña, no relaciones "
            "margen con posicionamiento, no infieras ventas o demanda y no recomiendes mantener "
            "un precio actual no aportado. "
            "Devuelve solamente JSON válido, sin Markdown, con las claves comparability, "
            "market_position, recommendation y limitations."
        ),
        expected_output="Objeto JSON textual que cumpla el contrato CommercialAssessment.",
        agent=advisor,
        context=[research_task, analysis_task],
    )
    return Crew(
        agents=[researcher, analyst, advisor],
        tasks=[research_task, analysis_task, advice_task],
        process=Process.sequential,
        output_log_file=output_log_file,
        verbose=False,
    )


def calculate_statistics_for_agent(pricing_data: PricingInput, references: list[MarketReference]):
    """Punto explícito de unión entre la calculadora y el análisis del agente."""

    return calculate_market_statistics(calculate_price(pricing_data), references)
