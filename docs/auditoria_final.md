# Auditoría final de AmiguPrecio

Fecha de auditoría: 2 de noviembre de 2026. Fuente de requisitos:
`docs/briefing.pdf`.

## Matriz de cumplimiento

| Requisito del briefing | Implementación | Evidencia | Estado | Riesgo o limitación |
|---|---|---|---|---|
| Tres agentes CrewAI auténticos | `create_agents()` en `src/amiguprecio/agents.py` crea investigador, analista y asesor | `test_exactly_three_agents_are_configured`; ejecución real completa registrada en `output/streamlit/23def349f8ef4e2bb7e8e3700f67d0a8/` | Cumplido | Requiere Groq disponible y una clave válida |
| Roles, objetivos y herramientas diferenciados | Roles y `goal` propios; investigador con MCP, analista sin herramientas y asesor con visión cuando hay foto | Configuración de `create_agents()` y log `langgraph-crewai.json` de la ejecución registrada | Cumplido | El analista interpreta, pero no calcula |
| Herramienta Python propia con entrada Pydantic | `PricingAnalysisTool`, `PricingToolInput` y `ToolMarketReference` | Pruebas de esquema, validación monetaria, resultado Decimal y traza en `tests/test_agents.py` | Cumplido | La invoca el coordinador Python, no autónomamente el analista |
| Al menos una herramienta invocada por un agente | `MCPReferenceSearchTool` en el investigador; `VisionAnalysisTool` en el asesor | La ejecución registrada contiene ambas llamadas; las pruebas exigen que el investigador haya llamado al MCP | Cumplido | El cálculo Python no cuenta como invocación autónoma |
| MCP real | Servidor `src/amiguprecio/mcp_server.py` y cliente `src/amiguprecio/mcp_client.py` por stdio | `test_stdio_client_connects_and_calls_real_tool`; una llamada MCP en la ejecución real | Cumplido | La demo estable usa el dataset guardado a través de MCP, no una búsqueda web en directo |
| Datos comerciales reales y trazables | `data/amigurumis_referencias.csv`, modelos de `references.py` y URLs en el informe | 17 filas auditadas, 17 URLs únicas, fecha, tienda, precio, moneda y procedencia `saved` | Cumplido | Son precios anunciados, no ventas realizadas; la vigencia puede cambiar |
| Análisis multimodal real integrado | `prepare_uploaded_image()`, `VisionAnalysisTool` y `analyze_image_with_groq()` | Prueba real con `qwen/qwen3.8-27b`, HTTP 200; resultado incluido en el checkpoint y el informe | Cumplido | Una foto no demuestra material, tamaño exacto, calidad, demanda ni costes |
| LangGraph con estado tipado y rutas condicionales | `AmiguPrecioGraphState` y `build_amiguprecio_graph()` | Pruebas de rutas de éxito, error, reintento y rechazo en `tests/test_langgraph_workflow.py` | Cumplido | Checkpointer en memoria; un reinicio pierde aprobaciones pendientes |
| Bucle de revisión limitado | `_retry_or_error()` limita `retry_count` a uno | Pruebas del segundo fallo y de no repetición de MCP/Python | Cumplido | Solo analista o asesor pueden reintentarse una vez |
| Interrupción humana real | `interrupt()` en `approval_node()` y reanudación con `Command` y el mismo `thread_id` | Pruebas de aprobación y rechazo; demo real aprobada | Cumplido | La decisión pendiente no persiste al reiniciar Streamlit |
| Automatización solo tras aprobación | `report_node()` se alcanza únicamente si `human_decision == "approved"` | Prueba de rechazo: no se crea archivo; aprobación: se guarda una vez | Cumplido | El gráfico y el log técnico se generan antes de aprobar; el informe final no |
| Resultados monetarios oficiales de Python | `pricing.py`, `run_deterministic_analysis()` y comprobaciones contra cambios del LLM | Pruebas impiden que analista/asesor sustituyan 81,25 por 78,00 | Cumplido | El usuario sigue siendo responsable de introducir todos sus costes |
| Interfaz Streamlit funcional | Formulario, foto, progreso por etapas, revisión, aprobación/rechazo y descargas en `app.py` | Revisión visual de escritorio y móvil; ejecución real de extremo a extremo | Cumplido | El progreso se actualiza al terminar cada nodo; no muestra cada llamada de herramienta mientras está en curso |
| Visibilidad en tiempo real del agente/herramienta activo | `WorkflowExecution.start()` emite actualizaciones de nodos y la UI muestra etapas | En la demo se ven las etapas completadas | Parcial | No hay telemetría intra-nodo; no debe presentarse como un monitor en tiempo real de cada tool call |
| Trazabilidad, fuentes y log | Referencias tipadas, URLs en informe y `langgraph-crewai.json` | Informe registrado conserva tienda, procedencia y enlace; log conserva eventos CrewAI | Cumplido | La UI descarga informe y gráfico, pero no ofrece el log técnico como descarga |
| Control de errores, tokens y ciclos | Timeouts de red, mensajes redactados, `max_iter`, `max_retry_limit`, `max_tokens`, `max_retries=0` y uso capturado | Pruebas de fallos de fuente, visión y agentes; reintentos acotados | Parcial | `MAX_LLM_CALLS` y `MAX_ESTIMATED_COST_EUR` de `.env.example` no son límites ejecutables; no afirmar que cortan el flujo |
| Seguridad y privacidad | Claves solo por entorno, imagen validada/recodificada sin EXIF, no se guarda la foto | `.gitignore`, `.env.example` y pruebas de imagen | Cumplido | Foto y prompts se envían a Groq; debe explicarse antes de la demo |
| Arquitectura y justificación | Diagrama y reparto CrewAI/LangGraph/MCP/Python en `README.md` | Diagrama Mermaid y documentación final | Cumplido | La arquitectura es un MVP local, no un servicio multiusuario |
| Buenas prácticas Git y revisión colaborativa | Cinco commits locales por hitos; repositorio limpio antes de esta auditoría | Historial `b44bbec` a `7054dfe` | Parcial | Desarrollo individual en `main`; no existen ramas ni PR revisadas y no se simulan |
| Presentación de 7–10 minutos | `docs/guion_presentacion.md` | Guion cronometrado y caso de demo reproducible | Cumplido | Requiere ensayar el cambio entre ejecución en directo y evidencia registrada |

## Qué herramienta ejecuta realmente cada componente

- **Investigador CrewAI:** decide e invoca autónomamente
  `search_market_references`; la herramienta llama al cliente y al servidor MCP.
- **Coordinador Python:** invoca directamente `PricingAnalysisTool` una vez. Es una
  herramienta Pydantic real y genera el gráfico, pero no es una decisión del LLM.
- **Analista CrewAI:** no dispone de herramientas. Interpreta un resumen corto de los
  resultados oficiales y no puede sustituirlos.
- **Asesor CrewAI:** cuando se ha aportado una foto, decide e invoca autónomamente
  `analyze_uploaded_amigurumi_image`; su JSON se valida con
  `CommercialAssessment`.
- **LangGraph:** coordina estados, rutas, reintento, interrupción y guardado; no es un
  cuarto agente.

## Auditoría de las 17 referencias

El CSV contiene 17 productos terminados, 17 URLs únicas, precios positivos, monedas
ISO, tienda y fecha de consulta. No contiene patrones ni kits. Hay nueve tamaños no
publicados; se mantienen como ausentes, sin rellenarlos. Todas las filas tienen
procedencia `saved` al convertirse a `MarketReference`.

| # | Producto | Precio | Categoría / tamaño | URL y evaluación |
|---:|---|---:|---|---|
| 1 | Amigurumi Elephant | 35,00 USD | amigurumi animal / no publicado | [SweetLavenderCo](https://sweetlavenderco.com/products/amigurumi_elephant); terminado y verificable |
| 2 | Amigurumi Giraffe | 35,00 USD | amigurumi animal / no publicado | [SweetLavenderCo](https://sweetlavenderco.com/products/amigurumi_giraffe); terminado y verificable |
| 3 | Amigurumi Owl | 41,00 USD | amigurumi animal / no publicado | [SweetLavenderCo](https://sweetlavenderco.com/products/amigurumi_owl); terminado y verificable |
| 4 | Amigurumi Reindeer | 44,00 USD | amigurumi animal / no publicado | [SweetLavenderCo](https://sweetlavenderco.com/products/amigurumi_reindeer); terminado y verificable |
| 5 | Handmade Crochet Bumblebee Toy | 33,50 GBP | amigurumi animal / 25 cm | [Umbrella Crochet](https://umbrellacrochet.com/product/handmade-crochet-bumblebee-toy-bee-amigurumi/); terminado y verificable |
| 6 | Handmade Crochet Dog Toy | 28,00 GBP | amigurumi animal / no publicado | [Umbrella Crochet](https://umbrellacrochet.com/product/handmade-crochet-dog-toy-adorable-amigurumi-plushie-gift/); la ficha no aporta un tamaño utilizable |
| 7 | Handmade Crochet Unicorn Toy | 38,00 GBP | amigurumi animal / 28 cm | [Umbrella Crochet](https://umbrellacrochet.com/product/handmade-crochet-unicorn-toy-28cm/); terminado y verificable |
| 8 | Handmade Crochet Teddy Bear with Bumblebee | 26,99 GBP | amigurumi animal / 20 cm | [Umbrella Crochet](https://umbrellacrochet.com/product/handmade-crochet-teddy-bear-with-bumblebee-amigurumi-plush-toy/); se conserva el precio anunciado vigente |
| 9 | Handmade Crochet White Teddy Bunny Plushie | 1.599,00 INR | amigurumi plushie / no publicado | [Nidsscrochet](https://www.nidsscrochet.in/product/handmade-crochet-white-teddy-bunny-plushie); terminado y verificable |
| 10 | Handmade Crochet White Elephant Plushie | 1.899,00 INR | amigurumi plushie / no publicado | [Nidsscrochet](https://www.nidsscrochet.in/product/handmade-crochet-white-elephant-plushie-amigurumi-toy); terminado y verificable |
| 11 | Handmade Crochet Turtle Plushie | 1.950,00 INR | amigurumi plushie / no publicado | [Nidsscrochet](https://www.nidsscrochet.in/product/handmade-crochet-turtle-plushie-amigurumi-toy); se conserva el precio anunciado vigente |
| 12 | Handmade Crochet Deer Plushie | 2.699,00 INR | amigurumi plushie / no publicado | [Nidsscrochet](https://www.nidsscrochet.in/product/handmade-crochet-deer-plushie); terminado y verificable |
| 13 | Strawberry Reversible Crochet Toy | 30,90 EUR | crochet plush toy / 15 × 9 × 9 cm | [MyUM](https://myum.fr/en/products/la-fraise-jouet-reversible-en-coton-bio); terminado, pero débilmente comparable con una muñeca |
| 14 | Crab Crochet Lovie | 22,90 EUR | crochet animal comforter / 30 × 25 × 4 cm | [MyUM](https://myum.fr/en/products/doudou-crabe-en-crochet-100-coton-bio); no es una muñeca ni un amigurumi equivalente |
| 15 | Pink Butterfly Crochet Rattle and Comforter | 21,90 EUR | crochet animal toy / 14 × 20 × 4 cm | [MyUM](https://myum.fr/en/products/hochet-doudou-papillon-rose-100-coton-bio); sonajero/doudou, no muñeca equivalente |
| 16 | Anne Claire Petit Bunny Crochet Doll | 45,00 EUR | amigurumi doll / 30 cm | [Maxland](https://www.maxland.gr/en/product/anne-claire-petit-bunny-doll); comparable como muñeca tejida terminada |
| 17 | Anne Claire Petit Dog Crochet Doll | 48,75 EUR | amigurumi doll / 30 cm | [Maxland](https://www.maxland.gr/en/product/anne-claire-petit-dog-doll); comparable como muñeca tejida terminada |

Las URL, fechas y tiendas exactas están en `data/amigurumis_referencias.csv`. La
auditoría no demuestra ventas realizadas, demanda ni beneficio. Un precio anunciado
solo prueba que la tienda ofrecía el producto a ese importe en la fecha registrada.

### Caso de demostración

Para la consulta `muñeca amigurumi`, el ranking devuelve dos muñecas de 30 cm y el
juguete reversible de fresa. La aritmética es correcta:

- coste de producción: `15 + (5 × 9) + 5 = 65,00 EUR`;
- precio con margen sobre ventas del 20 %: `65 / (1 - 0,20) = 81,25 EUR`;
- media de `45,00`, `48,75` y `30,90`: `41,55 EUR`;
- mediana: `45,00 EUR`.

La muestra de tres productos **no es homogénea** por tipo y tamaño. En la defensa se
presentará como referencia orientativa de productos tejidos terminados en EUR, no
como una valoración concluyente de muñecas equivalentes. Las dos referencias de
Maxland sí son las comparables más cercanas. No procede afirmar que 81,25 EUR sea
“premium” solo por esta muestra ni estimar ventas o beneficios garantizados.

## Revisión de interfaz y casos límite

| Caso | Resultado verificado |
|---|---|
| Datos válidos | Cálculo y flujo completos; 65,00/81,25 EUR en el caso de control |
| Costes cero | Permitidos por formulario y Pydantic; con margen válido producen cero sin división inválida |
| Valores negativos | Bloqueados por `min_value=0` y rechazados por Pydantic fuera de la UI |
| Margen inválido | UI limita 0–99,99; Pydantic rechaza valores negativos o mayores/iguales a 100 |
| Fotografía no válida o >5 MB | Rechazada antes de llamar al proveedor |
| Fallo de Groq | Se muestra un error redactado o una limitación visual; no se revelan credenciales |
| Sin referencias de la moneda | No se inventan media ni mediana; el informe lo declara expresamente |
| Aprobación | Reanuda el mismo checkpoint y guarda un informe una sola vez |
| Rechazo | Finaliza sin guardar informe y sin repetir MCP/Python |
| Descarga | Tras aprobar se ofrecen Markdown y PNG |
| Ejecuciones independientes | “Nueva valoración” elimina el objeto de sesión; la siguiente usa UUID, carpeta y `thread_id` nuevos |

Defecto corregido en esta auditoría: un flujo terminado en error se etiquetaba
visualmente como “detenido para revisión”. `app.py` ahora usa estado de error cuando
`review_status` vale `error`. No se ha alterado el flujo ni el diseño.

## Estado de validación y bloqueo de Windows

- **Evidencia anterior:** 62 pruebas superadas después de los cambios funcionales de
  Fase 4 y Ruff limpio.
- **Ejecución actual:** la colección de Pytest queda bloqueada al importar Pandas; no
  es un fallo de aserción.
- **Pruebas no dependientes de Pandas:** 23 superadas actualmente (precio, dataset,
  referencias y MCP).
- **Intérprete:** `.venv/Scripts/python.exe`, Python 3.11.16, con `sys.prefix` dentro
  del entorno virtual del proyecto.
- **DLL identificada:**
  `.venv/Lib/site-packages/pandas/_libs/pandas_datetime.cp311-win_amd64.pyd`.
- **Evidencia del sistema:** eventos Code Integrity 3033 y 3077 indican que la DLL no
  cumple el nivel de firma Enterprise de la política
  `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. PowerShell informa `NotSigned`.
- También hay un evento equivalente para `_pydantic_core.cp311-win_amd64.pyd` de la
  caché de `uv`; por ello no se debe asumir que el problema es exclusivo de Pandas.

No se ha desactivado la política, sustituido DLL, editado paquetes ni reinstalado el
entorno. La resolución corresponde a la administración de Windows: permitir
binarios de las dependencias aprobadas o proporcionar un entorno autorizado. Tras
ello debe repetirse `uv run pytest`.

## Demostración reproducible

### Preparación

1. En PowerShell: `Set-Location` a la raíz del repositorio.
2. Confirmar que `.env` contiene una `GROQ_API_KEY` válida sin mostrarla.
3. Ejecutar `uv run streamlit run app.py`.
4. Tener disponible `tests/fixtures/authorized-amigurumi.png`.
5. Cerrar otras sesiones de la app para identificar con claridad la nueva carpeta.

### Ejecución en directo

1. Nombre: `Luna`.
2. Tipo: `muñeca amigurumi`.
3. Materiales: `15`; horas: `5`; tarifa: `9`; otros gastos: `5`; margen: `20`.
4. Subir `tests/fixtures/authorized-amigurumi.png` y explicar el aviso de privacidad.
5. Pulsar **Analizar mi amigurumi** una sola vez.
6. Señalar investigación CrewAI + MCP, cálculo Python, analista, asesor + visión y
   revisión LangGraph. No llamar “tiempo real por herramienta” al progreso por nodo.
7. Mostrar 65,00 EUR y 81,25 EUR; presentar 41,55/45,00 EUR como muestra orientativa.
8. Revisar fuentes y limitaciones antes de aprobar.
9. Aprobar y descargar Markdown y PNG. Si se demuestra rechazo, hacerlo en una
   ejecución separada porque esa decisión es final.

### Evidencia de contingencia

La ejecución real ya completada está registrada localmente en
`output/streamlit/23def349f8ef4e2bb7e8e3700f67d0a8/` con informe, gráfico y log
CrewAI. Debe presentarse explícitamente como **ejecución previa registrada**, no como
actividad en directo. Si falla red/Groq durante la defensa, mostrar esos tres archivos
y explicar que el cálculo, el grafo y las pruebas deterministas no dependen de una
respuesta nueva del proveedor.

## Riesgos antes de entregar

1. Resolver con TI la política de firma y repetir Pytest; es el principal bloqueo.
2. Confirmar la clave y la cuota Groq sin consumir llamadas innecesarias.
3. Ensayar la advertencia de comparabilidad de la tercera referencia EUR.
4. No afirmar que las variables `MAX_LLM_CALLS` o `MAX_ESTIMATED_COST_EUR` aplican un
   corte automático.
5. No presentar el dataset local como búsqueda web en directo ni los precios como
   ventas.
6. Conservar la ejecución registrada como respaldo, pero diferenciarla de la demo
   en vivo.
7. Explicar con honestidad que el proyecto es individual y no tuvo PRs revisadas.
