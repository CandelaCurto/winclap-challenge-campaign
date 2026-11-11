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
| Gasto negativo | 5 | Se pasa a positivo. 4 quedan; la quinta se descarta igual por otros motivos |
| Más clicks que impresiones (ej. 114.055 impresiones, 114.102 clicks) | 6 | Se descarta la fila |
| Conversiones vacías | 8 (7 sin contar duplicados) | Se descarta la fila (`conversions vacío`) |
| Revenue vacío | 7 (6 sin contar duplicados) | Se descarta la fila (`revenue vacío`) |
| Varias filas distintas de la misma campaña el mismo día | 41 campañas-día | Se unen en una fila, sumando |
| Dos campañas distintas con el mismo nombre (C1001 y C1006) | — | Todo se agrupa por `campaign_id`, nunca por nombre |

Una misma fila puede tener varios problemas: la de C1011 del 17/09 (línea 6) tiene gasto negativo,
más clicks que impresiones y conversiones y revenue vacíos, y además está duplicada (línea 8). En
`rejected_rows` aparecen todos sus motivos.

## Resultado

| Paso | Filas |
|---|---|
| Filas leídas | 214 |
| Duplicados descartados | 6 |
| Inválidas descartadas | 17: 6 con más clicks que impresiones, 7 sin conversiones y 6 sin revenue (una fila tiene los tres motivos) |
| **Filas válidas** | **191** (10,7 % descartado, debajo del máximo del 20 %) |
| De ellas, con el gasto corregido a positivo | 4 (1,9 %) |
| **Filas por campaña y día** | **141** (41 formadas por 2 o 3 filas originales) |
| **Campañas en el resumen** | **12** |

Comprobación de la unión: el gasto y las impresiones totales son los mismos antes y después de unir.

## Casos que muestran por qué cada regla

**Lo que cuesta descartar las filas con datos vacíos.** 11 filas se descartaron solo por tener
conversiones o revenue vacíos. Sus impresiones, clicks y gasto eran válidos y se pierden con ellas:
suman **USD 11.254,61, el 6,6 % del gasto** del archivo. Por ejemplo, C1004 el 4/9 tenía dos filas:
una de USD 288,06 con 9 conversiones y otra de USD 2.275,52 sin conversiones. Queda solo la primera,
así que ese día figura con USD 288,06 de gasto. Es el precio de que todo lo publicado esté completo y
se pueda verificar; las 11 filas, con su gasto, están en `rejected_rows`.

**Métricas vacías.** Solo queda el CPA vacío en 7 días, los que tuvieron 0 conversiones: dividir por
0 no tiene resultado. CTR, CPC y ROAS no tienen vacíos.

**Por qué el objetivo importa al leer.** C1006 es una campaña de Awareness con un CPA de USD 205,85:
alto, pero esperable, porque no busca conversiones. Se juzga por cuánto se la vio (impresiones, CTR).

**El supuesto del gasto negativo.** Las 4 filas corregidas suman USD 2.085,86. Si alguna fuera un
reembolso y no un error de signo, ese monto estaría sumando gasto que no existió; están listadas en
`corrected_rows` para validarlo.
