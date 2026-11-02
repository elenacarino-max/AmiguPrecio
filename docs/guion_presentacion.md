# Guion de presentación de AmiguPrecio

Duración objetivo: 8 minutos. No hace falta leer el texto literalmente; las marcas
de tiempo sirven para mantener el ritmo.

## 0:00–0:50 — El problema

Una artesana puede conocer el coste del hilo, pero olvidar valorar todas sus horas,
los gastos adicionales o la diferencia entre recargo y margen sobre ventas. Además,
comparar productos en internet es difícil: hay monedas distintas, patrones mezclados
con productos terminados y precios que no prueban ventas reales.

AmiguPrecio ayuda a preparar una valoración trazable. No promete el “precio perfecto”
ni beneficios: calcula una base reproducible, aporta referencias y deja la decisión
final a la persona.

## 0:50–1:30 — La solución y su público

El MVP está pensado para artesanas y pequeños negocios de amigurumis. Recibe costes,
horas, tarifa, gastos, margen y, opcionalmente, una fotografía. Devuelve el cálculo
oficial, un gráfico, referencias con fuente, una interpretación comercial y un
informe que solo se guarda después de aprobación humana.

## 1:30–2:40 — Arquitectura y tres agentes

Mostrar el diagrama del README.

- El **investigador CrewAI** invoca autónomamente una herramienta MCP. El servidor
  consulta como respaldo un CSV local de productos terminados verificados y conserva
  URL, tienda, fecha, moneda y procedencia.
- El **coordinador Python** ejecuta la herramienta de cálculo con entrada Pydantic.
  Esta separación es intencionada: el LLM no decide ni modifica los importes.
- El **analista CrewAI** interpreta un resumen de las cifras oficiales, sin
  herramientas y sin capacidad de recalcular.
- El **asesor CrewAI** produce una valoración estructurada y, si hay foto, invoca
  autónomamente la herramienta visual. El JSON final se valida con Pydantic.
- **LangGraph** no es otro agente: controla el estado, las rutas de error, un único
  reintento, la pausa humana y el guardado posterior.

CrewAI resulta útil para roles y uso autónomo de herramientas; MCP desacopla la
fuente de referencias; LangGraph aporta control explícito y reanudación.

## 2:40–5:35 — Demostración

Introducir el caso de control:

- nombre `Luna`, tipo `muñeca amigurumi`;
- materiales 15 €, 5 horas, tarifa 9 €/h, otros gastos 5 €;
- margen sobre ventas del 20 %;
- fotografía autorizada de `tests/fixtures/authorized-amigurumi.png`.

Pulsar una vez **Analizar mi amigurumi** y narrar las etapas. Aclarar que la interfaz
actualiza el progreso al terminar cada nodo; el log conserva el detalle técnico.

Señalar los resultados:

- coste: `15 + 5 × 9 + 5 = 65,00 €`;
- precio: `65 / (1 - 0,20) = 81,25 €`;
- referencias EUR: 45,00 €, 48,75 € y 30,90 €;
- media 41,55 € y mediana 45,00 €.

La aritmética es exacta, pero la muestra es heterogénea: dos son muñecas de 30 cm y
la tercera es un juguete reversible de fresa. Por eso la comparación es orientativa,
no una demostración de que 81,25 € vaya a venderse ni de que genere un beneficio
garantizado.

Mostrar el análisis visual y sus límites: la foto permite describir colores, forma y
detalles visibles, pero no material exacto, tamaño, horas, coste, calidad o demanda.

Revisar las fuentes. Aprobar el informe y descargar Markdown y PNG. Explicar que un
rechazo termina sin informe y sin repetir MCP, Python ni agentes.

## 5:35–6:35 — Precisión, control y supervisión

Los importes usan `Decimal` y Pydantic rechaza valores no finitos, negativos o un
margen inválido. Las monedas no se mezclan ni convierten sin una fuente de cambio.
Las respuestas del analista y asesor se comparan con las cifras Python para impedir
que las sustituyan.

El grafo admite un solo reintento del analista o asesor. MCP y el cálculo correcto no
se repiten. Antes de guardar, `interrupt()` exige una decisión explícita y reanuda el
mismo checkpoint.

## 6:35–7:25 — Seguridad, ética y limitaciones

La clave está en `.env` y no se registra. La imagen es opcional, se valida, se
recodifica sin EXIF y no se guarda, aunque sus bytes sí se envían una vez a Groq.

El dataset es una fotografía temporal de precios anunciados. No representa ventas,
demanda ni beneficios. La fuente guardada no se presenta como búsqueda web en
directo. El checkpointer es en memoria, la muestra comercial es pequeña y la app no
es todavía multiusuario.

La ejecución externa depende de red, cuota y disponibilidad de Groq. Las iteraciones,
tokens y reintentos están acotados, pero las variables de coste estimado del ejemplo
no implementan un corte automático.

## 7:25–8:00 — Cierre y siguientes pasos

AmiguPrecio demuestra una combinación responsable: agentes para investigar e
interpretar, Python para calcular, MCP para fuentes, LangGraph para control y una
persona para autorizar el resultado.

Mejoras futuras razonables, sin afirmar que ya existen: ampliar referencias realmente
comparables, registrar históricos de precios, añadir conversión monetaria con fuente
fechada, persistir checkpoints de forma segura y medir la utilidad con artesanas
reales. El proyecto se ha desarrollado individualmente; no se simulan ramas, PRs ni
métricas de negocio inexistentes.

## Plan de contingencia

Si falla la conexión durante la defensa, no repetir llamadas en cadena. Abrir
`output/streamlit/23def349f8ef4e2bb7e8e3700f67d0a8/` y mostrar el informe, el
gráfico y el log como **evidencia de una ejecución real previa**. Después, enseñar las
pruebas deterministas y distinguir con claridad esa evidencia de una ejecución en
directo.
