"""Definición de exactamente tres agentes CrewAI para la Fase 2."""

from __future__ import annotations

import sys
from pathlib import Path

from crewai import Agent, Crew, Process, Task
from crewai.mcp import MCPServerStdio
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from amiguprecio.analysis import calculate_market_statistics, create_price_chart
from amiguprecio.models import PricingInput
from amiguprecio.pricing import calculate_price
from amiguprecio.references import MarketReference


class PricingToolInput(BaseModel):
    product_name: str
    product_type: str
    materials_cost: str
    hours_worked: str
    hourly_rate: str
    other_expenses: str = "0"
    margin_percent: str
    references: list[MarketReference] = Field(default_factory=list)
    pricing_currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    chart_path: str = "output/charts/market_comparison.png"


class PricingAnalysisTool(BaseTool):
    name: str = "calculate_and_compare_prices"
    description: str = (
        "Calcula costes con la fórmula validada y estadísticas sobre referencias válidas."
    )
    args_schema: type[BaseModel] = PricingToolInput

    def _run(self, **kwargs: object) -> dict:
        tool_input = PricingToolInput.model_validate(kwargs)
        pricing = calculate_price(
            PricingInput(
                product_name=tool_input.product_name,
                product_type=tool_input.product_type,
                materials_cost=tool_input.materials_cost,
                hours_worked=tool_input.hours_worked,
                hourly_rate=tool_input.hourly_rate,
                other_expenses=tool_input.other_expenses,
                margin_percent=tool_input.margin_percent,
            )
        )
        statistics = calculate_market_statistics(
            pricing, tool_input.references, tool_input.pricing_currency
        )
        chart = create_price_chart(
            pricing,
            tool_input.references,
            Path(tool_input.chart_path),
            tool_input.pricing_currency,
        )
        return {
            "pricing": pricing.model_dump(mode="json"),
            "statistics": statistics.model_dump(mode="json"),
            "chart_path": str(chart),
        }


class CommercialAssessment(BaseModel):
    comparability: str = Field(description="Alta, media, baja o insuficiente, con motivo")
    market_position: str
    recommendation: str
    limitations: list[str]


def create_agents() -> tuple[Agent, Agent, Agent]:
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
        allow_delegation=False,
        verbose=False,
    )
    analyst = Agent(
        role="Analista de costes y precios",
        goal="Calcular costes y estadísticas usando exclusivamente herramientas Python reproducibles.",
        backstory="Analista cuantitativo que separa precio rentable de precio observado en el mercado.",
        tools=[PricingAnalysisTool()],
        allow_delegation=False,
        verbose=False,
    )
    advisor = Agent(
        role="Asesor comercial de producto artesanal",
        goal="Evaluar comparabilidad y redactar una valoración estructurada sin inventar demanda ni ventas.",
        backstory="Asesor escéptico que explicita limitaciones y evita conclusiones cuando faltan datos.",
        tools=[],
        allow_delegation=False,
        verbose=False,
    )
    return researcher, analyst, advisor


def create_crew() -> Crew:
    researcher, analyst, advisor = create_agents()
    research_task = Task(
        description="Busca hasta tres referencias para {product_type}. Conserva URL, precio, moneda, fecha y procedencia.",
        expected_output="JSON con referencias verificables y errores de fuente.",
        agent=researcher,
    )
    analysis_task = Task(
        description="Calcula el precio con los datos {pricing_data} y compáralo solo con referencias válidas.",
        expected_output="Cálculo y estadísticas numéricas reproducibles.",
        agent=analyst,
        context=[research_task],
    )
    advice_task = Task(
        description="Evalúa comparabilidad, posición y limitaciones usando únicamente los resultados anteriores.",
        expected_output="Valoración comercial estructurada y prudente.",
        agent=advisor,
        context=[research_task, analysis_task],
        output_pydantic=CommercialAssessment,
    )
    return Crew(
        agents=[researcher, analyst, advisor],
        tasks=[research_task, analysis_task, advice_task],
        process=Process.sequential,
        verbose=False,
    )


def calculate_statistics_for_agent(pricing_data: PricingInput, references: list[MarketReference]):
    """Punto explícito de unión entre la calculadora y el análisis del agente."""

    return calculate_market_statistics(calculate_price(pricing_data), references)
