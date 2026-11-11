"""Tests de las reglas del pipeline. Corren sin Google: nada se publica.

Uso: python -m pytest
"""

from pathlib import Path

import pandas as pd
import pytest

import pipeline as p

HEADER = "date,campaign_id,campaign_name,channel,country,objective,impressions,clicks,spend,conversions,revenue,currency"


@pytest.fixture(autouse=True)
def isolated_outputs(tmp_path, monkeypatch):
    """Los tests que corren el pipeline entero escriben en una carpeta temporal, no en output/."""
    monkeypatch.setattr(p, "ROOT", tmp_path)
    for name in ["REJECTED_CSV", "CORRECTED_CSV", "DAILY_CSV", "SUMMARY_CSV"]:
        monkeypatch.setattr(p, name, tmp_path / "output" / getattr(p, name).name)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def run_clean(tmp_path, *rows):
    path = tmp_path / "campaigns.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    clean, rejected, _corrected, report = p.clean(p.load_raw(path))
    return clean, rejected, report


def row(date="2026-09-04", campaign="C1004", name="AR_CONV_Meta_Q4", channel="Meta Ads",
        impressions="1000", clicks="100", spend="50", conversions="5", revenue="200"):
    return f"{date},{campaign},{name},{channel},AR,Conversion,{impressions},{clicks},{spend},{conversions},{revenue},USD"


# --- Lectura de valores --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("$ 182,41", 182.41),
        ("182.41", 182.41),
        ("1.234,5", 1234.5),
        ("1,234.50", 1234.5),
        ("114.055", 114055),
        ("USD 2.493,41", 2493.41),
        ("-1325.39", -1325.39),
        ("0.0", 0.0),
        ("", None),
        ("  ", None),
        ("12-3", None),
        ("(182.41)", -182.41),  # negativo contable
        ("$ (1.234,50)", -1234.5),
        ("US$ 10,5", 10.5),
        ("€ 3,5", 3.5),
        ("1e3", None),  # no se adivina
        ("n/a", None),
    ],
)
def test_to_number(text, expected):
    assert p.to_number(text) == expected


def test_accounting_negative_spend_is_corrected_too(tmp_path):
    clean, rejected, _ = run_clean(tmp_path, row(spend='"(182.41)"'))
    assert rejected.empty and clean["spend"].iloc[0] == 182.41


# --- Forma del archivo ---------------------------------------------------------------------------

def test_missing_column_stops_with_a_clear_message(tmp_path):
    path = tmp_path / "campaigns.csv"
    path.write_text(HEADER.replace(",spend", "") + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"le faltan columnas: \['spend'\]"):
        p.load_raw(path)


@pytest.mark.parametrize("content, message", [("", "está vacío"), (HEADER + "\n", "no tiene filas")])
def test_empty_file_stops_with_a_clear_message(tmp_path, content, message):
    path = tmp_path / "campaigns.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SystemExit, match=message):
        p.load_raw(path)


def test_header_case_and_extra_columns_are_tolerated(tmp_path):
    path = tmp_path / "campaigns.csv"
    header = HEADER.replace("spend", " Spend ") + ",notes"
    path.write_text(f"{header}\n{row()},hola\n", encoding="utf-8")
    raw = p.load_raw(path)
    assert list(raw.columns) == p.RAW_COLS


def test_parse_dates_accepts_both_formats_and_blanks_the_rest():
    parsed = p.parse_dates(pd.Series(["2026-09-17", "17/09/2026", "09/17/2026", ""]))
    assert parsed.iloc[0] == parsed.iloc[1] == pd.Timestamp("2026-09-17")
    assert parsed.iloc[2:].isna().all()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("GOOGLE ADS", "Google Ads"),
        ("Google Ads Search", "Google Ads"),
        ("meta", "Meta Ads"),
        ("Facebook Ads", "Meta Ads"),
        ("Instagram Ads", "Meta Ads"),
        ("Linkedin", "LinkedIn Ads"),
        ("TikTok Ads", None),
    ],
)
def test_classify_channel(text, expected):
    assert p.classify_channel(text) == expected


# --- Limpieza ------------------------------------------------------------------------------------

def test_duplicate_is_detected_even_with_a_different_date_format(tmp_path):
    clean, rejected, report = run_clean(tmp_path, row(date="2026-09-04"), row(date="04/09/2026"))
    assert len(clean) == 1
    assert report["duplicados exactos"] == 1
    assert rejected.loc[0, "reason"] == "duplicado exacto de la línea 2"
    assert rejected.loc[0, "source_line"] == 3


def test_impossible_rows_are_rejected_with_every_reason(tmp_path):
    clean, rejected, _ = run_clean(
        tmp_path,
        row(),
        row(date="2026-09-05", conversions="-1"),
        row(date="2026-09-06", clicks="2000"),
        row(date="2026-09-07", impressions="-5"),  # negativa y, por eso, menos que los clicks
    )
    assert len(clean) == 1
    assert list(rejected["reason"]) == [
        "valor negativo",
        "más clicks que impresiones",
        "valor negativo; más clicks que impresiones",
    ]
    assert rejected.loc[0, "conversions"] == "-1"  # el descartado se guarda tal como venía


def test_negative_spend_is_made_positive_and_recorded(tmp_path):
    path = tmp_path / "campaigns.csv"
    rows = [row(spend="-328.33"), row(spend="-328.33"), row(date="2026-09-05", spend="-50", clicks="2000")]
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    clean, rejected, corrected, report = p.clean(p.load_raw(path))

    assert clean["spend"].tolist() == [328.33]  # la copia corregida se detecta como duplicado
    assert list(corrected["source_line"]) == [2]
    assert corrected.loc[0, "spend"] == "-328.33"  # se guarda tal como venía
    assert corrected.loc[0, "correction"] == "spend -328.33 pasado a positivo"
    assert report["gasto negativo pasado a positivo"] == 1
    # La que además tiene más clicks que impresiones se descarta: figura en rejected, no en corrected.
    assert list(rejected["source_line"]) == [3, 4]


def test_blank_results_keep_the_row_and_stay_blank(tmp_path):
    clean, rejected, _ = run_clean(tmp_path, row(conversions="", revenue=""))
    assert len(clean) == 1 and rejected.empty
    assert pd.isna(clean["conversions"].iloc[0]) and pd.isna(clean["revenue"].iloc[0])


def test_fractional_count_becomes_blank(tmp_path):
    clean, _, _ = run_clean(tmp_path, row(conversions='"2,5"'))  # entre comillas: la coma es decimal
    assert pd.isna(clean["conversions"].iloc[0])


# --- Unión por campaña y día ---------------------------------------------------------------------

def test_merge_sums_rows_of_the_same_campaign_and_day(tmp_path):
    clean, _, _ = run_clean(tmp_path, row(spend="50"), row(spend="30", impressions="500"))
    daily, _ = p.merge_same_day(clean)
    assert len(daily) == 1
    assert daily.loc[0, "spend"] == 80
    assert daily.loc[0, "impressions"] == 1500


def test_merge_blank_part_leaves_the_total_blank(tmp_path):
    clean, _, _ = run_clean(tmp_path, row(conversions="9"), row(spend="30", conversions=""))
    daily, _ = p.merge_same_day(clean)
    assert pd.isna(daily.loc[0, "conversions"])


def test_attribute_variants_do_not_split_the_primary_key(tmp_path):
    clean, _, _ = run_clean(
        tmp_path,
        row(name="AR_CONV_Meta_Q4"),
        row(name="AR_CONV_Meta_Q4", spend="30"),
        row(name="AR_CONV_Meta_Q4_v2", spend="20", channel="meta"),
    )
    daily, report = p.merge_same_day(clean)
    assert len(daily) == 1
    assert daily.loc[0, "campaign_name"] == "AR_CONV_Meta_Q4"  # el más frecuente
    assert report["campañas con atributos inconsistentes"] == 1


def test_different_currencies_are_never_summed(tmp_path):
    clean, _, _ = run_clean(tmp_path, row(), row(spend="30").replace(",USD", ",CLP"))
    daily, _ = p.merge_same_day(clean)
    assert sorted(daily["currency"]) == ["CLP", "USD"]


# --- Métricas y resumen --------------------------------------------------------------------------

def test_safe_divide_blank_when_denominator_is_zero_or_missing():
    result = p.safe_divide(pd.Series([10, 0, 10, None]), pd.Series([0, 5, None, 5]))
    assert result.isna().tolist() == [True, False, True, True]
    assert result.iloc[1] == 0  # el 0 arriba sí es un resultado válido


def test_summary_cpa_uses_only_the_spend_of_days_with_conversions(tmp_path):
    clean, _, _ = run_clean(
        tmp_path,
        row(date="2026-09-04", spend="100", conversions="10"),
        row(date="2026-09-05", spend="300", conversions=""),
    )
    daily, _ = p.merge_same_day(clean)
    summary = p.summarize(p.add_metrics(daily))
    assert summary.loc[0, "spend"] == 400  # el total sigue siendo el total
    assert summary.loc[0, "cpa"] == 10  # 100 / 10, no 400 / 10
    assert summary.loc[0, "spend_with_conversions"] == 100  # la base del CPA, a la vista


def test_every_summary_metric_can_be_redone_from_visible_columns():
    """Un analista tiene que poder rehacer cada métrica con las columnas de la tabla."""
    clean, _, _, _ = p.clean(p.load_raw(CASE_CSV))
    daily = p.add_metrics(p.merge_same_day(clean)[0])
    for table, cpa_base, roas_base in [
        (daily, "spend", "spend"),
        (p.summarize(daily), "spend_with_conversions", "spend_with_revenue"),
    ]:
        pd.testing.assert_series_equal(
            table["cpa"], p.safe_divide(table[cpa_base], table["conversions"]), check_names=False
        )
        pd.testing.assert_series_equal(
            table["roas"], p.safe_divide(table["revenue"], table[roas_base]), check_names=False
        )


def test_dictionary_explains_every_published_column():
    clean, _, _, _ = p.clean(p.load_raw(CASE_CSV))
    daily = p.add_metrics(p.merge_same_day(clean)[0])
    summary = p.summarize(daily)
    documented = p.DICTIONARY
    for tab, table in [(p.DAILY_TAB, daily), (p.SUMMARY_TAB, summary)]:
        covered = set(documented.loc[documented["tab"].isin([tab, "las dos"]), "columna"])
        assert set(table.columns) <= covered, f"{tab}: faltan {set(table.columns) - covered}"


def test_summed_money_has_no_float_noise(tmp_path):
    clean, _, _ = run_clean(tmp_path, row(spend="0.1"), row(spend="0.2"))
    daily, _ = p.merge_same_day(clean)
    assert daily.loc[0, "spend"] == 0.3  # sin redondear daría 0.30000000000000004


# --- Publicación ---------------------------------------------------------------------------------

def test_sheet_values_are_literal_with_real_dates_and_blanks():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-17"]),
            "campaign_name": ['=HYPERLINK("http://x")'],
            "conversions": pd.array([None], dtype="Int64"),
        }
    )
    header, *values = p.to_sheet_values(df)
    assert header == ["date", "campaign_name", "conversions"]
    assert values[0][0] == 46282  # 17/09/2026 como día de Sheets
    assert values[0][1] == '=HYPERLINK("http://x")'  # texto: con RAW no se ejecuta
    assert values[0][2] == ""


class FakeSheet:
    """Una tab de mentira que anota lo que el pipeline le pide, sin hablar con Google."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, method):
        return lambda *args, **kwargs: self.calls.append((method, args, kwargs))


def test_write_tab_clears_then_writes_literal_values():
    sheet = FakeSheet()
    book = type("Book", (), {"worksheet": lambda self, title: sheet})()
    df = pd.DataFrame({"date": pd.to_datetime(["2026-09-17"]), "spend": [10.5]})
    p.write_tab(book, "clean_data", df)

    methods = [method for method, _, _ in sheet.calls]
    assert methods.index("clear") < methods.index("update")  # reemplaza, no agrega abajo
    _, args, kwargs = sheet.calls[methods.index("update")]
    assert kwargs["value_input_option"] == "RAW"
    assert args[0] == [["date", "spend"], [46282, 10.5]]


# --- Control antes de publicar -------------------------------------------------------------------

@pytest.mark.parametrize(
    "read, valid, publishes",
    [(214, 198, True), (214, 172, True), (214, 171, False), (214, 0, False)],
)
def test_quality_gate(read, valid, publishes):
    assert (p.quality_gate({"filas leídas": read, "filas válidas": valid}) == []) is publishes


def test_broken_file_stops_before_publishing(tmp_path, monkeypatch):
    path = tmp_path / "broken.csv"
    path.write_text("\n".join([HEADER, row(clicks="2000")]) + "\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["pipeline.py", "--input", str(path)])
    monkeypatch.setattr(p, "publish", lambda *_: pytest.fail("publicó un archivo roto"))
    with pytest.raises(SystemExit) as stopped:
        p.main()
    assert stopped.value.code == 1


# --- Reporte en GitHub Actions -------------------------------------------------------------------

def test_step_summary_reports_why_a_broken_file_was_not_published(tmp_path, monkeypatch, capsys):
    path = tmp_path / "broken.csv"
    path.write_text("\n".join([HEADER, row(clicks="2000")]) + "\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr("sys.argv", ["pipeline.py", "--input", str(path)])
    try:
        with pytest.raises(SystemExit):
            p.main()
    finally:
        p.log.handlers.clear()

    text = summary.read_text(encoding="utf-8")
    assert "No se publicó" in text and "| filas leídas | 1 |" in text
    assert "::error::No se publica" in capsys.readouterr().out  # anotación en la página


def test_step_summary_explains_a_file_with_the_wrong_shape(tmp_path, monkeypatch):
    path = tmp_path / "campaigns.csv"
    path.write_text(HEADER.replace(",spend", "") + "\n" + row() + "\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr("sys.argv", ["pipeline.py", "--input", str(path)])
    with pytest.raises(SystemExit) as stopped:
        p.main()
    assert stopped.value.code == 1
    assert "le faltan columnas: ['spend']" in summary.read_text(encoding="utf-8")


# --- CSVs nuevos: lo que puede cambiar de una semana a otra --------------------------------------

def test_excel_export_with_semicolons_and_latin1_is_read(tmp_path):
    path = tmp_path / "campaigns.csv"
    data_row = row(name="AR_CONV_Ñandú_Meta_Q4", spend="SPEND").replace(",", ";").replace("SPEND", "182,41")
    path.write_bytes((HEADER.replace(",", ";") + "\n" + data_row + "\n").encode("latin-1"))
    raw = p.load_raw(path)
    assert list(raw.columns) == p.RAW_COLS
    assert raw.loc[2, "campaign_name"] == "AR_CONV_Ñandú_Meta_Q4"
    assert p.to_number(raw.loc[2, "spend"]) == 182.41


def test_future_date_is_rejected(tmp_path):
    clean, rejected, _ = run_clean(tmp_path, row(), row(date="2062-09-17"))
    assert len(clean) == 1 and rejected.loc[0, "reason"] == "fecha futura"


def test_gate_stops_when_too_many_rows_need_correcting():
    report = {"filas leídas": 214, "filas válidas": 202, "gasto negativo pasado a positivo": 202}
    assert "puede haber cambiado cómo exporta la plataforma" in p.quality_gate(report)[0]
    report["gasto negativo pasado a positivo"] = 4
    assert p.quality_gate(report) == []


# --- El archivo del caso -------------------------------------------------------------------------

# Una copia fija del CSV que entregó Winclap, no data/campaigns.csv: ese archivo se reemplaza cada
# semana y sus números cambian. Los tests prueban las reglas; el control de calidad, cada archivo.
CASE_CSV = Path(__file__).parent / "fixtures" / "campaigns_case.csv"


def test_case_file_end_to_end():
    clean, rejected, corrected, report = p.clean(p.load_raw(CASE_CSV))
    daily, _ = p.merge_same_day(clean)
    summary = p.summarize(p.add_metrics(daily))

    assert (report["filas leídas"], report["filas válidas"], len(rejected)) == (214, 202, 12)
    assert report["inválidas descartadas"] == 6  # más clicks que impresiones
    assert len(corrected) == 4  # gasto negativo pasado a positivo (la quinta se descarta igual)
    assert len(daily) == 145 and len(summary) == 12
    assert not daily.duplicated(["date", "campaign_id"]).any()  # clave primaria
    assert not summary.duplicated("campaign_id").any()
    assert daily["spend"].sum() == pytest.approx(clean["spend"].sum())
    assert summary["spend"].sum() == pytest.approx(daily["spend"].sum())
    assert p.quality_gate(report) == []
