# Pipeline de performance de campañas

Pipeline en Python que toma el CSV de performance diaria de campañas tal como sale de las plataformas,
lo limpia, calcula CTR, CPC, CPA y ROAS, arma un resumen por campaña y lo publica en Google Sheets.
Corre desde GitHub Actions al subir datos nuevos, a mano y todos los lunes a las 9:00 de Argentina.

**Resultado publicado:** [Google Sheet (lectura)](https://docs.google.com/spreadsheets/d/1fSj01Pwtsq3kPatY8jxhsvIrMPL7OUkeMafvnGNybZ8/edit)

| Tab | Contenido |
|---|---|
| `clean_data` | Data limpia: una fila por campaña y día, con sus métricas |
| `campaign_summary` | Una fila por campaña: totales y métricas recalculadas sobre los totales |

**Revisión de la limpieza:** [Google Sheet (lectura)](https://docs.google.com/spreadsheets/d/1riiICt4jCo14nDha1lX9h72UQN_Sf_pY5PiILsG72cw/edit)

| Tab | Contenido |
|---|---|
| `rejected_rows` | Cada fila descartada tal como venía, su línea en el archivo original y el motivo |
| `corrected_rows` | Cada fila corregida tal como venía y la corrección hecha |

**Análisis del archivo del caso:** qué problemas tenía el CSV entregado, cuántas filas afectó cada uno
y los números de esta carga, en [docs/analisis-del-caso.md](docs/analisis-del-caso.md).

## Cómo funciona

```
data/campaigns.csv → validar → limpiar → unir por campaña y día → métricas → resumen → control → Google Sheets
```

1. **Validar:** el archivo tiene las columnas esperadas y al menos una fila.
2. **Limpiar:** normaliza formatos, corrige lo corregible y descarta lo imposible.
3. **Unir:** deja una sola fila por campaña, día y moneda.
4. **Métricas:** CTR, CPC, CPA y ROAS por fila.
5. **Resumen:** totales por campaña y métricas recalculadas sobre esos totales.
6. **Control:** si el archivo vino roto, no publica y el Sheet conserva los datos anteriores.
7. **Publicar:** reemplaza el contenido de los Sheets; correrlo dos veces no duplica datos.

## Contenido del repo

| Archivo | Qué es |
|---|---|
| `pipeline.py` | Todo el pipeline |
| `data/campaigns.csv` | El CSV que se procesa (hoy, el original del caso) |
| `requirements.txt` | Dependencias con versión fija (pandas, gspread, google-auth) |
| `requirements-dev.txt`, `pytest.ini`, `tests/` | Los tests de cada regla y lo necesario para correrlos. `tests/fixtures/` tiene una copia fija del CSV del caso |
| `.python-version` | Python 3.14, la misma versión en local y en GitHub Actions |
| `.github/workflows/pipeline.yml` | La ejecución en GitHub Actions |
| `docs/analisis-del-caso.md` | Los problemas del archivo del caso y sus números |

Cada corrida genera además `output/` (no se versiona): las tablas en CSV, `rejected_rows.csv` y
`corrected_rows.csv`.

## Cómo correrlo

```bash
python -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python -m pytest                   # tests: no publican nada ni necesitan credenciales
python pipeline.py --no-publish    # procesa data/campaigns.csv y deja el resultado en output/
python pipeline.py --input otro.csv --no-publish
```

Para publicar en Google Sheets:

1. Una cuenta de servicio de Google Cloud con las APIs de Sheets y Drive habilitadas, y su clave JSON.
2. Los Sheets compartidos como **Editor** con el email de esa cuenta de servicio.
3. Estas variables de entorno, y `python pipeline.py`:

| Variable | Qué es |
|---|---|
| `SPREADSHEET_ID` | El ID del Sheet de resultados (la parte de la URL entre `/d/` y `/edit`) |
| `REVIEW_SPREADSHEET_ID` | Opcional: el ID del Sheet de revisión. Sin él, la revisión queda solo en `output/` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Ruta al JSON de la cuenta de servicio (en una computadora) |
| `GOOGLE_CREDENTIALS` | El contenido de ese JSON (en GitHub Actions, como secreto del repo) |

### En GitHub Actions

- **Cuándo corre:** al subir un CSV nuevo a `data/`, a mano (*Actions → Pipeline de campañas → Run
  workflow*) y todos los lunes a las 9:00 de Argentina.
- **Qué hace:** instala las dependencias, corre los tests y, **solo si pasan**, el pipeline. Una
  corrida a la vez, con un máximo de 10 minutos.
- **Qué deja:** el reporte de la corrida como tabla en la página de la ejecución, los avisos como
  anotaciones, y `output/` como adjunto descargable.
- **Configuración:** el secreto `GOOGLE_CREDENTIALS` en *Settings → Secrets and variables → Actions*.
  Los IDs de los dos Sheets están en el workflow.
- GitHub desactiva los workflows programados de un repo público tras 60 días sin actividad; se
  reactivan con un click en la pestaña Actions.

### Cómo actualizar los datos

El pipeline lee siempre `data/campaigns.csv`. Para procesar datos nuevos, se reemplaza ese archivo
**con el mismo nombre**:

- **Desde la web de GitHub:** carpeta `data` → *Add file → Upload files* → arrastrar el CSV nuevo
  llamado `campaigns.csv` → *Commit changes*.
- **Desde git:** copiar el archivo en `data/campaigns.csv`, commit y push a `main`.

Al llegar el archivo nuevo, el workflow corre solo. Si el archivo está roto, la corrida termina en
rojo con el motivo, el Sheet de resultados conserva los datos anteriores y el Sheet de revisión
muestra qué se descartó o corrigió.

Se aceptan las exportaciones más comunes: separadas por coma o por punto y coma (Excel en español),
en UTF-8 o en Latin-1 (Excel en Windows). Las columnas tienen que llamarse igual; el orden, las
mayúsculas y las columnas de más no importan.

## Reglas de limpieza

**Vacío no es cero.** Un 0 es un dato ("medimos y no hubo"); un vacío es su falta ("no sabemos").
Convertir el vacío en 0 inventaría un dato. Por eso conversiones o revenue vacíos no descartan la fila
(impresiones, clicks y gasto siguen sirviendo) y se mantienen vacíos de punta a punta.

| Situación | Qué hace | Por qué |
|---|---|---|
| Fechas `AAAA-MM-DD` o `DD/MM/AAAA` | Las lleva a fecha | Es el mismo dato en otro formato |
| Espacios sobrantes en textos | Los recorta | Si no, la misma campaña parece dos |
| Canal escrito de muchas formas | Lo reconoce por palabra clave: "google"/"youtube" → Google Ads; "meta"/"facebook"/"instagram" → Meta Ads; "linkedin" → LinkedIn Ads | Una variante nueva (`Google Ads Search`) se reconoce sola; solo una plataforma nueva de verdad requiere agregar una línea |
| Canal desconocido | Lo deja como vino y avisa | La fila tiene datos válidos: descartarla haría desaparecer gasto |
| Canal distinto al del nombre de la campaña (`AR_CONV_Meta_Q4`) | Avisa | Control cruzado: algo está mal cargado |
| Números con `$`, `USD`, coma o punto (`"$ 182,41"`, `"1.234,5"`) | Los convierte a número | El último separador es decimal si lo siguen 1 o 2 dígitos; si no, es de miles |
| Número entre paréntesis (`"(182.41)"`) | Lo lee como negativo | Convención contable |
| Texto que no es un número (`1e3`, `n/a`) | Lo deja vacío y avisa | No se adivina |
| Gasto negativo | Lo pasa a positivo y lo registra en `corrected_rows` | El gasto no puede ser negativo: se asume un error de signo y se conserva la fila |
| Fila idéntica a otra (ya normalizada) | Descarta la copia | Es un duplicado: sumaría dos veces lo mismo |
| Más clicks que impresiones | Descarta la fila | Un click requiere una impresión |
| Impresiones, clicks, conversiones o revenue negativos | Descarta la fila | Valor imposible |
| Fecha ilegible o futura | Descarta la fila | Un día que no pasó no puede tener performance (`2062-09-17` es un tipeo) |
| Sin impresiones, clicks o gasto | Descarta la fila | No se puede calcular casi nada |
| Cantidad con decimales (12,5 clicks) | La deja vacía y avisa | No se redondea a escondidas |

Toda fila descartada queda en `rejected_rows` y toda fila corregida en `corrected_rows`, tal como
venían en el archivo, para poder auditar qué se sacó o cambió sin confiar en el script a ciegas.

## Una fila por campaña y día

**La clave es fecha + `campaign_id` + moneda.** Si para la misma campaña y el mismo día llegan varias
filas **distintas**, se interpretan como **partes** del día (por ejemplo, grupos de anuncios) y se
suman. Si son **iguales en todo**, son un duplicado y se descarta la copia. La moneda está en la
clave porque sumar dólares con pesos da un número sin sentido. Nombre, canal, país y objetivo no
están en la clave: son atributos fijos de la campaña, y si uno viniera escrito distinto un día, no
debe partir la fila; se usa el valor más frecuente y el log avisa.

**Al unir, un vacío deja el total vacío.** Si una de las partes del día tiene conversiones vacías, el
total del día queda vacío: sumar solo lo conocido daría un total más bajo que el real, presentado como
si estuviera completo.

**Los montos sumados se redondean al centavo**, para sacar el ruido de sumar decimales
(`486.29999999999995`). Las métricas no se redondean: el formato se aplica al publicar.

## Métricas

**CTR = clicks / impressions · CPC = spend / clicks · CPA = spend / conversions · ROAS = revenue /
spend.** Una sola función las calcula por fila y sobre los totales del resumen, así las fórmulas no
pueden quedar distintas entre las dos tablas.

**Si el denominador es 0 o falta un valor, la métrica queda vacía.** No 0, porque un CPA de 0 diría
que las conversiones salieron gratis. No infinito, porque no se puede sumar, graficar ni comparar. El 0
en el numerador sí es válido: revenue 0 da ROAS 0 (se invirtió y no volvió nada). La métrica vacía
no pierde la fila: queda para que el analista la interprete.

**El resumen recalcula las métricas sobre los totales**, nunca promediando las de cada día: el
promedio le da el mismo peso a un día de USD 10 que a uno de USD 1.000.

**En el resumen, CPA y ROAS usan solo los días que tienen el dato.** Si una campaña tiene días con
conversiones vacías, dividir el gasto total por las conversiones conocidas contaría el gasto de esos
días como si no hubiera traído nada, y el CPA saldría peor por un dato que falta. Por eso el CPA usa
el gasto de los días con conversiones conocidas, y el ROAS el de los días con revenue conocido. En esas
campañas `spend / conversions` de la tabla no da exactamente el `cpa` mostrado, porque `spend` es el
total; el log de cada corrida dice qué parte del gasto se usó.

**El objetivo de la campaña sirve para leer las métricas, no para calcularlas.** Una campaña de
Awareness no se juzga por su CPA, pero el CPA se calcula igual que en las demás: si la regla cambiara
según el objetivo, la misma columna significaría cosas distintas según la fila.

## Calidad

- **El archivo se valida antes de procesarlo.** Si falta una columna, está vacío o solo tiene el
  encabezado, frena con un mensaje que dice qué pasó (`le faltan columnas: ['spend']`).
- **Un archivo roto no se publica.** Si no queda ninguna fila válida, si se descarta más del 20 % de
  las filas o si hay que corregir el gasto en más del 20 % (señal de que cambió cómo exporta la
  plataforma), no toca el Sheet de resultados y la corrida termina con error: el Sheet conserva los
  datos anteriores y GitHub avisa por mail. La revisión se publica igual, porque es justo lo que hay
  que mirar.
- **Tests antes de publicar.** Cubren cada regla y el archivo del caso de punta a punta. Usan una
  copia fija del CSV del caso, no `data/campaigns.csv`, que cambia con cada carga: los tests prueban
  las reglas; el control de calidad, el archivo de cada semana.
- **Al Sheet se escribe el valor tal cual** (modo `RAW`): un texto que empiece con `=` no se ejecuta
  como fórmula. Las fechas van como fecha de verdad, con formato `AAAA-MM-DD`.
- **Los montos se muestran sin símbolo de moneda:** `$` se confunde con pesos; la moneda la dice la
  columna `currency`. El CTR se muestra como porcentaje y los montos y el ROAS con dos decimales.

## Supuestos y riesgos

- **Cada CSV trae el histórico completo**, no solo los días nuevos. Por eso cada corrida reemplaza el
  contenido de los Sheets.
- **Las filas distintas de un mismo día son partes, no correcciones.** Si fueran versiones corregidas
  del mismo dato, sumarlas lo contaría dos veces. Es lo primero que validaría con quien conoce la
  exportación.
- **El gasto negativo es un error de signo.** Si fuera un reembolso o un ajuste, pasarlo a positivo
  sumaría gasto que no existió; cada caso queda en `corrected_rows` para validarlo.
- **`DD/MM/AAAA` es día/mes.** Un archivo solo con fechas ambiguas (`05/09`) necesitaría confirmar el
  formato de origen.
- **Los umbrales del 20 %** son un criterio, no un dato: se ajustan en una línea
  (`MAX_DISCARDED_SHARE`, `MAX_CORRECTED_SHARE`).

## Mejoras para escalar

- **Fuente de datos automática:** en vez de subir el CSV al repo, leerlo de una carpeta de Google
  Drive o de la API de cada plataforma (Google Ads, Meta, LinkedIn). Solo cambiaría `load_raw`.
- **Archivos incrementales:** si las plataformas exportaran solo los días nuevos, guardar cada archivo
  y combinarlos por fecha y campaña, quedándose con la versión más reciente de cada día.
- **Publicación atómica:** hoy cada tab se borra y después se escribe; si la conexión se corta en el
  medio, la tab puede quedar vacía hasta la próxima corrida. Escribiría en una tab temporal, la
  cambiaría por la vieja solo cuando esté completa y activaría los reintentos de gspread.
- **Historial:** guardar cada corrida con su fecha de carga en una base (BigQuery, por ejemplo) para
  comparar semanas, con el Sheet como vista.
