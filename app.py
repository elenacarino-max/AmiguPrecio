"""Interfaz completa de AmiguPrecio sobre el flujo LangGraph real."""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from amiguprecio.app_runtime import WorkflowExecution
from amiguprecio.models import PricingInput
from amiguprecio.reporting import collect_presented_limitations
from amiguprecio.vision import ImageValidationError, prepare_uploaded_image

OUTPUT_ROOT = Path("output/streamlit")
STAGE_LABELS = {
    "research": "Referencias verificadas mediante MCP",
    "calculation": "Cálculo Python y gráfico completados",
    "analyst": "Interpretación del analista completada",
    "advisor": "Valoración comercial y visión procesadas",
    "review": "Coherencia y trazabilidad validadas",
    "approval": "Esperando tu decisión",
    "report": "Informe aprobado y guardado",
}

st.set_page_config(page_title="AmiguPrecio", layout="wide")
st.markdown(
    """
    <style>
    :root {
        --canvas: #fbf6ec; --paper: #fffdf8; --ink: #292724;
        --muted: #655f57; --line: #ddd2c1; --green: #315b48;
        --green-soft: #e5eee8; --coral: #b9503e; --coral-dark: #963e31;
        --coral-soft: #f7e3dd;
    }
    .stApp { background: var(--canvas); color: var(--ink); }
    .block-container { max-width: 1120px; padding: 2.5rem 2rem 5rem; }
    h1, h2, h3 { color: var(--green); letter-spacing: -.025em; }
    p, label, [data-testid="stCaptionContainer"] { color: var(--muted); }
    .brand-line { color: var(--green); font-size: .74rem; font-weight: 750;
        letter-spacing: .13em; border-bottom: 1px dashed var(--line);
        padding-bottom: .85rem; margin-bottom: 1.4rem; }
    .intro { max-width: 720px; font-size: 1.05rem; line-height: 1.6; }
    [data-testid="stForm"] { background: var(--paper); border: 1px solid var(--line);
        border-radius: .55rem; padding: 1.35rem; }
    div.stButton > button[kind="primary"], div.stFormSubmitButton > button {
        background: #1f6f5f; color: #ffffff; border: none;
        border-radius: .38rem; font-weight: 750; }
    div.stButton > button[kind="primary"]:hover, div.stFormSubmitButton > button:hover {
        background: #174f45; color: #ffffff; border: none; }
    div.stButton > button:disabled, div.stFormSubmitButton > button:disabled {
        background: #d9dfdc; color: #4b514e; border: none; opacity: 1; }
    button:focus-visible, input:focus-visible, textarea:focus-visible {
        outline: 3px solid var(--coral-soft) !important; outline-offset: 2px; }
    [data-testid="stMetric"] { border-top: 2px solid var(--green);
        border-bottom: 1px solid var(--line); padding: .8rem .15rem 1rem;
        background: transparent; }
    .status-ok { background: var(--green-soft); border-left: 4px solid var(--green);
        padding: .8rem 1rem; margin: 1rem 0; }
    .privacy-note { border-left: 3px solid var(--coral); padding-left: .8rem;
        color: var(--muted); font-size: .88rem; }
    @media (max-width: 700px) {
        .block-container { padding: 3.5rem 1rem 3rem; }
        h1 { font-size: 2rem !important; }
        .brand-line { font-size: .67rem; line-height: 1.45; }
    }
    div.stFormSubmitButton button p,
    div.stButton button[kind="primary"] p {
        color: inherit !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _render_results(execution: WorkflowExecution) -> None:
    values = execution.values
    analysis = values.get("deterministic_analysis")
    if not analysis:
        if values.get("errors"):
            st.error("No se pudo completar el flujo: " + "; ".join(values["errors"]))
        return

    pricing = analysis["pricing"]
    statistics = analysis["statistics"]
    comparison = analysis["commercial_comparability"]
    st.header("Resultado verificable")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Mano de obra", f"{float(pricing['labor_cost']):.2f} €")
    metric_cols[1].metric("Coste de producción", f"{float(pricing['production_cost']):.2f} €")
    metric_cols[2].metric("Precio calculado", f"{float(pricing['calculated_price']):.2f} €")
    metric_cols[3].metric("Margen", f"{float(pricing['margin_percent']):.2f} %")

    left, right = st.columns([1.05, .95], gap="large")
    with left:
        st.subheader("Comparación comercial")
        if statistics["valid_reference_count"]:
            st.write(
                f"{statistics['valid_reference_count']} referencias en la muestra EUR. "
                f"Media de la muestra: **{float(statistics['mean']):.2f} €** · "
                f"Mediana: **{float(statistics['median']):.2f} €**"
            )
        else:
            st.warning("No existe una muestra de referencias en EUR.")
        st.write(
            f"Comparables directamente: **{comparison['directly_comparable_count']}** · "
            f"No comparables: **{comparison['not_comparable_count']}** · "
            f"No determinables: **{comparison['undetermined_count']}**"
        )
        if comparison["sample_is_heterogeneous"]:
            st.warning(comparison["conclusion"])
        else:
            st.info(comparison["conclusion"])
        chart_path = values.get("chart_path")
        if chart_path and Path(chart_path).exists():
            st.image(chart_path, caption="Precio Python frente a la muestra EUR")
    with right:
        st.subheader("Referencias y procedencia")
        reference_result = values.get("references") or {}
        comparison_by_title = {
            item["title"]: item for item in comparison.get("references", [])
        }
        for reference in reference_result.get("references", []):
            checked = str(reference["checked_at"]).split("T")[0]
            st.markdown(
                f"**{reference['title']}**  \n"
                f"{float(reference['price']):.2f} {reference['currency']} · "
                f"{reference['source_name']} · {reference['provenance']} · {checked}  \n"
                f"[Abrir fuente]({reference['source_url']})"
            )
            reference_comparison = comparison_by_title.get(reference["title"])
            if reference_comparison:
                status_label = {
                    "comparable": "Comparable directamente",
                    "not_comparable": "No comparable",
                    "undetermined": "Comparabilidad no determinable",
                }[reference_comparison["status"]]
                st.write(
                    f"**{status_label}:** {reference_comparison['reason']}"
                )
        if reference_result.get("used_fallback"):
            st.caption("Dataset local de respaldo; no es una búsqueda web en directo.")

    st.subheader("Lectura de los agentes")
    st.write(values.get("analyst_observations") or "Interpretación no disponible.")
    assessment = values.get("commercial_assessment")
    if assessment:
        st.markdown(f"**Comparabilidad:** {assessment['comparability']}")
        st.markdown(f"**Posición:** {assessment['market_position']}")
        st.markdown(f"**Recomendación:** {assessment['recommendation']}")

    st.subheader("Observación visual")
    visual = values.get("visual_analysis")
    if visual:
        st.write(f"**Tipo aparente:** {visual['apparent_type']}")
        st.write("**Colores visibles:** " + ", ".join(visual["predominant_colors"]))
        st.write("**Forma y detalles:** " + ", ".join(visual["shape_and_details"]))
        st.caption(f"{visual['component']} · {visual['model']}")
    elif values.get("visual_status") == "failed":
        st.warning("El análisis visual no se completó; el resto del resultado sigue siendo válido.")
    else:
        st.caption("No se aportó fotografía.")

    limitations = collect_presented_limitations(
        comparison.get("limitations", []),
        assessment.get("limitations", []) if assessment else [],
        visual.get("limitations", []) if visual else [],
    )
    if limitations:
        with st.expander(f"Limitaciones y alcance ({len(limitations)})"):
            for limitation in limitations:
                st.markdown(f"- {limitation}")

    if values.get("errors"):
        with st.expander("Incidencias técnicas"):
            for error in values["errors"]:
                st.write(error)

    if execution.waiting_for_approval:
        st.markdown(
            '<div class="status-ok"><strong>Revisión automática superada.</strong> '
            "Decide si deseas guardar el informe.</div>",
            unsafe_allow_html=True,
        )
        approve_col, reject_col = st.columns(2)
        if approve_col.button("Aprobar y generar informe", type="primary", use_container_width=True):
            execution.resume(True)
            st.rerun()
        if reject_col.button("Rechazar informe", use_container_width=True):
            execution.resume(False)
            st.rerun()

    values = execution.values
    if values.get("report_status") == "saved":
        st.success("Informe aprobado y guardado. El flujo no se ha vuelto a ejecutar.")
        report_path = Path(values["report_path"])
        chart_path = Path(values["chart_path"])
        download_cols = st.columns(2)
        download_cols[0].download_button(
            "Descargar informe Markdown", report_path.read_bytes(),
            file_name=report_path.name, mime="text/markdown", use_container_width=True,
        )
        download_cols[1].download_button(
            "Descargar gráfico PNG", chart_path.read_bytes(),
            file_name=chart_path.name, mime="image/png", use_container_width=True,
        )
    elif values.get("human_decision") == "rejected":
        st.info("Informe rechazado: no se ha guardado ni repetido el análisis.")


st.markdown(
    '<div class="brand-line">AMIGUPRECIO · PRECIO ARTESANO CON TRAZABILIDAD</div>',
    unsafe_allow_html=True,
)
st.title("Pon precio a tu amigurumi con datos y criterio")
st.markdown(
    '<p class="intro">Calcula un precio sostenible, compáralo con productos terminados '
    "en euros y obtén una lectura comercial asistida por tres agentes. Tú decides si el "
    "informe se guarda.</p>", unsafe_allow_html=True,
)

execution: WorkflowExecution | None = st.session_state.get("workflow_execution")
if execution is None:
    with st.form("pricing_form"):
        st.subheader("Datos del producto")
        identity_left, identity_right = st.columns(2)
        with identity_left:
            product_name = st.text_input("Nombre del amigurumi", placeholder="Luna")
        with identity_right:
            product_type = st.text_input("Tipo o categoría", placeholder="Muñeca amigurumi")

        cost_a, cost_b, cost_c = st.columns(3)
        with cost_a:
            materials_cost = st.number_input("Materiales (€)", min_value=0.0, step=0.50)
            hours_worked = st.number_input("Horas de trabajo", min_value=0.0, step=0.5)
        with cost_b:
            hourly_rate = st.number_input("Precio por hora (€)", min_value=0.0, step=0.50)
            other_expenses = st.number_input("Otros gastos (€)", min_value=0.0, step=0.50)
        with cost_c:
            margin_percent = st.number_input(
                "Margen sobre ventas (%)", min_value=0.0, max_value=99.99,
                value=20.0, step=1.0,
            )
            uploaded = st.file_uploader(
                "Fotografía opcional", type=["jpg", "jpeg", "png", "webp"],
                help="JPEG, PNG o WebP; máximo 5 MB.",
            )
        st.markdown(
            '<p class="privacy-note">Si aportas una imagen, se valida y se elimina su EXIF '
            "antes de enviarla una vez a Groq para analizar solo rasgos visibles. No se "
            "aceptan URLs y la imagen no se guarda en disco.</p>", unsafe_allow_html=True,
        )
        submitted = st.form_submit_button("Analizar mi amigurumi", use_container_width=True)

    if submitted:
        try:
            product = PricingInput(
                product_name=product_name, product_type=product_type,
                materials_cost=str(materials_cost), hours_worked=str(hours_worked),
                hourly_rate=str(hourly_rate), other_expenses=str(other_expenses),
                margin_percent=str(margin_percent),
            )
            prepared = prepare_uploaded_image(uploaded.getvalue()) if uploaded else None
            execution = WorkflowExecution.production(
                product, product_type, OUTPUT_ROOT, prepared,
            )
            st.session_state.workflow_execution = execution
            with st.status("Ejecutando el flujo real…", expanded=True) as status:
                for stage in execution.start():
                    st.write(STAGE_LABELS.get(stage, stage))
                if execution.values.get("review_status") == "error":
                    status.update(label="Flujo detenido por un error", state="error")
                else:
                    status.update(label="Flujo detenido para revisión", state="complete")
        except (ValidationError, ImageValidationError) as exc:
            st.error(f"Revisa los datos: {exc}")
        except Exception as exc:  # noqa: BLE001 - frontera de UI, mensaje redactado
            st.error(f"No se pudo iniciar el flujo ({type(exc).__name__}).")

if execution is not None:
    _render_results(execution)
    if st.button("Nueva valoración"):
        del st.session_state.workflow_execution
        st.rerun()
