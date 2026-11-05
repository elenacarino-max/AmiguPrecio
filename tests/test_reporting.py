from io import BytesIO

from pdfminer.high_level import extract_text

from amiguprecio.agents import CommercialAssessment
from amiguprecio.models import PricingInput
from amiguprecio.references import ReferenceSearchResult, load_saved_references
from amiguprecio.reporting import (
    can_download_approved_report,
    render_markdown_report,
    render_pdf_report,
)
from amiguprecio.vision import VisualAnalysis
from amiguprecio.workflow import run_deterministic_analysis


def _approved_report_data(tmp_path):
    product = PricingInput(
        product_name="Muñeca Ñandú",
        product_type="muñeca amigurumi",
        height_cm="30.5",
        materials_cost="10",
        hours_worked="1.5",
        hourly_rate="20",
        other_expenses="0",
        margin_percent="20",
    )
    references = ReferenceSearchResult(
        query=product.product_type,
        references=load_saved_references(product.product_type, currency="EUR"),
        used_fallback=True,
    )
    analysis = run_deterministic_analysis(
        product,
        references.references,
        chart_path=tmp_path / "comparación-precios.png",
    )
    assessment = CommercialAssessment(
        comparability="Insuficiente: la muestra EUR es heterogénea.",
        market_position="No es posible determinar el posicionamiento.",
        recommendation="Reunir referencias más equivalentes.",
        limitations=[
            "Los precios anunciados no prueban ventas ni demanda.",
            "El margen objetivo no determina el posicionamiento de mercado.",
        ],
    )
    visual = VisualAnalysis(
        apparent_type="muñeca tejida",
        predominant_colors=["crema", "verde"],
        shape_and_details=["cuerpo redondeado"],
        comparison_features=["acabado artesanal"],
        limitations=[
            "La fotografía no permite determinar el material exacto.",
            "seguridad del producto no verificada",
        ],
        model="qwen/qwen3.8-27b",
    )
    return product, references, analysis, assessment, visual


def test_markdown_and_pdf_use_official_values_sources_chart_and_unicode(tmp_path) -> None:
    product, references, analysis, assessment, visual = _approved_report_data(tmp_path)

    markdown = render_markdown_report(
        product,
        references,
        analysis,
        "Interpretación prudente basada en Python.",
        assessment,
        visual_analysis=visual,
    )
    pdf = render_pdf_report(
        product,
        references,
        analysis,
        "Interpretación prudente basada en Python.",
        assessment,
        visual_analysis=visual,
    )
    extracted = extract_text(BytesIO(pdf))

    assert "Altura: 30.50 cm" in markdown
    assert "Precio calculado: 50.00 EUR" in markdown
    assert "Maxland" in markdown
    assert pdf.startswith(b"%PDF-") and len(pdf) > 10_000
    assert b"/Subtype /Image" in pdf
    assert "Muñeca Ñandú" in extracted
    assert "30.50 cm" in extracted
    assert "50.00 €" in extracted
    assert "Maxland" in extracted
    assert "Limitaciones y alcance" in extracted
    assert "€" in extracted


def test_download_requires_saved_report_and_real_human_approval() -> None:
    assert can_download_approved_report({"report_status": "saved", "human_decision": "approved"})
    assert not can_download_approved_report(
        {"report_status": "pending", "human_decision": "approved"}
    )
    assert not can_download_approved_report({"report_status": "saved", "human_decision": "pending"})
    assert not can_download_approved_report(
        {"report_status": "not_saved", "human_decision": "rejected"}
    )
