from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_initial_form_is_complete_and_does_not_call_providers() -> None:
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py").run(timeout=15)

    assert not app.exception
    assert app.title[0].value == "Pon precio a tu amigurumi con datos y criterio"
    assert app.button[0].label == "Analizar mi amigurumi"
    assert {item.label for item in app.text_input} == {
        "Nombre del amigurumi",
        "Tipo o categoría",
    }
    assert {item.label for item in app.number_input} == {
        "Materiales (€)",
        "Horas de trabajo",
        "Precio por hora (€)",
        "Otros gastos (€)",
        "Margen sobre ventas (%)",
    }
