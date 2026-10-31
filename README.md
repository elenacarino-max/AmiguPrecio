# AmiguPrecio

MVP para que artesanas y artesanos calculen un precio rentable para sus amigurumis y, en las siguientes fases, lo contrasten con referencias reales y trazables del mercado.

## Estado

**Fase 1 verificada:** modelo de entrada Pydantic, cálculo determinista, interfaz Streamlit inicial y pruebas unitarias. Las consultas de mercado, agentes, MCP, LangGraph, visión e informe final pertenecen a las fases siguientes y no se simulan en esta versión.

La fórmula implementada es:

```text
coste de producción = materiales + (horas × tarifa por hora) + otros gastos
precio calculado = coste de producción / (1 - margen / 100)
```

El margen es margen sobre ventas, no un recargo sobre costes. El resultado no incluye comisiones, impuestos ni gastos no declarados.

## Arquitectura objetivo (MVP)

```mermaid
flowchart LR
    UI[Streamlit] --> LG[LangGraph\nestado y control]
    LG --> A1[CrewAI\ninvestigador]
    LG --> A2[CrewAI\nanalista]
    LG --> A3[CrewAI\nasesor visual]
    A1 --> MCP[Servidor MCP\nreferencias]
    A2 --> PY[Python\nPydantic + pandas + matplotlib]
    A3 --> V[Modelo multimodal]
    LG --> HITL{Aprobación humana}
    HITL -->|aprobar| REPORT[Informe descargable]
    HITL -->|rechazar| END[Fin sin guardar]
```

CrewAI define roles y herramientas especializadas. LangGraph controla el orden, los límites, la revisión y la pausa humana; no duplica el trabajo de los agentes.

## Estructura

```text
AmiguPrecio/
├── app.py
├── docs/briefing.pdf
├── src/amiguprecio/
│   ├── models.py
│   └── pricing.py
├── tests/test_pricing.py
├── .env.example
└── pyproject.toml
```

## Instalación en Windows (PowerShell)

Requisitos: Git y [uv](https://docs.astral.sh/uv/). `uv` instalará una versión compatible de Python si hace falta.

```powershell
git clone https://github.com/elenacarino-max/AmiguPrecio.git
Set-Location AmiguPrecio
Copy-Item .env.example .env
uv sync --extra dev
```

No añadas claves a Git. La Fase 1 no consume ninguna API ni realiza llamadas de pago.

## Ejecutar

```powershell
uv run streamlit run app.py
```

## Pruebas y calidad

```powershell
uv run pytest
uv run ruff check .
```

## Hoja de ruta mínima

1. **Fase 1:** calculadora validada e interfaz base. Completada.
2. **Fase 2:** tres agentes CrewAI y herramientas; servidor y cliente MCP reales.
3. **Fase 3:** LangGraph con revisión limitada, errores, presupuesto, pausa/reanudación y visión.
4. **Fase 4:** comparación, gráfico, informe, aprobación/rechazo y pruebas de integración.
5. **Fase 5:** auditoría contra el briefing, documentación y guion de demo.

## Fuente de requisitos

El briefing oficial se conserva en `docs/briefing.pdf`. Sus mínimos prevalecen sobre decisiones auxiliares de implementación.

