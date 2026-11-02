"""Informe Markdown auditable generado solo tras aprobación humana."""

from __future__ import annotations

from pathlib import Path

from amiguprecio.agents import CommercialAssessment
from amiguprecio.models import PricingInput
from amiguprecio.references import ReferenceSearchResult
from amiguprecio.vision import VisualAnalysis
from amiguprecio.workflow import DeterministicAnalysis


def _table_text(value: object | None) -> str:
    if value is None:
        return "No disponible"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown_report(
    product: PricingInput,
    references: ReferenceSearchResult,
    analysis: DeterministicAnalysis,
    analyst_observations: str,
    assessment: CommercialAssessment,
    *,
    pricing_currency: str = "EUR",
    visual_analysis: VisualAnalysis | None = None,
    visual_error: str | None = None,
) -> str:
    """Renderiza el informe usando Python como única fuente monetaria oficial."""

    pricing = analysis.pricing
    lines = [
        f"# Informe de precio — {product.product_name}",
        "",
        "## Identificación",
        "",
        f"- Producto: {product.product_name}",
        f"- Tipo: {product.product_type}",
        "",
        "## Costes y precio oficial",
        "",
        "Los siguientes importes proceden del cálculo Python determinista:",
        "",
        f"- Mano de obra: {pricing.labor_cost:.2f} {pricing_currency}",
        f"- Coste de producción: {pricing.production_cost:.2f} {pricing_currency}",
        f"- Precio calculado: {pricing.calculated_price:.2f} {pricing_currency}",
        f"- Beneficio bruto: {pricing.gross_profit:.2f} {pricing_currency}",
        f"- Margen: {pricing.margin_percent:.2f} %",
        "",
        "## Referencias comerciales",
        "",
    ]
    if references.references:
        lines.extend(
            [
                "| Producto | Precio | Moneda | Tienda | Procedencia | Fuente |",
                "|---|---:|:---:|---|:---:|---|",
            ]
        )
        for reference in references.references:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _table_text(reference.title),
                        f"{reference.price:.2f}",
                        _table_text(reference.currency),
                        _table_text(reference.source_name),
                        _table_text(reference.provenance),
                        f"[enlace]({reference.source_url})",
                    ]
                )
                + " |"
            )
    else:
        lines.append("No se obtuvieron referencias comerciales verificadas.")

    lines.extend(["", "## Comparación", ""])
    if analysis.statistics.valid_reference_count == 0:
        lines.append(
            f"No existe una muestra válida comparable en {pricing_currency}; "
            "no se calcula ni se inventa una media de mercado."
        )
    else:
        lines.extend(
            [
                f"- Referencias comparables: {analysis.statistics.valid_reference_count}",
                f"- Media: {analysis.statistics.mean:.2f} {pricing_currency}",
                f"- Mediana: {analysis.statistics.median:.2f} {pricing_currency}",
            ]
        )

    lines.extend(["", "## Análisis visual", ""])
    if visual_analysis is not None:
        lines.extend(
            [
                f"- Tipo aparente: {visual_analysis.apparent_type}",
                f"- Colores predominantes: {', '.join(visual_analysis.predominant_colors)}",
                f"- Forma y detalles: {', '.join(visual_analysis.shape_and_details)}",
                f"- Rasgos comparables: {', '.join(visual_analysis.comparison_features)}",
                f"- Componente: {visual_analysis.component} ({visual_analysis.model})",
            ]
        )
        lines.extend(f"- Limitación visual: {item}" for item in visual_analysis.limitations)
    elif visual_error:
        lines.append(f"Análisis visual no completado: {visual_error}")
    else:
        lines.append("No se aportó una fotografía para análisis visual.")

    lines.extend(
        [
            "",
            "## Gráfico",
            "",
            f"![Comparación de precios]({analysis.chart_path})",
            "",
            "## Interpretación del analista",
            "",
            analyst_observations,
            "",
            "## Valoración comercial",
            "",
            f"- Comparabilidad: {assessment.comparability}",
            f"- Posición de mercado: {assessment.market_position}",
            f"- Recomendación: {assessment.recommendation}",
            "",
            "## Fuentes y limitaciones",
            "",
        ]
    )
    for limitation in assessment.limitations:
        lines.append(f"- {limitation}")
    for error in references.errors:
        lines.append(f"- Incidencia de fuente: {error}")
    lines.append(
        "- Las referencias guardadas no constituyen una búsqueda web en directo."
        if references.used_fallback
        else "- Las referencias proceden de la consulta indicada en su campo de procedencia."
    )
    return "\n".join(lines) + "\n"


def save_markdown_report(path: Path, content: str) -> Path:
    """Guarda una sola vez el informe previamente aprobado."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
