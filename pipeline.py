"""Pipeline de performance de campañas.

Lee el CSV tal como sale de las plataformas, lo limpia, calcula métricas y publica el resultado
en Google Sheets. Las decisiones de limpieza están explicadas en el README.

Uso: python pipeline.py [--no-publish]
"""

import argparse
import io
import json
import logging
import os
import re
from pathlib import Path

import gspread
import pandas as pd

log = logging.getLogger("pipeline")

ROOT = Path(__file__).parent
RAW_CSV = ROOT / "data" / "campaigns.csv"
# Copias locales de lo que va a cada tab, para revisar sin abrir los Sheets.
DAILY_CSV = ROOT / "output" / "campaigns_daily.csv"
SUMMARY_CSV = ROOT / "output" / "campaign_summary.csv"
REJECTED_CSV = ROOT / "output" / "rejected_rows.csv"
CORRECTED_CSV = ROOT / "output" / "corrected_rows.csv"

# Sheet de resultados (SPREADSHEET_ID)
DAILY_TAB = "clean_data"
SUMMARY_TAB = "campaign_summary"
# Sheet de revisión (REVIEW_SPREADSHEET_ID): lo que la limpieza sacó o cambió, para auditarlo.
REJECTED_TAB = "rejected_rows"
CORRECTED_TAB = "corrected_rows"

# Si la limpieza descarta más que esto, el archivo está roto y no se publica: el Sheet se queda con
# los datos de la corrida anterior. Hoy se descarta el 5,6 %; el 20 % deja margen para un mal día
# sin dejar pasar un archivo con, por ejemplo, una columna entera mal exportada.
MAX_DISCARDED_SHARE = 0.20
# Lo mismo para las correcciones: unas pocas son errores de carga, pero si hay que corregir muchas
# es que cambió cómo exporta la plataforma (por ejemplo, el gasto en negativo) y alguien tiene que
# mirarlo antes de publicar. Hoy se corrige el 1,9 %.
MAX_CORRECTED_SHARE = 0.20

RAW_COLS = [
    "date", "campaign_id", "campaign_name", "channel", "country", "objective",
    "impressions", "clicks", "spend", "conversions", "revenue", "currency",
]
TEXT_COLS = ["campaign_id", "campaign_name", "channel", "country", "objective", "currency"]
COUNT_COLS = ["impressions", "clicks", "conversions"]
MONEY_COLS = ["spend", "revenue"]
NUMERIC_COLS = COUNT_COLS + MONEY_COLS
METRIC_COLS = ["ctr", "cpc", "cpa", "roas"]

# Clave primaria de la data limpia: una fila por campaña, día y moneda. La moneda va en la clave
# porque sumar dólares con pesos da un número sin sentido; hoy todo es USD.
KEY_COLS = ["date", "campaign_id", "currency"]
# Atributos fijos de cada campaña. No van en la clave: si un día vienen escritos distinto, partirían
# la fila de ese día en dos. Se toma un único valor por campaña (ver campaign_attributes).
CAMPAIGN_ATTRS = ["campaign_name", "channel", "country", "objective"]
OUTPUT_ID_COLS = ["date", "campaign_id", *CAMPAIGN_ATTRS, "currency"]

# Cada plataforma se reconoce por una palabra clave, escriba como escriba el nombre
# ("GOOGLE ADS", "Google Ads Search", "Facebook Ads"...). Una plataforma nueva se agrega acá.
CHANNEL_KEYWORDS = {
    "Google Ads": ["google", "youtube"],
    "Meta Ads": ["meta", "facebook", "instagram"],  # Facebook Ads es el nombre anterior de Meta Ads
    "LinkedIn Ads": ["linkedin"],
}


def load_raw(path: Path) -> pd.DataFrame:
    """Lee el CSV y controla su forma antes de seguir: si no es el archivo esperado, frena con un
    mensaje que dice qué falta, en vez de fallar más adelante con un error que no se entiende.

    Acepta las dos exportaciones más comunes: separado por coma o por punto y coma (Excel en
    español), y codificado en UTF-8 o en Latin-1 (Excel en Windows).
    """
    content = path.read_bytes()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
        log.warning("%s no está en UTF-8: se lee como Latin-1", path.name)
    header = text.split("\n", 1)[0]
    separator = ";" if header.count(";") > header.count(",") else ","
    try:
        # Todo se lee como texto: cada tipo se convierte de forma explícita en normalize().
        raw = pd.read_csv(io.StringIO(text), sep=separator, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        raise SystemExit(f"{path.name} está vacío: no tiene ni el encabezado.")
    except pd.errors.ParserError as error:
        raise SystemExit(f"{path.name} no se puede leer como CSV: {error}")
    raw.columns = raw.columns.str.strip().str.lower()  # 'Spend ' es la misma columna que 'spend'

    missing = [col for col in RAW_COLS if col not in raw.columns]
    if missing:
        raise SystemExit(f"A {path.name} le faltan columnas: {missing}. Llegaron: {list(raw.columns)}.")
    extra = [col for col in raw.columns if col not in RAW_COLS]
    if extra:
        log.warning("Columnas que el pipeline no usa, se ignoran: %s", extra)
    if raw.empty:
        raise SystemExit(f"{path.name} no tiene filas: solo el encabezado.")

    raw = raw[RAW_COLS]
    raw.index = raw.index + 2  # el índice es la línea del archivo (la 1 es el encabezado)
    return raw


def parse_dates(raw: pd.Series) -> pd.Series:
    """Acepta AAAA-MM-DD y DD/MM/AAAA. Lo que no encaja en ninguno queda vacío."""
    iso = pd.to_datetime(raw, format="%Y-%m-%d", errors="coerce")
    day_first = pd.to_datetime(raw, format="%d/%m/%Y", errors="coerce")
    return iso.fillna(day_first)


# Lo único que puede acompañar a un número: un símbolo o un código de moneda de 3 letras.
CURRENCY_MARKS = re.compile(r"(?i)\bUS\$|\b[a-z]{3}\b|[$€£]")


def to_number(text: str) -> float | None:
    """Lee un número escrito con coma o punto, como decimal o como separador de miles.

    El último separador es decimal solo si lo siguen 1 o 2 dígitos (los centavos);
    si no, todos los separadores son de miles:
    '$ 182,41' -> 182.41 · '1.234,5' -> 1234.5 · '1,234.50' -> 1234.5 · '114.055' -> 114055
    Entre paréntesis es negativo, como en contabilidad: '(182.41)' -> -182.41.
    Si queda algo que no es parte de un número ('1e3', 'n/a'), queda vacío: no se adivina.
    """
    digits = CURRENCY_MARKS.sub("", text).replace(" ", "")
    negative = digits.startswith("(") and digits.endswith(")")
    if negative:
        digits = digits[1:-1]
    if not re.fullmatch(r"-?[\d.,]*\d[\d.,]*", digits):
        return None  # vacío, o algo que no es un número
    decimals = re.search(r"[.,](\d{1,2})$", digits)
    if decimals:
        whole = re.sub(r"[.,]", "", digits[: decimals.start()])
        digits = f"{whole}.{decimals.group(1)}"
    else:
        digits = re.sub(r"[.,]", "", digits)
    value = float(digits)
    return -value if negative else value


def parse_numbers(raw: pd.Series) -> pd.Series:
    values = pd.to_numeric(raw.map(to_number), errors="coerce")
    unreadable = values.isna() & raw.str.strip().ne("")
    if unreadable.any():
        log.warning(
            "%s: %d valores que no son números quedan vacíos: %s",
            raw.name, int(unreadable.sum()), sorted(raw[unreadable].unique())[:5],
        )
    return values


def classify_channel(text: str) -> str | None:
    lowered = text.lower()
    for channel, keywords in CHANNEL_KEYWORDS.items():
        if any(word in lowered for word in keywords):
            return channel
    return None


def name_platform(campaign_name: str) -> str | None:
    """La plataforma que dice el nombre: AR_CONV_Meta_Q4 -> Meta Ads."""
    parts = campaign_name.split("_")
    return classify_channel(parts[2]) if len(parts) >= 3 else None


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    """Tipos correctos y valores escritos de una sola forma. No descarta filas."""
    df = raw.copy()
    for col in TEXT_COLS:
        df[col] = df[col].str.strip()

    df["date"] = parse_dates(df["date"].str.strip())

    channel = df["channel"].map(classify_channel)
    unknown = df.loc[channel.isna(), "channel"].unique()
    if len(unknown):
        # Un canal nuevo no frena el pipeline: se conserva tal cual y queda avisado.
        log.warning("Canales sin reconocer, se dejan como vienen: %s", list(unknown))
    df["channel"] = channel.fillna(df["channel"])

    # Control cruzado: el canal tiene que coincidir con la plataforma del nombre de la campaña.
    from_name = df["campaign_name"].map(name_platform)
    mismatch = from_name.notna() & (from_name != df["channel"])
    if mismatch.any():
        log.warning(
            "Canal distinto al del nombre de la campaña en las líneas %s",
            list(df.index[mismatch]),
        )

    for col in COUNT_COLS:
        counts = parse_numbers(df[col])
        fractional = counts.notna() & (counts % 1 != 0)
        if fractional.any():
            # Una cantidad con decimales no se redondea a escondidas: queda vacía y avisada.
            log.warning("%s con decimales, quedan vacías: %d filas", col, int(fractional.sum()))
        df[col] = counts.mask(fractional).astype("Int64")
    for col in MONEY_COLS:
        df[col] = parse_numbers(df[col])
    return df


def invalid_reasons(df: pd.DataFrame) -> pd.DataFrame:
    """Una columna por regla; True donde la fila la rompe."""
    return pd.DataFrame(
        {
            "fecha ilegible": df["date"].isna(),
            # Un día que todavía no pasó no puede tener performance: es un error de tipeo (2062).
            "fecha futura": df["date"] > pd.Timestamp.today().normalize(),
            "sin impresiones, clicks o gasto": df[["impressions", "clicks", "spend"]].isna().any(axis=1),
            "valor negativo": (df[NUMERIC_COLS] < 0).any(axis=1),
            "más clicks que impresiones": df["clicks"] > df["impressions"],
        }
    ).fillna(False)


def duplicate_reasons(df: pd.DataFrame) -> pd.Series:
    """Para cada copia sobrante, la línea de la fila que se conserva. Vacío si no es copia."""
    group = df.groupby(list(df.columns), dropna=False, sort=False).ngroup()
    first_line = df.index.to_series().groupby(group).transform("min")
    copies = df.duplicated()
    return ("duplicado exacto de la línea " + first_line.astype(str)).where(copies)


def correct_negative_spend(df: pd.DataFrame) -> pd.Series:
    """Pasa a positivo el gasto negativo y devuelve, por línea, la corrección hecha.

    Supuesto: el gasto no puede ser negativo, así que el signo es un error de carga y el monto es
    correcto. Se corrige antes de buscar duplicados, así dos copias de la misma fila siguen siendo
    iguales.
    """
    negative = df["spend"].lt(0).fillna(False)
    corrections = "spend " + df.loc[negative, "spend"].astype(str) + " pasado a positivo"
    df.loc[negative, "spend"] = df.loc[negative, "spend"].abs()
    return corrections


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Devuelve la data limpia, las filas descartadas con su motivo, las filas corregidas con la
    corrección hecha y un reporte de conteos."""
    df = normalize(raw)
    report = {"filas leídas": len(df)}
    corrections = correct_negative_spend(df)

    # Se comparan las filas ya normalizadas: así también se detecta un duplicado
    # que solo difiere en el formato de la fecha o en espacios.
    duplicate = duplicate_reasons(df)
    report["duplicados exactos"] = int(duplicate.notna().sum())
    df = df[duplicate.isna()]

    reasons = invalid_reasons(df)
    for reason, hits in reasons.items():
        report[f"inválidas: {reason}"] = int(hits.sum())
    invalid = reasons.apply(lambda row: "; ".join(row.index[row]), axis=1)
    # Una fila puede romper varias reglas: este es el total real, no la suma de las de arriba.
    report["inválidas descartadas"] = int((invalid != "").sum())
    df = df[invalid == ""]

    # Conversiones o revenue vacíos no invalidan la fila: el resto de sus datos sirve.
    report["filas válidas"] = len(df)
    report["con conversiones vacías"] = int(df["conversions"].isna().sum())
    report["con revenue vacío"] = int(df["revenue"].isna().sum())

    reason = pd.concat([duplicate.dropna(), invalid[invalid != ""]])
    rejected = raw.loc[reason.index].assign(reason=reason).sort_index()
    rejected = rejected.rename_axis("source_line").reset_index()

    # Solo las corregidas que siguieron: una corregida y después descartada figura en rejected.
    kept = corrections[corrections.index.isin(df.index)]
    report["gasto negativo pasado a positivo"] = len(kept)
    corrected = raw.loc[kept.index].assign(correction=kept).sort_index()
    corrected = corrected.rename_axis("source_line").reset_index()
    return df, rejected, corrected, report


def campaign_attributes(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Un único nombre, canal, país y objetivo por campaña: el más frecuente en el archivo.

    Si una campaña trae más de un valor, se avisa con todos los que trajo. Ante un empate gana el
    primero en orden alfabético, para que el resultado no dependa del orden de las filas.
    """
    attrs = df.groupby("campaign_id")[CAMPAIGN_ATTRS].agg(lambda values: values.mode().iloc[0])
    variants = df.groupby("campaign_id")[CAMPAIGN_ATTRS].nunique()
    inconsistent = variants[variants.gt(1).any(axis=1)]
    for campaign_id, counts in inconsistent.iterrows():
        rows = df[df["campaign_id"] == campaign_id]
        for col in counts.index[counts.gt(1)]:
            log.warning(
                "%s tiene más de un %s: %s. Se usa '%s'",
                campaign_id, col, sorted(rows[col].unique()), attrs.loc[campaign_id, col],
            )
    return attrs, len(inconsistent)


def merge_same_day(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Una fila por campaña, día y moneda, sumando las filas que comparten la clave.

    Regla estricta: si alguna de las filas sumadas tiene un valor vacío, el total queda vacío.
    Sumar solo las partes conocidas daría un total más bajo que el real, presentado como completo.
    """
    attrs, inconsistent = campaign_attributes(df)
    grouped = df.groupby(KEY_COLS, dropna=False)
    merged = grouped[NUMERIC_COLS].sum(skipna=False)
    merged[MONEY_COLS] = merged[MONEY_COLS].round(2)  # 486.29999999999995 -> 486.3, ruido de sumar
    merged = merged.reset_index().join(attrs, on="campaign_id")
    merged = merged[OUTPUT_ID_COLS + NUMERIC_COLS]

    report = {
        "campañas con atributos inconsistentes": inconsistent,
        "filas por campaña y día": len(merged),
        "de ellas, unidas de varias filas": int((grouped.size() > 1).sum()),
        "con conversiones vacías tras unir": int(merged["conversions"].isna().sum()),
        "con revenue vacío tras unir": int(merged["revenue"].isna().sum()),
    }
    return merged, report


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divide fila a fila. Si el denominador es 0 o falta alguno de los dos valores, queda vacío.

    No se usa 0 en esos casos: un CPA de 0 diría que las conversiones salieron gratis.
    """
    numerator = numerator.astype("Float64")
    denominator = denominator.astype("Float64")
    denominator = denominator.mask(denominator.eq(0).fillna(False))
    return numerator / denominator


def add_metrics(
    df: pd.DataFrame, spend_for_cpa: str = "spend", spend_for_roas: str = "spend"
) -> pd.DataFrame:
    """CTR, CPC, CPA y ROAS. Se usa igual por fila y sobre los totales del resumen.

    El resumen pasa otro gasto para CPA y ROAS: el de los días que tienen el dato (ver summarize).
    """
    return df.assign(
        ctr=safe_divide(df["clicks"], df["impressions"]),
        cpc=safe_divide(df["spend"], df["clicks"]),
        cpa=safe_divide(df[spend_for_cpa], df["conversions"]),
        roas=safe_divide(df["revenue"], df[spend_for_roas]),
    )


def summarize(daily: pd.DataFrame) -> pd.DataFrame:
    """Una fila por campaña: totales y métricas recalculadas sobre esos totales.

    Días con conversiones o revenue vacío: CPA y ROAS se calculan solo con el gasto de los días
    que tienen ese dato. Si no, el gasto de un día sin dato se dividiría por resultados de otros
    días y la métrica saldría peor de lo que es. Los totales de conversiones y revenue suman lo
    conocido; si una campaña no tiene ningún dato, quedan vacíos.

    Ese gasto base queda en la tabla (spend_with_conversions, spend_with_revenue) para que quien
    la use pueda rehacer cada métrica con columnas visibles, sin conocer esta regla.
    """
    # Los atributos ya son únicos por campaña (merge_same_day): agruparlos no parte ninguna fila.
    campaign_cols = [col for col in OUTPUT_ID_COLS if col != "date"]
    with_known = daily.assign(
        spend_with_conversions=daily["spend"].where(daily["conversions"].notna()),
        spend_with_revenue=daily["spend"].where(daily["revenue"].notna()),
    )
    money = MONEY_COLS + ["spend_with_conversions", "spend_with_revenue"]
    totals = (
        with_known.groupby(campaign_cols, dropna=False)[COUNT_COLS + money]
        .sum(min_count=1)
        .reset_index()
    )
    totals[money] = totals[money].round(2)  # los montos sumados, sin ruido de decimales

    incomplete = totals[
        totals["spend_with_conversions"].lt(totals["spend"])
        | totals["spend_with_revenue"].lt(totals["spend"])
    ]
    for row in incomplete.itertuples():
        log.info(
            "%s: CPA sobre el %.0f%% del gasto, ROAS sobre el %.0f%% (días sin dato)",
            row.campaign_id,
            100 * row.spend_with_conversions / row.spend,
            100 * row.spend_with_revenue / row.spend,
        )

    summary = add_metrics(totals, "spend_with_conversions", "spend_with_revenue")
    # Cada base al lado de lo que divide: spend_with_conversions junto a conversions, etc.
    order = campaign_cols + [
        "impressions", "clicks", "spend",
        "conversions", "spend_with_conversions", "revenue", "spend_with_revenue",
    ] + METRIC_COLS
    return summary[order]


def quality_gate(report: dict) -> list[str]:
    """Motivos para no publicar. Vacía si los datos se pueden publicar."""
    read, valid = report["filas leídas"], report["filas válidas"]
    if valid == 0:
        return [f"no quedó ninguna fila válida de {read} leídas"]
    problems = []
    discarded = (read - valid) / read
    if discarded > MAX_DISCARDED_SHARE:
        problems.append(
            f"se descartó el {discarded:.0%} de las filas ({read - valid} de {read}), "
            f"más que el máximo de {MAX_DISCARDED_SHARE:.0%}"
        )
    corrected = report.get("gasto negativo pasado a positivo", 0)
    if corrected / read > MAX_CORRECTED_SHARE:
        problems.append(
            f"se corrigió el gasto negativo en el {corrected / read:.0%} de las filas "
            f"({corrected} de {read}), más que el máximo de {MAX_CORRECTED_SHARE:.0%}: "
            f"puede haber cambiado cómo exporta la plataforma"
        )
    return problems


def sheets_client() -> gspread.Client:
    """En GitHub Actions la clave llega como texto en GOOGLE_CREDENTIALS (un secreto del repo);
    en una computadora, como ruta a un archivo en GOOGLE_APPLICATION_CREDENTIALS."""
    if os.environ.get("GOOGLE_CREDENTIALS"):
        return gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_CREDENTIALS"]))
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return gspread.service_account(filename=os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    raise SystemExit(
        "Faltan las credenciales de Google: definí GOOGLE_CREDENTIALS o "
        "GOOGLE_APPLICATION_CREDENTIALS, o corré con --no-publish."
    )


SHEETS_EPOCH = pd.Timestamp("1899-12-30")  # el día 0 de Google Sheets


def to_sheet_values(df: pd.DataFrame) -> list[list]:
    """Encabezado + filas, para escribir tal cual (sin que Sheets interprete nada).

    Las fechas van como el número de día que usa Sheets, así son fechas de verdad (se ordenan y
    filtran como fechas) sin depender del idioma de la planilla. Los vacíos van como celda vacía.
    """
    out = df.copy()
    for col in out.select_dtypes("datetime").columns:
        out[col] = (out[col] - SHEETS_EPOCH).dt.days
    out = out.astype(object).where(out.notna(), "")
    return [list(out.columns)] + out.values.tolist()


def column_letter(df: pd.DataFrame, col: str) -> str:
    return gspread.utils.rowcol_to_a1(1, df.columns.get_loc(col) + 1).rstrip("1")


def write_tab(book: gspread.Spreadsheet, title: str, df: pd.DataFrame) -> None:
    """Reemplaza el contenido de la tab: cada corrida borra lo anterior y escribe todo de nuevo."""
    try:
        sheet = book.worksheet(title)
    except gspread.WorksheetNotFound:
        sheet = book.add_worksheet(title, rows=len(df) + 1, cols=len(df.columns))
    sheet.clear()
    sheet.resize(rows=len(df) + 1, cols=len(df.columns))  # sin filas sobrantes de corridas anteriores
    # RAW: cada valor se escribe tal cual. Con USER_ENTERED, Sheets interpreta el texto como si
    # alguien lo tipeara: un nombre que empieza con "=" se ejecutaría como fórmula.
    sheet.update(to_sheet_values(df), "A1", value_input_option="RAW")

    # Formato de presentación: el dato se guarda con todos sus decimales. Los montos van sin
    # símbolo: "$" se confunde con pesos, y la moneda de cada fila ya está en la columna currency.
    formats = {
        "date": ("DATE", "yyyy-mm-dd"),
        "ctr": ("NUMBER", "0.00%"),
        "cpc": ("NUMBER", "#,##0.00"),
        "cpa": ("NUMBER", "#,##0.00"),
        "spend": ("NUMBER", "#,##0.00"),
        "spend_with_conversions": ("NUMBER", "#,##0.00"),
        "spend_with_revenue": ("NUMBER", "#,##0.00"),
        "revenue": ("NUMBER", "#,##0.00"),
        "roas": ("NUMBER", "0.00"),
    }
    last = len(df) + 1
    sheet.batch_format(
        [{"range": "1:1", "format": {"textFormat": {"bold": True}}}]
        + [
            {
                "range": f"{column_letter(df, col)}2:{column_letter(df, col)}{last}",
                "format": {"numberFormat": {"type": kind, "pattern": pattern}},
            }
            for col, (kind, pattern) in formats.items()
            if col in df.columns
        ]
    )
    sheet.freeze(rows=1)
    log.info("Tab '%s' reemplazada: %d filas", title, len(df))


# Qué es cada columna y cómo se calcula, publicado como una tab más: quien use el Sheet puede
# entender y rehacer cada número sin conocer el código. Un test controla que no falte ninguna columna.
DICTIONARY = pd.DataFrame(
    [
        ("las dos", "campaign_id", "Código único de la campaña", "Del archivo"),
        ("las dos", "campaign_name", "Nombre: PAÍS_OBJETIVO_PLATAFORMA_PERÍODO", "Del archivo, sin espacios sobrantes. Si una campaña trae más de uno, el más frecuente"),
        ("las dos", "channel", "Plataforma: Google Ads, Meta Ads o LinkedIn Ads", "Reconocida por palabra clave en el canal del archivo"),
        ("las dos", "country", "País de la campaña", "Del archivo"),
        ("las dos", "objective", "Objetivo: Awareness, Consideration o Conversion", "Del archivo"),
        ("las dos", "currency", "Moneda de todos los montos de la fila", "Del archivo"),
        (DAILY_TAB, "date", "Día", "Del archivo (acepta AAAA-MM-DD y DD/MM/AAAA)"),
        (DAILY_TAB, "impressions", "Veces que se mostró el anuncio ese día", "Suma de las filas de esa campaña y día"),
        (DAILY_TAB, "clicks", "Clicks del día", "Suma de las filas de esa campaña y día"),
        (DAILY_TAB, "conversions", "Conversiones del día", "Suma de las filas de esa campaña y día. Vacío si alguna no tenía el dato"),
        (DAILY_TAB, "spend", "Gasto del día", "Suma de las filas de esa campaña y día. Un gasto negativo se pasó a positivo (ver corrected_rows)"),
        (DAILY_TAB, "revenue", "Ingresos del día", "Suma de las filas de esa campaña y día. Vacío si alguna no tenía el dato"),
        (DAILY_TAB, "ctr", "Click-through rate: de cada 100 impresiones, cuántos clicks", "clicks / impressions"),
        (DAILY_TAB, "cpc", "Costo por click", "spend / clicks"),
        (DAILY_TAB, "cpa", "Costo por conversión", "spend / conversions. Vacío si no hubo conversiones o falta el dato"),
        (DAILY_TAB, "roas", "Dólares que volvieron por cada dólar invertido", "revenue / spend. Vacío si falta el revenue"),
        (SUMMARY_TAB, "impressions", "Impresiones de la campaña", "Suma de todos los días"),
        (SUMMARY_TAB, "clicks", "Clicks de la campaña", "Suma de todos los días"),
        (SUMMARY_TAB, "spend", "Gasto total de la campaña", "Suma de todos los días"),
        (SUMMARY_TAB, "conversions", "Conversiones conocidas", "Suma de los días que tienen el dato"),
        (SUMMARY_TAB, "spend_with_conversions", "Gasto de los días que tienen dato de conversiones: la base del CPA", "Suma del gasto de esos días. Igual a spend si no falta ningún día"),
        (SUMMARY_TAB, "revenue", "Ingresos conocidos", "Suma de los días que tienen el dato"),
        (SUMMARY_TAB, "spend_with_revenue", "Gasto de los días que tienen dato de revenue: la base del ROAS", "Suma del gasto de esos días. Igual a spend si no falta ningún día"),
        (SUMMARY_TAB, "ctr", "Click-through rate de la campaña", "clicks / impressions, sobre los totales"),
        (SUMMARY_TAB, "cpc", "Costo por click de la campaña", "spend / clicks, sobre los totales"),
        (SUMMARY_TAB, "cpa", "Costo por conversión de la campaña", "spend_with_conversions / conversions: solo los días con dato, así el gasto de un día sin dato no empeora el CPA"),
        (SUMMARY_TAB, "roas", "Retorno del gasto de la campaña", "revenue / spend_with_revenue: solo los días con dato"),
        ("todas", "(celda vacía)", "No hay dato, o la métrica no se puede calcular (por ejemplo, dividir por 0)", "Nunca significa 0"),
    ],
    columns=["tab", "columna", "qué es", "cómo se calcula"],
)
DICTIONARY_TAB = "diccionario"


def publish(daily: pd.DataFrame, summary: pd.DataFrame) -> str:
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    if not spreadsheet_id:
        raise SystemExit("Falta SPREADSHEET_ID: el ID del Google Sheet donde publicar.")
    book = sheets_client().open_by_key(spreadsheet_id)
    write_tab(book, DAILY_TAB, daily)
    write_tab(book, SUMMARY_TAB, summary)
    write_tab(book, DICTIONARY_TAB, DICTIONARY)
    log.info("Publicado en %s", book.url)
    return book.url


def publish_review(rejected: pd.DataFrame, corrected: pd.DataFrame) -> str | None:
    """Publica en un Sheet aparte lo que la limpieza descartó o corrigió, para revisarlo después.

    Es opcional: sin REVIEW_SPREADSHEET_ID el pipeline funciona igual y la revisión queda en output/.
    """
    spreadsheet_id = os.environ.get("REVIEW_SPREADSHEET_ID")
    if not spreadsheet_id:
        log.info("Sin REVIEW_SPREADSHEET_ID: la revisión queda solo en output/")
        return None
    book = sheets_client().open_by_key(spreadsheet_id)
    write_tab(book, REJECTED_TAB, rejected)
    write_tab(book, CORRECTED_TAB, corrected)
    log.info("Revisión publicada en %s", book.url)
    return book.url


class GitHubAnnotations(logging.Handler):
    """En GitHub Actions, los avisos y errores también aparecen como anotaciones en la página de la
    ejecución: un canal desconocido o un archivo rechazado se ven sin abrir el log."""

    def emit(self, record: logging.LogRecord) -> None:
        kind = "error" if record.levelno >= logging.ERROR else "warning"
        print(f"::{kind}::{record.getMessage()}", flush=True)


def write_step_summary(report: dict, outcome: str) -> None:
    """En GitHub Actions, el reporte de la corrida como tabla en la página de la ejecución."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## Pipeline de campañas", "", outcome]
    if report:
        lines += ["", "| Paso | Filas |", "|---|---:|"]
        lines += [f"| {step} | {count} |" for step, count in report.items()]
    with open(path, "a", encoding="utf-8") as summary_file:
        summary_file.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-publish", action="store_true", help="solo genera los CSV locales en output/"
    )
    parser.add_argument(
        "--input", type=Path, default=RAW_CSV, help="CSV a procesar (por defecto data/campaigns.csv)"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        log.addHandler(GitHubAnnotations(level=logging.WARNING))
    try:
        raw = load_raw(args.input)
    except SystemExit as bad_file:  # el archivo no tiene la forma esperada
        log.error("No se publica: %s", bad_file)
        write_step_summary({}, f"❌ **No se publicó:** {bad_file}")
        raise SystemExit(1)
    clean_df, rejected, corrected, report = clean(raw)
    daily, merge_report = merge_same_day(clean_df)
    report.update(merge_report)
    daily = add_metrics(daily)
    for metric in METRIC_COLS:
        report[f"{metric} vacío"] = int(daily[metric].isna().sum())
    for step, count in report.items():
        log.info("%-48s %d", step, count)
    summary = summarize(daily)

    REJECTED_CSV.parent.mkdir(exist_ok=True)
    outputs = {
        DAILY_CSV: daily, SUMMARY_CSV: summary, REJECTED_CSV: rejected, CORRECTED_CSV: corrected,
    }
    for path, table in outputs.items():
        table.to_csv(path, index=False, encoding="utf-8-sig")  # con BOM: Excel lee bien los acentos
        log.info("Escrito %s", path.relative_to(ROOT))

    # La revisión se publica antes del control: si el archivo está roto, es justo lo que hay que ver.
    if not args.no_publish:
        publish_review(rejected, corrected)

    # El control va después de escribir los CSV: si frena, igual quedan para ver qué pasó.
    problems = quality_gate(report)
    if problems:
        for problem in problems:
            log.error("No se publica: %s", problem)
        log.error("El Sheet conserva los datos de la corrida anterior. Revisar las filas descartadas.")
        write_step_summary(report, "❌ **No se publicó:** " + "; ".join(problems) + ".")
        raise SystemExit(1)

    if args.no_publish:
        write_step_summary(report, "Corrida sin publicar (`--no-publish`).")
    else:
        url = publish(daily, summary)
        write_step_summary(report, f"✅ Publicado en [Google Sheets]({url}).")


if __name__ == "__main__":
    main()
