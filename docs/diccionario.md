# Diccionario de datos

Qué es cada columna de las tabs del Sheet de resultados y cómo se calcula.

## Columnas de las dos tabs

| Columna | Qué es | Cómo se calcula |
|---|---|---|
| `campaign_id` | Código único de la campaña | Del archivo |
| `campaign_name` | Nombre: `PAÍS_OBJETIVO_PLATAFORMA_PERÍODO` | Del archivo, sin espacios sobrantes. Si una campaña trae más de uno, el más frecuente |
| `channel` | Plataforma: Google Ads, Meta Ads o LinkedIn Ads | Reconocida por palabra clave en el canal del archivo |
| `country` | País de la campaña | Del archivo |
| `objective` | Objetivo: Awareness, Consideration o Conversion | Del archivo |
| `currency` | Moneda de todos los montos de la fila | Del archivo |

## `clean_data`: una fila por campaña y día

| Columna | Qué es | Cómo se calcula |
|---|---|---|
| `date` | Día | Del archivo (acepta `AAAA-MM-DD` y `DD/MM/AAAA`) |
| `impressions` | Veces que se mostró el anuncio ese día | Suma de las filas de esa campaña y día |
| `clicks` | Clicks del día | Suma de las filas de esa campaña y día |
| `conversions` | Conversiones del día | Suma de las filas de esa campaña y día |
| `spend` | Gasto del día | Suma de las filas de esa campaña y día. Un gasto negativo se pasó a positivo (ver `corrected_rows`) |
| `revenue` | Ingresos del día | Suma de las filas de esa campaña y día |
| `ctr` | Click-through rate: de cada 100 impresiones, cuántos clicks | `clicks / impressions` |
| `cpc` | Costo por click | `spend / clicks` |
| `cpa` | Costo por conversión | `spend / conversions`. Vacío si no hubo conversiones |
| `roas` | Dólares que volvieron por cada dólar invertido | `revenue / spend` |

## `campaign_summary`: una fila por campaña

| Columna | Qué es | Cómo se calcula |
|---|---|---|
| `impressions` | Impresiones de la campaña | Suma de todos los días |
| `clicks` | Clicks de la campaña | Suma de todos los días |
| `conversions` | Conversiones de la campaña | Suma de todos los días |
| `spend` | Gasto total de la campaña | Suma de todos los días |
| `revenue` | Ingresos de la campaña | Suma de todos los días |
| `ctr` | Click-through rate de la campaña | `clicks / impressions`, sobre los totales |
| `cpc` | Costo por click de la campaña | `spend / clicks`, sobre los totales |
| `cpa` | Costo por conversión de la campaña | `spend / conversions`, sobre los totales. Vacío si no hubo conversiones |
| `roas` | Retorno del gasto de la campaña | `revenue / spend`, sobre los totales |

## Celdas vacías

Solo aparecen en las métricas, cuando no se pueden calcular porque habría que dividir por 0 (por
ejemplo, el CPA de un día sin conversiones). **Nunca significan 0.** Las filas a las que les faltaba
algún número se descartaron: están en `rejected_rows` del Sheet de revisión, con el motivo.
