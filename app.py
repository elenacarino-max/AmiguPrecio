"""Interfaz Streamlit de la Fase 1 de AmiguPrecio."""

import streamlit as st
from pydantic import ValidationError

from amiguprecio import PricingInput, calculate_price

st.set_page_config(page_title="AmiguPrecio", layout="centered")
st.markdown(
    """
    <style>
    :root {
        --bg: #fbf6ec;
        --surface: #fffdf8;
        --text: #2b2926;
        --muted: #625d55;
        --border: #ded5c6;
        --brand: #375b4a;
        --action: #b94f3d;
        --action-hover: #9e4032;
        --action-tint: #f8e4df;
    }
    .stApp { background: var(--bg); color: var(--text); }
    .block-container { max-width: 780px; padding-top: 3rem; padding-bottom: 4rem; }
    h1, h2, h3 { color: var(--brand); letter-spacing: -0.02em; }
    p, label, [data-testid="stCaptionContainer"] { color: var(--muted); }
    .amigu-eyebrow {
        color: var(--brand);
        font-size: .75rem;
        font-weight: 700;
        letter-spacing: .14em;
        padding-bottom: .8rem;
        border-bottom: 1px dashed var(--border);
        margin-bottom: 1.25rem;
    }
    div.stButton > button {
        background: var(--action);
        color: white;
        border: 1px solid var(--action);
        border-radius: .35rem;
        font-weight: 700;
    }
    div.stButton > button:hover { background: var(--action-hover); border-color: var(--action-hover); }
    div.stButton > button:focus-visible {
        outline: 3px solid var(--action-tint);
        outline-offset: 2px;
    }
    [data-testid="stMetric"] {
        background: transparent;
        border-top: 2px solid var(--brand);
        border-bottom: 1px solid var(--border);
        padding: .85rem .15rem 1rem;
    }
    [data-testid="stForm"] {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: .5rem;
        padding: 1.25rem;
    }
    input:focus-visible, textarea:focus-visible, button:focus-visible {
        outline-color: var(--brand) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="amigu-eyebrow">AMIGUPRECIO · PRECIO ARTESANO CON CRITERIO</div>',
    unsafe_allow_html=True,
)
st.title("Calcula un precio que sostenga tu trabajo")
st.caption("Calcula un precio rentable antes de compararlo con el mercado.")

with st.form("pricing_form"):
    left, right = st.columns(2)
    with left:
        product_name = st.text_input("Nombre del amigurumi", placeholder="Luna")
        product_type = st.text_input("Tipo", placeholder="Muñeca de ganchillo")
        materials_cost = st.number_input("Materiales (€)", min_value=0.0, step=0.50)
        hours_worked = st.number_input("Horas de trabajo", min_value=0.0, step=0.5)
    with right:
        hourly_rate = st.number_input("Precio deseado por hora (€)", min_value=0.0, step=0.50)
        other_expenses = st.number_input("Otros gastos (€)", min_value=0.0, step=0.50)
        margin_percent = st.number_input(
            "Margen sobre ventas (%)", min_value=0.0, max_value=99.99, value=20.0, step=1.0
        )
        image = st.file_uploader(
            "Fotografía (análisis disponible en la Fase 3)", type=["jpg", "jpeg", "png"]
        )
    submitted = st.form_submit_button("Calcular precio", use_container_width=True)

if image:
    st.image(image, caption="Fotografía aportada", width=280)

if submitted:
    try:
        data = PricingInput(
            product_name=product_name,
            product_type=product_type,
            materials_cost=str(materials_cost),
            hours_worked=str(hours_worked),
            hourly_rate=str(hourly_rate),
            other_expenses=str(other_expenses),
            margin_percent=str(margin_percent),
        )
        result = calculate_price(data)
    except ValidationError as exc:
        errors = "; ".join(error["msg"] for error in exc.errors())
        st.error(f"Revisa los datos: {errors}")
    else:
        st.subheader("Resultado del cálculo")
        col1, col2, col3 = st.columns(3)
        col1.metric("Mano de obra", f"{result.labor_cost:.2f} €")
        col2.metric("Coste de producción", f"{result.production_cost:.2f} €")
        col3.metric("Precio calculado", f"{result.calculated_price:.2f} €")
        st.info(
            "El precio calculado aplica margen sobre ventas. No incluye comisiones, impuestos "
            "ni gastos que no se hayan introducido como otros gastos. Aún no es una comparación de mercado."
        )
