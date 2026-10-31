"""Tres agentes CrewAI configurables para ejecución real y limitada."""

from __future__ import annotations

import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from crewai import LLM, Agent, Crew, Process, Task
from crewai.llms.cache import CACHE_BREAKPOINT_KEY
from crewai.mcp import MCPServerStdio
from crewai.tools import BaseTool
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from amiguprecio.analysis import calculate_market_statistics, create_price_chart
from amiguprecio.models import PricingInput
from amiguprecio.pricing import calculate_price
from amiguprecio.references import MarketReference


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
        "Calcula costes con la fórmula validada y estadísticas sobre referencias válidas."
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


class CommercialAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparability: str = Field(description="Alta, media, baja o insuficiente, con motivo")
    market_position: str
    recommendation: str
    limitations: list[str]


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

    allowed = _collect_authoritative_decimals(python_trace)
    narrative = " ".join(
        [
            assessment.comparability,
            assessment.market_position,
            assessment.recommendation,
            *assessment.limitations,
        ]
    )
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


def create_llm() -> LLM:
    """Construye el LLM sin registrar credenciales y con un presupuesto acotado."""

    load_dotenv()
    model = os.getenv("GROQ_MODEL", "groq/openai/gpt-oss-20b")
    api_key = os.getenv("GROQ_API_KEY")
    if model.startswith("groq/") and not api_key:
        raise RuntimeError("Falta GROQ_API_KEY para ejecutar CrewAI con Groq")
    llm_class = GroqCompatibleLLM if model.startswith("groq/") else LLM
    return llm_class(
        model=model,
        api_key=api_key,
        temperature=0,
        max_tokens=600,
        timeout=60,
        max_retries=1,
    )


def create_agents(llm: LLM | None = None) -> tuple[Agent, Agent, Agent]:
    llm = llm or create_llm()
    project_root = Path(__file__).parents[2]
    mcp_config = MCPServerStdio(
        command=sys.executable,
        args=["-m", "amiguprecio.mcp_server"],
        env={"PYTHONPATH": str(project_root / "src")},
        cache_tools_list=True,
    )
    researcher = Agent(
        role="Investigador de mercado de amigurumis",
        goal="Obtener hasta tres referencias comerciales verificables y distinguir datos en directo de guardados.",
        backstory="Especialista prudente en investigación comercial que nunca inventa precios ni fuentes.",
        mcps=[mcp_config],
        llm=llm,
        allow_delegation=False,
        max_iter=2,
        max_retry_limit=1,
        verbose=False,
    )
    analyst = Agent(
        role="Analista de costes y precios",
        goal="Calcular costes y estadísticas usando exclusivamente herramientas Python reproducibles.",
        backstory="Analista cuantitativo que separa precio rentable de precio observado en el mercado.",
        tools=[PricingAnalysisTool()],
        llm=llm,
        allow_delegation=False,
        max_iter=1,
        max_retry_limit=1,
        verbose=False,
    )
    advisor = Agent(
        role="Asesor comercial de producto artesanal",
        goal="Evaluar comparabilidad y redactar una valoración estructurada sin inventar demanda ni ventas.",
        backstory="Asesor escéptico que explicita limitaciones y evita conclusiones cuando faltan datos.",
        tools=[],
        llm=llm,
        allow_delegation=False,
        max_iter=1,
        max_retry_limit=1,
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
            "misma moneda."
        ),
        expected_output="Cálculo y estadísticas numéricas reproducibles.",
        agent=analyst,
        context=[research_task],
    )
    advice_task = Task(
        description=(
            "Evalúa comparabilidad, posición y limitaciones usando únicamente los resultados "
            "anteriores. No recalcules ni sustituyas cifras de Python y evita repetir importes. "
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
