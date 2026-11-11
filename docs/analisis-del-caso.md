# Análisis del archivo del caso

Los problemas que tenía `campaigns.csv`, el archivo entregado para el caso, y cómo quedó después de
procesarlo. Las reglas generales están en el [README](../README.md); acá están los números de esta
carga.

## El archivo

- **214 filas y 12 columnas**, del 1 al 22 de septiembre de 2026.
- **12 campañas** (C1001 a C1012) en 4 países (AR, CL, CO, MX), 3 objetivos (Awareness,
  Consideration, Conversion) y 3 plataformas (Google Ads, Meta Ads, LinkedIn Ads). Todo en USD.
- Al leerlo, todas las columnas llegan como texto: el `"$ 182,41"` de una celda alcanza para que la
  columna de gasto entera no se reconozca como número.

## Problemas encontrados

| Problema | Filas | Qué se hizo |
|---|---|---|
| Fechas en dos formatos (`2026-09-17` y `17/09/2026`) | 25 | Todo a fecha. Con barras es día/mes: `17/09` no admite otra lectura |
| Espacios sobrantes en el nombre de campaña | 9 | Se recortan |
| El canal escrito de 8 formas (`GOOGLE ADS`, `google ads`, `meta`, `Facebook Ads`…) | todas | Se reconoce por palabra clave → `Google Ads`, `Meta Ads`, `LinkedIn Ads` |
| Gasto como texto con formato de moneda (`"$ 182,41"`) | 9 | Se convierte a número |
| Duplicados exactos | 6 | Se descartan |
| Gasto negativo | 5 | Se pasa a positivo. 4 quedan; la quinta se descarta igual por más clicks que impresiones |
| Más clicks que impresiones (ej. 114.055 impresiones, 114.102 clicks) | 6 | Se descarta la fila |
| Conversiones o revenue vacíos | 6 y 5 | La fila se queda; el valor queda vacío, no 0 |
| Varias filas distintas de la misma campaña el mismo día | 48 campañas-día | Se unen en una fila, sumando |
| Dos campañas distintas con el mismo nombre (C1001 y C1006) | — | Todo se agrupa por `campaign_id`, nunca por nombre |

Una misma fila puede tener varios problemas: la de C1011 del 17/09 está duplicada, tiene gasto
negativo, más clicks que impresiones y conversiones y revenue vacíos.

## Resultado

| Paso | Filas |
|---|---|
| Filas leídas | 214 |
| Duplicados descartados | 6 |
| Inválidas descartadas (más clicks que impresiones) | 6 |
| **Filas válidas** | **202** (5,6 % descartado) |
| De ellas, con el gasto corregido a positivo | 4 (1,9 %) |
| **Filas por campaña y día** | **145** (48 formadas por 2 o 3 filas originales) |
| **Campañas en el resumen** | **12** |

Comprobación de la unión: el gasto y las impresiones totales son los mismos antes y después de unir.

## Casos que muestran por qué cada regla

**Por qué un vacío deja vacío el total del día.** C1004 el 4/9 tiene dos filas: una con USD 288 de
gasto y 9 conversiones, otra con USD 2.276 de gasto y conversiones vacías. Sumando solo lo conocido
quedarían 9 conversiones sobre USD 2.564: un CPA de USD 284,8, falso pero con apariencia de completo.

**Por qué el resumen usa solo los días con dato.** En C1004 el 34 % del gasto cayó en días sin dato
de conversiones. Con los días que tienen el dato, el CPA da **USD 10,07**; dividiendo el gasto total
daría USD 15,29, un 52 % peor por un dato que falta y no por la campaña.

En `campaign_summary` se ve así: `spend` = 11.223,57, `spend_with_conversions` = 7.391,30,
`conversions` = 734 y `cpa` = 7.391,30 / 734 = 10,07.

Parte del gasto usada en cada campaña con días sin dato (`spend_with_conversions` y
`spend_with_revenue` sobre `spend`):

| Campaña | Gasto usado para el CPA | Gasto usado para el ROAS |
|---|---|---|
| C1002 | 100 % | 92 % |
| C1004 | 66 % | 100 % |
| C1005 | 100 % | 98 % |
| C1006 | 68 % | 100 % |
| C1009 | 84 % | 96 % |
| C1010 | 100 % | 97 % |

**Métricas vacías.** CPA vacío en 12 filas (6 sin dato de conversiones y 6 con 0 conversiones) y ROAS
vacío en 5 (sin dato de revenue). CTR y CPC sin vacíos: no hay filas con 0 impresiones ni 0 clicks.

**Por qué el objetivo importa al leer.** C1006 es una campaña de Awareness con un CPA de USD 205,85:
alto, pero esperable, porque no busca conversiones. Se juzga por cuánto se la vio (impresiones, CTR).

**El supuesto del gasto negativo.** Las 4 filas corregidas suman USD 2.085,86. Si alguna fuera un
reembolso y no un error de signo, ese monto estaría sumando gasto que no existió; están listadas en
`corrected_rows` para validarlo.
