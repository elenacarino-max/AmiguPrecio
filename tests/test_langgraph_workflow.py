from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from langgraph.types import Command

from amiguprecio.agents import CommercialAssessment
from amiguprecio.langgraph_workflow import (
    AmiguPrecioGraphState,
    WorkflowServices,
    build_amiguprecio_graph,
    initial_graph_state,
)
from amiguprecio.models import PricingInput
from amiguprecio.references import MarketReference, ReferenceSearchResult
from amiguprecio.reporting import save_markdown_report
from amiguprecio.workflow import DeterministicAnalysis, run_deterministic_analysis


def _product() -> PricingInput:
    return PricingInput(
        product_name="Luna",
        product_type="muñeca amigurumi terminada",
        materials_cost="12.50",
        hours_worked="5",
        hourly_rate="10",
        other_expenses="2.50",
        margin_percent="20",
    )


def _references() -> ReferenceSearchResult:
    return ReferenceSearchResult(
        query="muñeca amigurumi terminada",
        references=[
            MarketReference(
                title="Muñeca artesanal USD",
                price="35.00",
                currency="USD",
                features=["producto terminado"],
                source_url="https://example.com/verified-doll",
                checked_at=datetime(2026, 10, 31, 16, 30, tzinfo=UTC),
                source_name="Tienda verificable",
                provenance="saved",
                category="muñeca",
                product_type="finished_product",
            )
        ],
        used_fallback=True,
    )


class FakeRuntime:
    """Sustituto determinista: no contiene IA, MCP ni red."""

    def __init__(
        self,
        *,
        analyst_outputs: list[str] | None = None,
        advisor_failures: int = 0,
        research_error: bool = False,
    ) -> None:
        self.analyst_outputs = analyst_outputs or [
            (
                "Python fija 65,00 EUR de coste, 81,25 EUR de precio y 20 % de margen. "
                "No hay comparación válida en EUR porque la referencia está en USD."
            )
        ]
        self.advisor_failures = advisor_failures
        self.research_error = research_error
        self.research_calls = 0
        self.calculation_calls = 0
        self.analyst_calls = 0
        self.advisor_calls = 0
        self.report_calls = 0

    def research(self, query: str) -> ReferenceSearchResult:
        self.research_calls += 1
        if self.research_error:
            raise RuntimeError("fallo MCP controlado")
        result = _references()
        assert query == result.query
        return result

    def calculate(
        self,
        product: PricingInput,
        references: list[MarketReference],
        chart_path: Path,
        pricing_currency: str,
    ) -> DeterministicAnalysis:
        self.calculation_calls += 1
        return run_deterministic_analysis(
            product,
            references,
            chart_path,
            pricing_currency,
        )

    def analyze(self, analysis: DeterministicAnalysis, pricing_currency: str) -> str:
        self.analyst_calls += 1
        assert analysis.pricing.calculated_price == 81.25
        assert pricing_currency == "EUR"
        index = min(self.analyst_calls - 1, len(self.analyst_outputs) - 1)
        return self.analyst_outputs[index]

    def advise(
        self,
        analysis: DeterministicAnalysis,
        observations: str,
        pricing_currency: str,
    ) -> CommercialAssessment:
        self.advisor_calls += 1
        if self.advisor_calls <= self.advisor_failures:
            raise ValueError("salida controlada inválida")
        assert analysis.pricing.production_cost == 65
        assert observations
        assert pricing_currency == "EUR"
        return CommercialAssessment(
            comparability="Insuficiente: las referencias están en USD",
            market_position="No determinable sin una muestra comparable en EUR",
            recommendation="Mantener el precio oficial calculado por Python",
            limitations=["No hay referencias comparables en EUR"],
        )

    def save_report(self, path: Path, content: str) -> Path:
        self.report_calls += 1
        return save_markdown_report(path, content)

    def services(self) -> WorkflowServices:
        return WorkflowServices(
            research=self.research,
            calculate=self.calculate,
            analyze=self.analyze,
            advise=self.advise,
            save_report=self.save_report,
        )


def _start(runtime: FakeRuntime, tmp_path: Path, thread_id: str):
    graph = build_amiguprecio_graph(runtime.services())
    state = initial_graph_state(
        _product(),
        "muñeca amigurumi terminada",
        tmp_path,
        report_path=tmp_path / "report.md",
    )
    config = {"configurable": {"thread_id": thread_id}}
    interrupted = graph.invoke(state, config)
    return graph, config, interrupted


def test_graph_interrupts_and_resumes_same_thread_without_repeating_work(tmp_path) -> None:
    runtime = FakeRuntime()
    graph, config, interrupted = _start(runtime, tmp_path, "approval-flow")

    assert interrupted["__interrupt__"]
    snapshot = graph.get_state(config)
    assert snapshot.next == ("approval",)
    assert snapshot.values["review_status"] == "approved"
    assert snapshot.values["references"]["references"][0]["source_name"] == (
        "Tienda verificable"
    )
    assert snapshot.values["deterministic_analysis"]["pricing"]["calculated_price"] == (
        "81.25"
    )
    counts_before_resume = (runtime.research_calls, runtime.calculation_calls)

    completed = graph.invoke(Command(resume={"approved": True}), config)

    assert completed["human_decision"] == "approved"
    assert completed["report_status"] == "saved"
    assert Path(completed["report_path"]).exists()
    assert runtime.report_calls == 1
    assert (runtime.research_calls, runtime.calculation_calls) == counts_before_resume == (1, 1)
    assert completed["research_attempts"] == 1
    assert completed["calculation_attempts"] == 1


def test_rejection_ends_without_saving_report(tmp_path) -> None:
    runtime = FakeRuntime()
    graph, config, interrupted = _start(runtime, tmp_path, "rejected-flow")

    assert interrupted["__interrupt__"]
    completed = graph.invoke(Command(resume={"approved": False}), config)

    assert completed["human_decision"] == "rejected"
    assert completed["report_status"] == "not_saved"
    assert completed["report_path"] is None
    assert runtime.report_calls == 0
    assert not (tmp_path / "report.md").exists()
    assert runtime.research_calls == runtime.calculation_calls == 1


def test_quality_retry_is_limited_and_does_not_repeat_mcp_or_python(tmp_path) -> None:
    runtime = FakeRuntime(
        analyst_outputs=[
            "",
            (
                "Python fija 65,00 EUR de coste, 81,25 EUR de precio y 20 % de margen. "
                "No hay comparación válida en EUR porque la referencia está en USD."
            ),
        ]
    )
    graph, config, interrupted = _start(runtime, tmp_path, "retry-flow")

    assert interrupted["__interrupt__"]
    snapshot = graph.get_state(config).values
    assert snapshot["retry_count"] == 1
    assert snapshot["review_status"] == "approved"
    assert snapshot["analyst_attempts"] == 2
    assert snapshot["advisor_attempts"] == 1
    assert runtime.research_calls == runtime.calculation_calls == 1


def test_second_invalid_analyst_output_finishes_as_explicit_error(tmp_path) -> None:
    runtime = FakeRuntime(analyst_outputs=[""])
    graph = build_amiguprecio_graph(runtime.services())
    state = initial_graph_state(_product(), _references().query, tmp_path)
    config = {"configurable": {"thread_id": "failed-retry"}}

    completed = graph.invoke(state, config)

    assert "__interrupt__" not in completed
    assert completed["review_status"] == "error"
    assert completed["report_status"] == "error"
    assert completed["retry_count"] == 1
    assert completed["analyst_attempts"] == 2
    assert completed["human_decision"] == "pending"
    assert runtime.research_calls == runtime.calculation_calls == 1
    assert runtime.report_calls == 0


def test_advisor_can_retry_once_without_repeating_prior_stages(tmp_path) -> None:
    runtime = FakeRuntime(advisor_failures=1)
    graph, config, interrupted = _start(runtime, tmp_path, "advisor-retry")

    assert interrupted["__interrupt__"]
    snapshot = graph.get_state(config).values
    assert snapshot["retry_count"] == 1
    assert snapshot["advisor_attempts"] == 2
    assert snapshot["analyst_attempts"] == 1
    assert runtime.research_calls == runtime.calculation_calls == 1


def test_unrecoverable_research_error_is_partial_and_never_interrupts(tmp_path) -> None:
    runtime = FakeRuntime(research_error=True)
    graph = build_amiguprecio_graph(runtime.services())
    state = initial_graph_state(_product(), _references().query, tmp_path)
    config = {"configurable": {"thread_id": "research-error"}}

    completed = graph.invoke(state, config)

    assert "__interrupt__" not in completed
    assert completed["review_status"] == "error"
    assert completed["report_status"] == "error"
    assert completed["references"] is None
    assert completed["deterministic_analysis"] is None
    assert runtime.research_calls == 1
    assert runtime.calculation_calls == runtime.report_calls == 0


def test_approved_report_preserves_official_values_sources_and_limitations(tmp_path) -> None:
    runtime = FakeRuntime()
    graph, config, _ = _start(runtime, tmp_path, "report-content")

    completed = graph.invoke(Command(resume=True), config)
    content = Path(completed["report_path"]).read_text(encoding="utf-8")

    assert "Coste de producción: 65.00 EUR" in content
    assert "Precio calculado: 81.25 EUR" in content
    assert "No existe una muestra válida comparable en EUR" in content
    assert "https://example.com/verified-doll" in content
    assert "Tienda verificable" in content
    assert "No hay referencias comparables en EUR" in content
    assert AmiguPrecioGraphState.__required_keys__ >= {
        "product",
        "references",
        "deterministic_analysis",
        "human_decision",
        "report_status",
    }
