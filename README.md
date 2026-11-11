# Winclap — pipeline de performance de campañas

Pipeline en Python que toma el CSV de performance diaria de campañas tal como sale de las plataformas,
lo limpia, calcula CTR, CPC, CPA y ROAS, arma un resumen por campaña y lo publica en Google Sheets.
Corre desde GitHub Actions a mano y todos los lunes.

**Resultado publicado:** [Google Sheet (lectura)](https://docs.google.com/spreadsheets/d/1fSj01Pwtsq3kPatY8jxhsvIrMPL7OUkeMafvnGNybZ8/edit)

| Tab | Contenido |
|---|---|
| `clean_data` | Data limpia: una fila por campaña y día, con sus métricas |
| `campaign_summary` | Una fila por campaña: totales y métricas recalculadas sobre los totales |

```
data/campaigns.csv → validar → limpiar → unir por campaña y día → métricas → resumen → control → Google Sheets
     214 filas                  202 válidas       145 filas                    12 filas
```

## Contenido del repo

| Archivo | Qué es |
|---|---|
| `pipeline.py` | Todo el pipeline, en funciones chicas en el orden de arriba |
| `data/campaigns.csv` | El CSV original del caso, sin tocar |
| `requirements.txt` | Dependencias con versión fija (pandas, gspread, google-auth) |
| `requirements-dev.txt`, `pytest.ini`, `tests/` | Los tests de cada regla y lo necesario para correrlos |
| `.python-version` | Python 3.14, la misma versión en local y en GitHub Actions |
| `.github/workflows/pipeline.yml` | La ejecución en GitHub Actions |

Cada corrida genera además `output/` (no se versiona): las dos tablas en CSV, `rejected_rows.csv`
(cada fila descartada tal como venía, su línea en el archivo original y el motivo) y
`corrected_rows.csv` (cada fila corregida, tal como venía, y la corrección hecha). Esas dos últimas
se publican también en un **Sheet de revisión** aparte, si está configurado.

## Cómo correrlo

```bash
python -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python -m pytest                   # 52 tests: no publican nada ni necesitan credenciales
python pipeline.py --no-publish    # procesa data/campaigns.csv y deja el resultado en output/
python pipeline.py --input otro.csv --no-publish
```

Para publicar en un Google Sheet:

1. Una cuenta de servicio de Google Cloud con las APIs de Sheets y Drive habilitadas, y su clave JSON.
2. El Sheet compartido como **Editor** con el email de esa cuenta de servicio.
3. Dos variables de entorno, y `python pipeline.py`:

| Variable | Qué es |
|---|---|
| `SPREADSHEET_ID` | El ID del Sheet (la parte de la URL entre `/d/` y `/edit`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Ruta al JSON de la cuenta de servicio (en una computadora) |
| `GOOGLE_CREDENTIALS` | El contenido de ese JSON (en GitHub Actions, como secreto del repo) |
| `REVIEW_SPREADSHEET_ID` | Opcional: el ID de otro Sheet para las filas descartadas y corregidas |

Cada corrida **reemplaza** el contenido de las dos tabs: correrla dos veces no duplica datos.

### En GitHub Actions

- **Cuándo corre:** a mano (*Actions → Pipeline de campañas → Run workflow*) y todos los lunes a las
  9:00 de Argentina.
- **Qué hace:** instala las dependencias, corre los tests y, **solo si pasan**, el pipeline. Una
  corrida a la vez, con un máximo de 10 minutos.
- **Qué deja:** el reporte de la corrida como tabla en la página de la ejecución, los avisos como
  anotaciones, y `output/` como adjunto descargable.
- **Configuración:** el secreto `GOOGLE_CREDENTIALS` en *Settings → Secrets and variables → Actions*.
  El ID del Sheet está en el workflow.
- GitHub desactiva los workflows programados de un repo público tras 60 días sin actividad; se
  reactivan con un click en la pestaña Actions.

## Problemas encontrados en los datos

| Problema | Filas | Qué se hizo |
|---|---|---|
| Fechas en dos formatos (`2026-09-17` y `17/09/2026`) | 25 | Todo a fecha. Con barras es día/mes: `17/09` no admite otra lectura |
| Espacios sobrantes en el nombre de campaña | 9 | Se recortan |
| El canal escrito de 8 formas (`GOOGLE ADS`, `google ads`, `meta`, `Facebook Ads`…) | todas | Se reconoce por palabra clave → `Google Ads`, `Meta Ads`, `LinkedIn Ads` |
| Gasto como texto con formato de moneda (`"$ 182,41"`) | 9 | Se convierte a número |
| Duplicados exactos | 6 | Se descartan |
| Gasto negativo | 5 | Se pasa a positivo (supuesto: error de signo). 4 quedan; la quinta se descarta igual por más clicks que impresiones |
| Más clicks que impresiones (ej. 114.055 impresiones, 114.102 clicks) | 6 | Se descarta la fila: un click requiere una impresión |
| Conversiones o revenue vacíos | 6 y 5 | La fila se queda; el valor queda **vacío, no 0** |
| Varias filas de la misma campaña el mismo día, con números distintos | 47 campañas-día | Se unen en una fila, sumando |
| Dos campañas distintas con el mismo nombre (C1001 y C1006) | — | Todo se agrupa por `campaign_id`, nunca por nombre |

Resultado: 214 filas → 6 duplicados y 6 inválidas descartados (12, el 5,6 %) → **202 filas
válidas** (4 con el gasto corregido) → **145 filas** de campaña y día → **12 campañas**.

## Decisiones y por qué

### Limpieza

**Vacío no es cero.** Un 0 es un dato ("medimos y no hubo"); un vacío es su falta ("no sabemos").
Convertir el vacío en 0 inventaría un dato: diría, por ejemplo, que 12 conversiones no generaron
revenue. Por eso conversiones o revenue vacíos no descartan la fila (impresiones, clicks y gasto
siguen sirviendo) y se mantienen vacíos de punta a punta.

**El canal se reconoce por palabra clave**, no por una lista de variantes exactas: "google" o
"youtube" → Google Ads; "meta", "facebook" (el nombre anterior de Meta Ads) o "instagram" → Meta Ads;
"linkedin" → LinkedIn Ads. Así una variante nueva como `Google Ads Search` se reconoce sola. Un canal
desconocido no frena el pipeline: queda como vino y el log avisa. Además se compara con la plataforma
que dice el nombre de la campaña (`AR_CONV_Meta_Q4` → Meta) y se avisa si no coinciden; hoy coinciden
en todas las filas.

**Números con coma o punto.** El último separador es decimal si lo siguen 1 o 2 dígitos; si no, son de
miles: `"$ 182,41"` → 182.41 · `"1.234,5"` → 1234.5 · `"1,234.50"` → 1234.5 · `"114.055"` → 114055.
Entre paréntesis es negativo, como en contabilidad: `"(182.41)"` → -182.41 (y, como todo gasto
negativo, después se pasa a positivo). Junto al número solo se acepta un símbolo o código de moneda (`$`, `US$`, `USD`,
`€`); cualquier otra cosa (`1e3`, `n/a`) deja el valor vacío con un aviso en vez de adivinarlo.

**Los duplicados se buscan después de normalizar.** Así se detectan también dos copias de una fila que
solo difieren en el formato de la fecha o en espacios.

**El gasto negativo se pasa a positivo.** Un gasto no puede ser negativo, así que se asume que el
monto es correcto y el signo es un error de carga: se corrige en vez de perder la fila. Es un
supuesto: si el negativo fuera, por ejemplo, un reembolso, habría que restarlo. Cada corrección queda
en `corrected_rows`, con la fila original y el cambio (`spend -328.33 pasado a positivo`), para que
se pueda revisar. Se corrige antes de buscar duplicados, así dos copias de la misma fila siguen
siendo iguales.

**Se descarta lo imposible, no lo raro.** Más clicks que impresiones (un click requiere una
impresión), impresiones, clicks, conversiones o revenue negativos, fecha ilegible o falta de
impresiones, clicks o gasto. Una cantidad con decimales (12,5 clicks) queda
vacía con un aviso en vez de redondearse a escondidas. Las reglas cubren casos que este archivo no
tiene, pensando en las cargas de cada semana.

### Clave primaria y unión

**Una fila por campaña y día.** Sin esto la tabla no tiene clave primaria: "C1004 el 4/9" podía ser
dos o tres registros. Las filas repetidas de un mismo día tienen números muy distintos entre sí
(8.905 contra 23.289 impresiones), así que se interpretan como **partes** del día —por ejemplo, grupos
de anuncios— y se suman. En cambio, si dos filas son iguales en todo, son un **duplicado** y se
descarta la copia. Comprobación: el gasto y las impresiones totales son los mismos antes y después
de unir.

**La clave es fecha + `campaign_id` + moneda.** La moneda está en la clave porque sumar dólares con
pesos da un número sin sentido (hoy todo es USD). Nombre, canal, país y objetivo **no** están en la
clave: son atributos fijos de la campaña, y si un día vinieran escritos distinto (`AR_CONV_Meta_Q4` y
`AR_CONV_Meta_Q4_v2`) partirían la fila de ese día en dos. Se usa el valor más frecuente de cada
campaña (ante un empate, el primero alfabéticamente) y el log avisa con todas las variantes.

**Al unir, un vacío deja el total vacío.** Si una de las filas del día tiene conversiones vacías, el
total del día queda vacío. Sumar solo lo conocido daría, para C1004 el 4/9, 9 conversiones sobre
USD 2.564 de gasto, cuando USD 2.276 de ese gasto no tienen dato: un CPA falso que parece completo.

**Los montos sumados se redondean al centavo.** Sumar decimales deja ruido (`486.29999999999995`). Las
métricas no se redondean: el formato se aplica recién al publicar.

### Métricas

**CTR = clicks / impressions · CPC = spend / clicks · CPA = spend / conversions · ROAS = revenue /
spend.** Una sola función las calcula por fila y sobre los totales del resumen, así las fórmulas no
pueden quedar distintas entre las dos tablas.

**Si el denominador es 0 o falta un valor, la métrica queda vacía.** No 0, porque un CPA de 0 diría
que las conversiones salieron gratis cuando no hubo ninguna. No infinito, porque no se puede sumar,
graficar ni comparar. El 0 en el numerador sí es válido: revenue 0 da ROAS 0 (se invirtió y no volvió
nada). Resultado: CPA vacío en 12 filas (6 sin dato de conversiones y 6 con 0 conversiones) y ROAS
vacío en 5.

**El resumen recalcula las métricas sobre los totales**, nunca promediando las de cada día: el
promedio le da el mismo peso a un día de USD 10 que a uno de USD 1.000.

**En el resumen, CPA y ROAS usan solo los días que tienen el dato.** 6 de las 12 campañas tienen algún
día con conversiones o revenue vacío. Dividir el gasto total por las conversiones conocidas contaría el
gasto de los días sin dato como si no hubiera traído nada: en C1004 el CPA daría USD 15,29 en vez de
USD 10,07, un 52 % peor por un dato que falta y no por la campaña. A diferencia de la unión dentro de
un día, acá sí se puede separar qué gasto corresponde a qué resultado, porque cada día es una unidad
con su propio gasto. La regla es la misma para todas las campañas, sea cual sea su objetivo.
Consecuencia: en esas 6 campañas `spend / conversions` de la tabla no da exactamente el `cpa`
mostrado, porque `spend` es el total. El log de cada corrida dice qué parte del gasto se usó:

| Campaña | Gasto usado para el CPA | Gasto usado para el ROAS |
|---|---|---|
| C1002 | 100 % | 92 % |
| C1004 | 66 % | 100 % |
| C1005 | 100 % | 98 % |
| C1006 | 68 % | 100 % |
| C1009 | 84 % | 96 % |
| C1010 | 100 % | 97 % |

**El objetivo de la campaña sirve para leer las métricas, no para calcularlas.** Una campaña de
Awareness no se juzga por su CPA (C1006 tiene un CPA de USD 205,85 y es esperable), pero el CPA se
calcula igual que en las demás: si la regla cambiara según el objetivo, la misma columna significaría
cosas distintas según la fila.

### Calidad y robustez

**El archivo se controla antes de procesarlo.** Si falta una columna, el archivo está vacío o solo tiene
el encabezado, el pipeline frena con un mensaje que dice qué pasó (`le faltan columnas: ['spend']`) en
vez de fallar más adelante con un error técnico. Los nombres de columna se aceptan con mayúsculas o
espacios, y las columnas de más se ignoran con un aviso.

**Un archivo roto no se publica.** Si no quedó ninguna fila válida o se descartó más del 20 % de las
filas, el pipeline no toca el Sheet de resultados y la corrida termina con error: el Sheet conserva
los datos de la corrida anterior, que siguen siendo correctos, y GitHub avisa por mail. Hoy se
descarta el 5,6 %; el 20 % deja margen para un mal día sin dejar pasar, por ejemplo, una columna
entera mal exportada. La revisión (descartadas y corregidas) se publica igual, porque es justo lo que
hay que mirar para entender por qué frenó.

**Lo que se descarta o corrige queda registrado, en un Sheet de revisión aparte.** `rejected_rows`
guarda cada fila descartada tal como venía, con su línea en el archivo original y el motivo
(`más clicks que impresiones`, `duplicado exacto de la línea 6`; si rompe varias reglas, aparecen
todas). `corrected_rows` guarda cada fila corregida, tal como venía, con la corrección hecha.
Cualquiera puede auditar qué se sacó o cambió sin confiar en el script a ciegas. Va en un Sheet
aparte para que el de resultados tenga solo los datos que se usan.

**Tests antes de publicar.** 52 tests cubren cada regla —lectura de números y fechas, canales,
duplicados, inválidas, unión, clave primaria, monedas, métricas, resumen, control de calidad,
publicación— más el archivo real de punta a punta. En GitHub Actions corren antes del pipeline: si una
regla deja de cumplirse, la corrida frena y el Sheet no se toca. Para comprobar que los tests sirven,
se rompió a propósito cada regla principal y los tests fallaron en todos los casos.

### Publicación

**Al Sheet se escribe el valor tal cual** (modo `RAW`): Google no interpreta nada, así un nombre de
campaña que empiece con `=` no se ejecuta como fórmula y ningún texto se convierte solo en fecha o
número según el idioma de la planilla. Las fechas se mandan como fecha de verdad (se ordenan y
filtran como fechas) con formato `AAAA-MM-DD`.

**Los montos se muestran sin símbolo de moneda.** `$` se confunde con pesos y un símbolo fijo estaría
mal el día que llegue una fila en otra moneda: la moneda la dice la columna `currency`. El CTR se
muestra como porcentaje y los montos y el ROAS con dos decimales.

## Supuestos y riesgos

- **Las filas repetidas de un mismo día son partes, no correcciones.** Si fueran versiones corregidas
  del mismo dato, sumarlas lo contaría dos veces. Los números muy distintos apoyan que son partes,
  pero el archivo no lo confirma: es lo primero que validaría con quien conoce la exportación.
- **El formato `DD/MM/AAAA`** se asume día/mes porque hay fechas como `17/09` que no admiten otra
  lectura. Un archivo solo con fechas ambiguas (`05/09`) necesitaría confirmar el formato de origen.
- **El gasto negativo es un error de signo.** Si fuera un reembolso o un ajuste, pasarlo a positivo
  sumaría gasto que no existió; las 4 filas corregidas suman USD 2.085,86 y quedan listadas en
  `corrected_rows` para validarlo.
- **El umbral del 20 %** es un criterio, no un dato: se ajusta en una línea (`MAX_DISCARDED_SHARE`).

## Mejoras para escalar

**La fuente de datos.** El pipeline lee el CSV del repo, así que la corrida semanal vuelve a publicar
el mismo archivo. Es lo que pide el caso; en producción la entrada sería dinámica: un archivo nuevo en
una carpeta de Google Drive o, mejor, la API de cada plataforma (Google Ads, Meta, LinkedIn). Solo
cambiaría `load_raw`; el resto ya está preparado para datos nuevos cada semana.

**Publicación atómica.** Hoy cada tab se borra y después se escribe. Si la conexión con Google se
corta justo en el medio, la tab puede quedar vacía o a medias hasta la próxima corrida. Con un Sheet
chico y una corrida semanal el riesgo es bajo; con más datos o más consumidores, escribiría en una tab
temporal, reemplazaría la vieja solo cuando la nueva está completa, y activaría los reintentos
automáticos de gspread para cuando Google responde "demasiadas solicitudes".

**Historial.** Hoy el Sheet tiene solo la última versión. Si los consumidores necesitaran comparar
semanas, guardaría cada corrida con su fecha de carga en una base (BigQuery, por ejemplo) y el Sheet
quedaría como vista.
