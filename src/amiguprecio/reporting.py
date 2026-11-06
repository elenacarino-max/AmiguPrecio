"""Informe Markdown auditable generado solo tras aprobación humana."""

from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as ReportLabImage,
)
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from amiguprecio.agents import CommercialAssessment
from amiguprecio.models import PricingInput
from amiguprecio.references import ReferenceSearchResult
from amiguprecio.vision import VisualAnalysis
from amiguprecio.workflow import DeterministicAnalysis


def _table_text(value: object | None) -> str:
    if value is None:
        return "No disponible"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _source_label(provenance: str) -> str:
    return {
        "serpapi_google_shopping": "Google Shopping vía SerpApi (agregador)",
        "live": "Catálogo directo SweetLavenderCo",
        "saved": "Catálogo local guardado",
    }.get(provenance, provenance)


def _comparison_label(status: str | None) -> str:
    return {
        "comparable": "Comparable",
        "not_comparable": "No comparable",
        "undetermined": "No determinable",
    }.get(status, "No evaluada")


def collect_presented_limitations(
    *groups: list[str], product: PricingInput | None = None
) -> list[str]:
    """Resume por significado sin modificar las limitaciones originales."""

    cleaned_values: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            cleaned = " ".join(value.split()).strip()
            key = cleaned.casefold().rstrip(".")
            if cleaned and key not in seen:
                seen.add(key)
                cleaned_values.append(cleaned)

    categories = {
        "comparison": False,
        "advertised": False,
        "visual": False,
        "manufacturing": False,
    }
    remaining: list[str] = []
    for value in cleaned_values:
        normalized = value.casefold()
        if any(
            term in normalized
            for term in (
                "fotograf",
                "imagen",
                "visual",
                "material",
                "composición",
                "calidad",
                "seguridad",
                "tamaño exacto",
                "altura exacta",
            )
        ):
            categories["visual"] = True
        elif any(
            term in normalized
            for term in ("tiempo de elabor", "horas", "coste de producción", "fabricación")
        ):
            categories["manufacturing"] = True
        elif "precio" in normalized and any(
            term in normalized for term in ("anunci", "ventas", "demanda", "transacción")
        ):
            categories["advertised"] = True
        elif any(
            term in normalized
            for term in ("comparab", "muestra", "referenc", "moneda", "tipo o altura")
        ):
            categories["comparison"] = True
        else:
            remaining.append(value)

    result: list[str] = []
    if categories["comparison"]:
        result.append(
            "Comparabilidad y muestra: compartir moneda no demuestra equivalencia; "
            "una muestra pequeña o heterogénea limita las conclusiones por tipo, "
            "altura y características."
        )
    if categories["advertised"]:
        result.append(
            "Precios anunciados: no prueban ventas, demanda ni el precio final de una transacción."
        )
    if categories["visual"]:
        height_note = (
            " La altura indicada procede del formulario, no de la imagen."
            if product is not None and product.height_cm is not None
            else " La fotografía tampoco permite confirmar una altura o medidas exactas."
        )
        result.append(
            "Análisis visual: la fotografía muestra rasgos visibles, pero no confirma "
            f"composición, calidad ni seguridad del producto.{height_note}"
        )
    if categories["manufacturing"]:
        result.append(
            "Información de fabricación: las horas y los costes utilizados proceden del "
            "formulario; el proceso y las condiciones de elaboración debe aportarlos la artesana."
        )
    if remaining:
        result.append("Otras advertencias: " + "; ".join(remaining))
    return result


def can_download_approved_report(values: dict[str, object]) -> bool:
    """La descarga solo existe tras aprobación humana y guardado confirmado."""

    return values.get("human_decision") == "approved" and values.get("report_status") == "saved"


def render_markdown_report(
    product: PricingInput,
    references: ReferenceSearchResult,
    analysis: DeterministicAnalysis,
    analyst_observations: str,
    assessment: CommercialAssessment | None,
    *,
    pricing_currency: str = "EUR",
    visual_analysis: VisualAnalysis | None = None,
    visual_error: str | None = None,
    partial_report: bool = False,
) -> str:
    """Renderiza el informe usando Python como única fuente monetaria oficial."""

    pricing = analysis.pricing
    comparison = analysis.commercial_comparability
    comparison_statuses = {item.title: item.status for item in comparison.references}
    lines = [
        (
            f"# Informe técnico parcial de precio — {product.product_name}"
            if partial_report
            else f"# Informe de precio — {product.product_name}"
        ),
        "",
        *(
            [
                (
                    "**Informe parcial aprobado:** la valoración del asesor comercial no está "
                    "disponible. Los resultados deterministas y las fuentes se conservan."
                ),
                "",
            ]
            if partial_report
            else []
        ),
        "## Identificación",
        "",
        f"- Producto: {product.product_name}",
        f"- Tipo: {product.product_type}",
        f"- Altura: {product.height_cm:.2f} cm"
        if product.height_cm is not None
        else "- Altura: no indicada",
        "",
        "## Costes y precio oficial",
        "",
        "Los siguientes importes proceden del cálculo Python determinista:",
        "",
        f"- Materiales: {product.materials_cost:.2f} {pricing_currency}",
        f"- Horas de trabajo: {product.hours_worked:.2f}",
        f"- Tarifa por hora: {product.hourly_rate:.2f} {pricing_currency}",
        f"- Otros gastos: {product.other_expenses:.2f} {pricing_currency}",
        f"- Mano de obra: {pricing.labor_cost:.2f} {pricing_currency}",
        f"- Coste de producción: {pricing.production_cost:.2f} {pricing_currency}",
        f"- Precio calculado: {pricing.calculated_price:.2f} {pricing_currency}",
        f"- Beneficio bruto: {pricing.gross_profit:.2f} {pricing_currency}",
        f"- Margen: {pricing.margin_percent:.2f} %",
        "",
        "## Referencias comerciales online y guardadas",
        "",
    ]
    if references.references:
        lines.extend(
            [
                "| Producto | Precio | Moneda | Tienda | Procedencia | Comparabilidad | Consulta | Fuente |",
                "|---|---:|:---:|---|---|---|:---:|---|",
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
                        _table_text(_source_label(reference.provenance)),
                        _table_text(
                            _comparison_label(
                                comparison_statuses.get(
                                    reference.title, reference.comparability_status
                                )
                            )
                        ),
                        reference.checked_at.date().isoformat(),
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
            f"No existe una muestra de referencias en {pricing_currency}; "
            "no se calcula ni se inventa una media de mercado."
        )
    else:
        lines.extend(
            [
                (
                    f"- Referencias en la muestra {pricing_currency}: "
                    f"{analysis.statistics.valid_reference_count}"
                ),
                f"- Media de la muestra: {analysis.statistics.mean:.2f} {pricing_currency}",
                f"- Mediana de la muestra: {analysis.statistics.median:.2f} {pricing_currency}",
            ]
        )
    lines.extend(
        [
            f"- Comparables directamente: {comparison.directly_comparable_count}",
            f"- No comparables: {comparison.not_comparable_count}",
            f"- Comparabilidad no determinable: {comparison.undetermined_count}",
            f"- Conclusión: {comparison.conclusion}",
        ]
    )
    if comparison.comparable_mean is not None:
        lines.append(
            "- Media de productos directamente comparables: "
            f"{comparison.comparable_mean:.2f} {pricing_currency}"
        )
    else:
        lines.append(
            "- No existe una media de productos equivalentes; los precios de los candidatos "
            "son únicamente orientativos."
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
        ]
    )
    if assessment is not None:
        lines.extend(
            [
                f"- Comparabilidad: {assessment.comparability}",
                f"- Posición de mercado: {assessment.market_position}",
                f"- Recomendación: {assessment.recommendation}",
            ]
        )
    else:
        lines.append("**Valoración del asesor comercial no disponible**.")
    lines.extend(["", "## Limitaciones y alcance", ""])
    presented_limitations = collect_presented_limitations(
        comparison.limitations,
        assessment.limitations if assessment is not None else [],
        visual_analysis.limitations if visual_analysis is not None else [],
        product=product,
    )
    for limitation in presented_limitations:
        lines.append(f"- {limitation}")
    lines.extend(["", "## Procedencia e incidencias de fuentes", ""])
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


def _pdf_paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)


def _pdf_money(value: object, currency: str) -> str:
    suffix = "€" if currency == "EUR" else currency
    return f"{value:.2f} {suffix}"


def render_pdf_report(
    product: PricingInput,
    references: ReferenceSearchResult,
    analysis: DeterministicAnalysis,
    analyst_observations: str,
    assessment: CommercialAssessment | None,
    *,
    pricing_currency: str = "EUR",
    visual_analysis: VisualAnalysis | None = None,
    visual_error: str | None = None,
    partial_report: bool = False,
) -> bytes:
    """Genera un PDF A4 en memoria desde resultados oficiales ya aprobados."""

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.7 * cm,
        leftMargin=1.7 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.7 * cm,
        title=(
            f"AmiguPrecio - Informe técnico parcial - {product.product_name}"
            if partial_report
            else f"AmiguPrecio - {product.product_name}"
        ),
        author="AmiguPrecio",
    )
    palette = {
        "cream": colors.HexColor("#FBF6EC"),
        "paper": colors.HexColor("#FFFDF8"),
        "green": colors.HexColor("#1F6F5F"),
        "green_soft": colors.HexColor("#E5EEE8"),
        "ink": colors.HexColor("#292724"),
        "line": colors.HexColor("#D8CDBD"),
    }
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "AmiguPrecioBody",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=9.2,
        leading=13,
        textColor=palette["ink"],
        spaceAfter=5,
    )
    heading = ParagraphStyle(
        "AmiguPrecioHeading",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=palette["green"],
        spaceBefore=12,
        spaceAfter=7,
    )
    title = ParagraphStyle(
        "AmiguPrecioTitle",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        alignment=TA_CENTER,
        textColor=palette["green"],
        spaceAfter=4,
    )
    subtitle = ParagraphStyle(
        "AmiguPrecioSubtitle",
        parent=body,
        alignment=TA_CENTER,
        fontSize=11,
        leading=14,
        spaceAfter=14,
    )
    small = ParagraphStyle("AmiguPrecioSmall", parent=body, fontSize=7.6, leading=10)

    story: list[object] = [
        Paragraph("AmiguPrecio", title),
        _pdf_paragraph(product.product_name, subtitle),
    ]
    if partial_report:
        story.extend(
            [
                Paragraph("Informe técnico parcial", heading),
                Paragraph(
                    "Valoración del asesor comercial no disponible. Este informe conserva "
                    "únicamente resultados deterministas y fuentes verificadas, aprobados "
                    "expresamente por la persona usuaria.",
                    body,
                ),
            ]
        )
    story.append(Paragraph("Datos del producto", heading))
    height = f"{product.height_cm:.2f} cm" if product.height_cm is not None else "No indicada"
    product_rows = [
        ["Producto", product.product_name, "Tipo", product.product_type],
        ["Altura", height, "Margen sobre ventas", f"{analysis.pricing.margin_percent:.2f} %"],
        [
            "Materiales",
            _pdf_money(product.materials_cost, pricing_currency),
            "Horas",
            f"{product.hours_worked:.2f}",
        ],
        [
            "Tarifa por hora",
            _pdf_money(product.hourly_rate, pricing_currency),
            "Otros gastos",
            _pdf_money(product.other_expenses, pricing_currency),
        ],
    ]
    product_table = Table(product_rows, colWidths=[3.2 * cm, 5.1 * cm, 3.6 * cm, 4.5 * cm])
    product_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), palette["paper"]),
                ("TEXTCOLOR", (0, 0), (-1, -1), palette["ink"]),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.35, palette["line"]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([product_table, Paragraph("Costes y precio oficial", heading)])
    pricing_rows = [
        ["Mano de obra", "Coste de producción", "Precio calculado", "Beneficio bruto"],
        [
            _pdf_money(analysis.pricing.labor_cost, pricing_currency),
            _pdf_money(analysis.pricing.production_cost, pricing_currency),
            _pdf_money(analysis.pricing.calculated_price, pricing_currency),
            _pdf_money(analysis.pricing.gross_profit, pricing_currency),
        ],
    ]
    pricing_table = Table(pricing_rows, colWidths=[4.1 * cm] * 4)
    pricing_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), palette["green"]),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, 1), palette["green_soft"]),
                ("TEXTCOLOR", (0, 1), (-1, 1), palette["ink"]),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.3),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.4, palette["line"]),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    comparison = analysis.commercial_comparability
    comparison_statuses = {item.title: item.status for item in comparison.references}
    story.extend(
        [pricing_table, Paragraph("Referencias comerciales online y guardadas", heading)]
    )
    if references.references:
        reference_rows: list[list[object]] = [
            ["Producto", "Precio", "Fuente", "Consulta", "Origen", "Comparabilidad"]
        ]
        for reference in references.references:
            source_url = escape(str(reference.source_url), quote=True)
            source = Paragraph(
                f'{escape(reference.source_name)}<br/><link href="{source_url}">Abrir fuente</link>',
                small,
            )
            reference_rows.append(
                [
                    _pdf_paragraph(reference.title, small),
                    _pdf_money(reference.price, reference.currency),
                    source,
                    reference.checked_at.date().isoformat(),
                    _source_label(reference.provenance),
                    _comparison_label(
                        comparison_statuses.get(
                            reference.title, reference.comparability_status
                        )
                    ),
                ]
            )
        reference_table = Table(
            reference_rows,
            colWidths=[4.3 * cm, 1.8 * cm, 3.2 * cm, 1.9 * cm, 2.8 * cm, 2.4 * cm],
            repeatRows=1,
        )
        reference_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), palette["green"]),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("GRID", (0, 0), (-1, -1), 0.35, palette["line"]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [palette["paper"], colors.white]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(reference_table)
    else:
        story.append(Paragraph("No se obtuvieron referencias verificadas.", body))

    story.append(Paragraph("Estadísticas de la muestra EUR", heading))
    statistics = analysis.statistics
    if statistics.valid_reference_count:
        story.append(
            Paragraph(
                f"Muestra EUR: {statistics.valid_reference_count} referencias. "
                f"Media: {_pdf_money(statistics.mean, pricing_currency)}. "
                f"Mediana: {_pdf_money(statistics.median, pricing_currency)}. "
                "Estas estadísticas agrupan moneda; no prueban equivalencia comercial.",
                body,
            )
        )
    else:
        story.append(
            Paragraph(
                "No existe una muestra EUR válida; no se calcula ni se inventa una media.",
                body,
            )
        )
    story.append(_pdf_paragraph(comparison.conclusion, body))
    if comparison.comparable_mean is not None:
        story.append(
            _pdf_paragraph(
                "Media de productos directamente comparables: "
                + _pdf_money(comparison.comparable_mean, pricing_currency),
                body,
            )
        )
    else:
        story.append(
            Paragraph(
                "No existe una media de productos equivalentes; los precios encontrados "
                "son información orientativa.",
                body,
            )
        )
    chart_path = Path(analysis.chart_path)
    if chart_path.is_file():
        chart = ReportLabImage(str(chart_path), width=15.8 * cm, height=8.9 * cm)
        chart.hAlign = "CENTER"
        story.extend([Spacer(1, 5), chart])
    else:
        story.append(Paragraph("El gráfico comparativo no está disponible.", body))

    story.append(Paragraph("Análisis visual", heading))
    if visual_analysis is not None:
        story.extend(
            [
                _pdf_paragraph(f"Tipo aparente: {visual_analysis.apparent_type}", body),
                _pdf_paragraph(
                    "Colores visibles: " + ", ".join(visual_analysis.predominant_colors), body
                ),
                _pdf_paragraph(
                    "Forma y detalles: " + ", ".join(visual_analysis.shape_and_details), body
                ),
                _pdf_paragraph(
                    "Rasgos comparables: " + ", ".join(visual_analysis.comparison_features),
                    body,
                ),
                _pdf_paragraph(
                    f"Componente: {visual_analysis.component} ({visual_analysis.model})",
                    body,
                ),
            ]
        )
    elif visual_error:
        story.append(_pdf_paragraph(f"Análisis visual no completado: {visual_error}", body))
    else:
        story.append(Paragraph("No se aportó una fotografía para análisis visual.", body))

    story.extend(
        [
            Paragraph("Interpretación del analista", heading),
            _pdf_paragraph(analyst_observations, body),
            Paragraph(
                "Valoración comercial validada"
                if assessment is not None
                else "Valoración comercial",
                heading,
            ),
        ]
    )
    if assessment is not None:
        story.extend(
            [
                _pdf_paragraph(f"Comparabilidad: {assessment.comparability}", body),
                _pdf_paragraph(f"Posición de mercado: {assessment.market_position}", body),
                _pdf_paragraph(f"Recomendación: {assessment.recommendation}", body),
            ]
        )
    else:
        story.append(
            Paragraph("Valoración del asesor comercial no disponible.", body)
        )
    story.append(Paragraph("Limitaciones y alcance", heading))
    limitations = collect_presented_limitations(
        comparison.limitations,
        assessment.limitations if assessment is not None else [],
        visual_analysis.limitations if visual_analysis is not None else [],
        product=product,
    )
    for limitation in limitations:
        story.append(_pdf_paragraph(f"- {limitation}", body))
    story.extend(
        [
            Paragraph("Procedencia de las fuentes", heading),
            Paragraph(
                "Las referencias guardadas son una fuente local de respaldo, no una búsqueda "
                "web en directo. Cada referencia conserva tienda, URL, fecha de consulta y origen."
                if references.used_fallback
                else "Cada referencia conserva tienda, URL, fecha de consulta y procedencia.",
                body,
            ),
        ]
    )

    def decorate_page(canvas: object, doc: object) -> None:
        page_width, page_height = A4
        canvas.saveState()
        canvas.setFillColor(palette["cream"])
        canvas.rect(0, 0, page_width, page_height, fill=1, stroke=0)
        canvas.setStrokeColor(palette["green"])
        canvas.setLineWidth(0.8)
        canvas.line(
            1.7 * cm, page_height - 1.25 * cm, page_width - 1.7 * cm, page_height - 1.25 * cm
        )
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(palette["green"])
        footer_label = (
            "AmiguPrecio · informe técnico parcial aprobado"
            if partial_report
            else "AmiguPrecio · informe aprobado"
        )
        canvas.drawString(1.7 * cm, 0.9 * cm, footer_label)
        canvas.drawRightString(page_width - 1.7 * cm, 0.9 * cm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=decorate_page, onLaterPages=decorate_page)
    return buffer.getvalue()
