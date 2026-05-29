from pathlib import Path
import importlib.util
import re
import unicodedata

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from matplotlib.backends.backend_pdf import PdfPages
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill


SCRIPT_DIR = Path(__file__).resolve().parent
BASE = SCRIPT_DIR / "base" / "parquet" / "df_ronda.parquet"
VALIDANDO_SCRIPT = SCRIPT_DIR / "Validando Registros Manuais.py"
OUT_DIR = SCRIPT_DIR / "Ocorrências" / "Foco_B-VSP_Cenarios_Beneficio"
OUT_XLSX = OUT_DIR / "00_ranking_B-VSP_cenarios_beneficio.xlsx"
OUT_PDF = OUT_DIR / "00_ranking_B-VSP_cenarios_beneficio.pdf"
OUT_PEOPLE_DIR = OUT_DIR / "Colaboradores"
REGISTRO_MANUAL_COL = "registro_manual"

AREA_FOCO = "B-VSP"
CARGO_FOCO = None
CIBELE_CADASTRO = "4062738"
PERIOD_START = pd.Timestamp("2024-01-01")
PERIOD_END = pd.Timestamp("2026-04-01")
GAP_MINIMO_MIN = 60
TOP_DIAS_PDF = 24

COLS_BASE = [
    "cadastro",
    "nome",
    "data",
    "hora",
    "dir",
    "tipo",
    "acesso",
    "descricao_coletor",
    "uso_acesso",
    "planta",
    "coletor",
    "cargo",
    "area",
    "departamento",
    REGISTRO_MANUAL_COL,
]

PORTARIA_RE = re.compile(
    r"\bPORTARIA\b|\bPORT\b|\bCANCELA\b|\bGUARITA\b|\bPEDESTRE\b|"
    r"\bFUNCIONARIO\b|\bGATE\b"
)
PONTO_RE = re.compile(r"\bMARCA\b|\bPONTO\b|\bPONT\b")


def load_validando_module():
    spec = importlib.util.spec_from_file_location("validando_manuais", VALIDANDO_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalizar_texto(value):
    if pd.isna(value):
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.upper().strip()


def duration_label(minutes):
    if pd.isna(minutes):
        return "-"
    value = int(round(abs(float(minutes))))
    hours, mins = divmod(value, 60)
    if hours and mins:
        return f"{hours}h {mins}min"
    if hours:
        return f"{hours}h"
    return f"{mins}min"


def minute_label(minutes):
    if pd.isna(minutes):
        return ""
    value = int(round(float(minutes)))
    return f"{value // 60:02d}:{value % 60:02d}"


def safe_filename(value, fallback="sem_nome"):
    clean = "".join(
        ch if ch.isalnum() or ch in (" ", "-", "_", ".") else "_"
        for ch in str(value)
    ).strip()
    clean = "_".join(clean.split())
    return clean or fallback


def corrigir_data_ambigua(series):
    data = pd.to_datetime(series, errors="coerce").dt.normalize()
    dt = data.dt
    ambiguas = data.notna() & dt.day.le(12) & dt.month.le(12)
    invertida = pd.to_datetime(
        {"year": dt.year, "month": dt.day, "day": dt.month},
        errors="coerce",
    )
    return data.where(~ambiguas, invertida).dt.normalize()


def find_focus_people():
    people = {}
    parquet = pq.ParquetFile(BASE)
    for batch in parquet.iter_batches(
        batch_size=500_000,
        columns=["cadastro", "nome", "cargo", "area"],
        use_threads=False,
    ):
        part = batch.to_pandas()
        mask = part["area"].astype("string").str.strip().str.upper().str.startswith(AREA_FOCO, na=False)
        if CARGO_FOCO:
            mask = mask & part["cargo"].astype("string").str.strip().str.upper().eq(str(CARGO_FOCO).upper())
        if not mask.any():
            continue
        focus = part.loc[mask, ["cadastro", "nome", "cargo", "area"]].dropna(subset=["cadastro"])
        for row in focus.drop_duplicates("cadastro").itertuples(index=False):
            cadastro = str(row.cadastro).strip()
            people[cadastro] = {
                "cadastro": cadastro,
                "nome": str(row.nome).strip(),
                "cargo": str(row.cargo).strip(),
                "area": str(row.area).strip(),
            }
    return people


def load_rows_for_people(cadastros):
    parts = []
    parquet = pq.ParquetFile(BASE)
    cadastros = {str(c).strip() for c in cadastros}
    for batch in parquet.iter_batches(batch_size=500_000, columns=COLS_BASE, use_threads=False):
        part = batch.to_pandas()
        mask = part["cadastro"].astype("string").str.strip().isin(cadastros)
        if mask.any():
            parts.append(part.loc[mask].copy())
    if not parts:
        return pd.DataFrame(columns=COLS_BASE)
    return pd.concat(parts, ignore_index=True)


def prepare_for_manual_module(df, manual_module):
    df = df.copy()
    df["data_corrigida"] = corrigir_data_ambigua(df["data"])
    df["hora_min"] = df["hora"].map(manual_module.hora_to_minutes)
    df = df.dropna(subset=["data_corrigida", "hora_min"]).copy()
    df["data_hora"] = df["data_corrigida"] + pd.to_timedelta(df["hora_min"], unit="m")
    df = df[(df["data_corrigida"] >= PERIOD_START) & (df["data_corrigida"] <= PERIOD_END)].copy()

    df["manual_norm"] = df[REGISTRO_MANUAL_COL].astype(str).str.strip().str.upper()
    df["dir_norm"] = df["dir"].astype(str).str.strip().str.upper()
    df["tipo_norm"] = df["tipo"].fillna("").astype(str).str.strip().str.upper()
    df["planta_norm"] = df["planta"].astype(str).str.strip()
    df["desc_norm"] = df["descricao_coletor"].fillna("").astype(str).str.upper()
    df["uso_norm"] = df["uso_acesso"].fillna("").astype(str).str.upper()
    df["coletor_norm"] = df["coletor"].fillna("").astype(str).str.upper()
    df["acesso_norm"] = df["acesso"].fillna("").astype(str).str.upper()
    df["home_office_flag"] = (
        manual_module.contains_any_term(df["desc_norm"])
        | manual_module.contains_any_term(df["uso_norm"])
        | manual_module.contains_any_term(df["coletor_norm"])
        | manual_module.contains_any_term(df["acesso_norm"])
    )
    return df


def build_manual_summary(people, all_rows, manual_module):
    summaries = []
    all_cases = []
    for cadastro, person in people.items():
        raw = all_rows[all_rows["cadastro"].astype("string").str.strip().eq(cadastro)].copy()
        if raw.empty:
            summaries.append({**person, "erro": "Sem linhas no parquet"})
            continue

        prepared = prepare_for_manual_module(raw, manual_module)
        if prepared.empty:
            summaries.append({**person, "erro": "Sem linhas no periodo"})
            continue

        try:
            (
                _period_all,
                _manual,
                _daily_exit,
                _daily_entry,
                manual_after_exit,
                manual_before_entry,
                daily_suspicious,
                stats,
            ) = manual_module.prepare_person_analysis(prepared, manual_cargo=CARGO_FOCO)
        except Exception as exc:
            summaries.append({**person, "erro": str(exc)})
            continue

        cases = manual_module.build_manual_cases(manual_after_exit, manual_before_entry)
        if daily_suspicious.empty:
            diferenca_servico_real_horas = float(stats.get("diferenca_horas_servico_reais", 0.0))
        elif "diferenca_servico_real_horas" in daily_suspicious:
            diferenca_servico_real_horas = float(daily_suspicious["diferenca_servico_real_horas"].sum())
        elif "diferenca_min" in daily_suspicious:
            diferenca_servico_real_horas = float(daily_suspicious["diferenca_min"].sum() / 60.0)
        else:
            diferenca_servico_real_horas = float(stats.get("diferenca_horas_servico_reais", 0.0))
        summaries.append(
            {
                **person,
                **stats,
                "diferenca_servico_real_horas": diferenca_servico_real_horas,
                "maior_diferenca_min": float(cases["minutos_fora"].max()) if not cases.empty else np.nan,
            }
        )
        if not cases.empty:
            cases = cases.copy()
            for position, (column, value) in enumerate(
                [
                    ("cadastro", cadastro),
                    ("nome", person["nome"]),
                    ("cargo", person["cargo"]),
                    ("area", person["area"]),
                ]
            ):
                if column in cases.columns:
                    cases[column] = value
                else:
                    cases.insert(position, column, value)
            all_cases.append(cases)

    summary = pd.DataFrame(summaries)
    if not summary.empty:
        numeric_cols = [
            "horas_apos_saida",
            "horas_antes_entrada",
            "horas_totais_manipuladas",
            "diferenca_servico_real_horas",
            "maior_diferenca_min",
        ]
        for col in numeric_cols:
            if col in summary:
                summary[col] = pd.to_numeric(summary[col], errors="coerce").round(2)
        if "ocorrencias_fora_fabrica" in summary:
            summary = summary.sort_values(
                ["ocorrencias_fora_fabrica", "horas_totais_manipuladas"],
                ascending=False,
                na_position="last",
            )

    cases = pd.concat(all_cases, ignore_index=True) if all_cases else pd.DataFrame()
    return summary, cases


def classify_presence_intervals(day_rows):
    physical = day_rows[
        day_rows["is_portaria"]
        & day_rows["dir_norm"].isin(["E", "S"])
        & ~day_rows["manual_norm"].eq("SIM")
        & ~day_rows["planta_norm"].eq("999")
    ].sort_values("hora_min")

    intervals = []
    start = None
    for row in physical.itertuples(index=False):
        if row.dir_norm == "E":
            if start is None:
                start = float(row.hora_min)
        elif row.dir_norm == "S":
            if start is not None and float(row.hora_min) >= start:
                intervals.append((start, float(row.hora_min)))
                start = None
    if start is not None:
        intervals.append((start, 24 * 60.0))
    return intervals, physical


def point_reason(point_min, intervals):
    if not intervals:
        return "Sem intervalo fisico"
    if any(start <= point_min <= end for start, end in intervals):
        return "Dentro de presenca fisica"
    first_start = min(start for start, _end in intervals)
    last_end = max(end for _start, end in intervals)
    if point_min < first_start:
        return "Antes da entrada fisica"
    if point_min > last_end:
        return "Depois da saida fisica"
    return "Entre saida e reentrada"


def minutes_to_nearest_interval(point_min, intervals):
    if not intervals:
        return np.nan
    if any(start <= point_min <= end for start, end in intervals):
        return 0.0
    return min(min(abs(point_min - start), abs(point_min - end)) for start, end in intervals)


def analyze_person_presence(person_rows, person):
    df = person_rows.copy()
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), df

    person_meta = {
        "cadastro": str(person.get("cadastro", "")).strip(),
        "nome": str(person.get("nome", "")).strip(),
        "cargo": str(person.get("cargo", "")).strip(),
        "area": str(person.get("area", "")).strip(),
    }
    df["data_corrigida"] = corrigir_data_ambigua(df["data"])
    df["hora_min"] = df["hora"].map(lambda value: minute_from_any(value))
    df = df.dropna(subset=["data_corrigida", "hora_min"]).copy()
    df = df[(df["data_corrigida"] >= PERIOD_START) & (df["data_corrigida"] <= PERIOD_END)].copy()
    df["data_hora"] = df["data_corrigida"] + pd.to_timedelta(df["hora_min"], unit="m")
    df["manual_norm"] = df[REGISTRO_MANUAL_COL].astype(str).str.strip().str.upper()
    df["dir_norm"] = df["dir"].astype(str).str.strip().str.upper()
    df["planta_norm"] = df["planta"].astype(str).str.strip()
    df["desc_ascii"] = df["descricao_coletor"].map(normalizar_texto)
    df["is_portaria"] = df["desc_ascii"].str.contains(PORTARIA_RE, na=False)
    df["is_ponto"] = df["desc_ascii"].str.contains(PONTO_RE, na=False)

    point_rows = []
    daily_rows = []
    for data_ref, day in df.groupby("data_corrigida", sort=True):
        intervals, physical = classify_presence_intervals(day)
        points = day[day["is_ponto"]].sort_values("hora_min")
        first_entry = physical.loc[physical["dir_norm"].eq("E"), "hora_min"].min()
        last_exit = physical.loc[physical["dir_norm"].eq("S"), "hora_min"].max()
        first_point = points["hora_min"].min() if not points.empty else np.nan
        last_point = points["hora_min"].max() if not points.empty else np.nan

        after_last_point = (
            max(float(last_exit) - float(last_point), 0.0)
            if pd.notna(last_exit) and pd.notna(last_point)
            else np.nan
        )
        before_first_point = (
            max(float(first_point) - float(first_entry), 0.0)
            if pd.notna(first_entry) and pd.notna(first_point)
            else np.nan
        )

        daily_rows.append(
            {
                **person_meta,
                "data": data_ref,
                "dia_semana": day_name(data_ref),
                "qtd_registros": len(day),
                "qtd_pontos": len(points),
                "qtd_pontos_999": int(points["planta_norm"].eq("999").sum()) if not points.empty else 0,
                "qtd_pontos_manuais_oficiais": int(points["manual_norm"].eq("SIM").sum()) if not points.empty else 0,
                "primeira_entrada_fisica": minute_label(first_entry),
                "ultima_saida_fisica": minute_label(last_exit),
                "primeiro_ponto": minute_label(first_point),
                "ultimo_ponto": minute_label(last_point),
                "min_antes_primeiro_ponto": before_first_point,
                "min_apos_ultimo_ponto": after_last_point,
                "horas_apos_ultimo_ponto": (
                    round(after_last_point / 60.0, 2) if pd.notna(after_last_point) else np.nan
                ),
                "gap_apos_ponto_maior_1h": bool(pd.notna(after_last_point) and after_last_point > GAP_MINIMO_MIN),
                "beneficio_gap_min": after_last_point if pd.notna(after_last_point) and after_last_point > GAP_MINIMO_MIN else 0.0,
            }
        )

        for point in points.itertuples(index=False):
            reason = point_reason(float(point.hora_min), intervals)
            minutes_out = minutes_to_nearest_interval(float(point.hora_min), intervals)
            outside = reason != "Dentro de presenca fisica"
            point_rows.append(
                {
                    **person_meta,
                    "data": data_ref,
                    "dia_semana": day_name(data_ref),
                    "hora_ponto": minute_label(point.hora_min),
                    "motivo_presenca": reason,
                    "fora_presenca_fisica": outside,
                    "minutos_ate_presenca_fisica": minutes_out,
                    "beneficio_ponto_fora_min": minutes_out if outside and pd.notna(minutes_out) else 0.0,
                    "diferenca": duration_label(minutes_out) if pd.notna(minutes_out) else "-",
                    "manual_oficial": point.manual_norm,
                    "planta": point.planta,
                    "dir": point.dir,
                    "tipo": point.tipo,
                    "acesso": point.acesso,
                    "coletor": point.coletor,
                    "descricao_coletor": point.descricao_coletor,
                }
            )

    daily = pd.DataFrame(daily_rows)
    points = pd.DataFrame(point_rows)
    if not points.empty:
        points = points.sort_values(["fora_presenca_fisica", "minutos_ate_presenca_fisica"], ascending=False)
    if not daily.empty:
        daily = daily.sort_values(["gap_apos_ponto_maior_1h", "min_apos_ultimo_ponto"], ascending=False)
    raw = df.sort_values(["data_corrigida", "hora_min"]).copy()
    return daily, points, raw


def minute_from_any(value):
    if pd.isna(value):
        return np.nan
    if isinstance(value, pd.Timedelta):
        parts = value.components
        return parts.hours * 60 + parts.minutes + parts.seconds / 60
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return value.hour * 60 + value.minute + getattr(value, "second", 0) / 60
    try:
        parts = str(value).split(":")
        return int(parts[0]) * 60 + int(parts[1]) + (int(parts[2]) / 60 if len(parts) > 2 else 0)
    except Exception:
        return np.nan


def day_name(value):
    names = {
        0: "Segunda",
        1: "Terca",
        2: "Quarta",
        3: "Quinta",
        4: "Sexta",
        5: "Sabado",
        6: "Domingo",
    }
    return names[pd.Timestamp(value).weekday()]


def build_resumo(manual_summary, cibele_daily, cibele_points):
    cibele_manual = manual_summary[manual_summary["cadastro"].astype(str).eq(CIBELE_CADASTRO)]
    cibele_manual_official = 0
    if not cibele_manual.empty and "registros_manuais_brutos" in cibele_manual.columns:
        cibele_manual_official = int(cibele_manual["registros_manuais_brutos"].iloc[0])

    cibele_points_out = cibele_points[cibele_points["fora_presenca_fisica"]] if not cibele_points.empty else cibele_points
    official_manual_out = (
        int(cibele_points_out["manual_oficial"].astype(str).str.upper().eq("SIM").sum())
        if not cibele_points_out.empty
        else 0
    )
    points_999_out = (
        int(cibele_points_out["planta"].astype(str).str.strip().eq("999").sum())
        if not cibele_points_out.empty
        else 0
    )

    return pd.DataFrame(
        [
            {
                "item": "Mensalistas B-VSP-1 avaliados",
                "valor": len(manual_summary),
                "leitura": "Recorte de cargo M e area dominante B-VSP-1.",
            },
            {
                "item": "Cibele - registros registro_manual=Sim",
                "valor": cibele_manual_official,
                "leitura": "Na base de ajustes manuais, a Cibele nao aparece com ponto manual oficial.",
            },
            {
                "item": "Cibele - pontos fora de presenca fisica",
                "valor": len(cibele_points_out),
                "leitura": "Pontos de relogio/captura que caem antes da entrada, depois da saida ou entre saida e reentrada.",
            },
            {
                "item": "Cibele - desses, registro_manual=Sim",
                "valor": official_manual_out,
                "leitura": "Confere se o ponto fora de presenca tambem foi ajuste manual oficial.",
            },
            {
                "item": "Cibele - desses, planta 999",
                "valor": points_999_out,
                "leitura": "Indica captura digital/home office, separada de registro_manual=Sim.",
            },
            {
                "item": "Cibele - dias com saida fisica mais de 1h apos ultimo ponto",
                "valor": int(cibele_daily["gap_apos_ponto_maior_1h"].sum()) if not cibele_daily.empty else 0,
                "leitura": "Esse e o mecanismo que explica as horas depois do ponto, sem depender de registro_manual=Sim.",
            },
            {
                "item": "Cibele - horas fisicas apos ultimo ponto",
                "valor": round(cibele_daily["horas_apos_ultimo_ponto"].fillna(0).sum(), 2) if not cibele_daily.empty else 0,
                "leitura": "Soma do intervalo entre ultimo ponto do dia e ultima saida fisica da fabrica.",
            },
        ]
    )


def registros_top_dias(cibele_raw, cibele_daily):
    if cibele_daily.empty:
        return pd.DataFrame()
    top_dates = set(cibele_daily.head(20)["data"])
    out = cibele_raw[cibele_raw["data_corrigida"].isin(top_dates)].copy()
    cols = [
        "cadastro",
        "nome",
        "data_corrigida",
        "hora",
        "dir",
        "tipo",
        "acesso",
        "planta",
        "coletor",
        "descricao_coletor",
        "uso_acesso",
        "area",
        "cargo",
        "registro_manual",
    ]
    return out[[c for c in cols if c in out.columns]].sort_values(["data_corrigida", "hora"])


def write_excel(tables):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        for sheet, df in tables.items():
            safe_sheet = sheet[:31]
            df.to_excel(writer, sheet_name=safe_sheet, index=False)

    wb = load_workbook(OUT_XLSX)
    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1764A5")
        for column_cells in ws.columns:
            letter = column_cells[0].column_letter
            max_len = max((len(str(cell.value)) for cell in column_cells[:200] if cell.value is not None), default=8)
            ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 48)
    wb.save(OUT_XLSX)


def write_pdf(resumo, manual_summary, cibele_daily, cibele_points):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUT_PDF) as pdf:
        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        ax.axis("off")
        fig.patch.set_facecolor("#f4f8fb")
        ax.text(0.03, 0.95, "Foco mensalistas B-VSP-1 / Cibele", fontsize=18, fontweight="bold", color="#142235")
        ax.text(
            0.03,
            0.90,
            "Separacao entre ponto manual oficial e ponto/presenca fisica desalinhados.",
            fontsize=10,
            color="#5b7088",
        )
        y = 0.82
        for row in resumo.itertuples(index=False):
            ax.text(0.04, y, str(row.item), fontsize=9, color="#5b7088")
            ax.text(0.44, y, str(row.valor), fontsize=13, fontweight="bold", color="#1764a5")
            ax.text(0.57, y, str(row.leitura), fontsize=8.2, color="#142235")
            y -= 0.065

        table_cols = [
            "cadastro",
            "nome",
            "registros_manuais_brutos",
            "ocorrencias_fora_fabrica",
            "horas_totais_manipuladas",
        ]
        view = manual_summary[[c for c in table_cols if c in manual_summary.columns]].copy()
        if not view.empty:
            y -= 0.04
            ax.text(0.04, y, "Mensalistas da area", fontsize=12, fontweight="bold", color="#142235")
            y -= 0.04
            text = view.to_string(index=False)
            ax.text(0.04, y, text, family="monospace", fontsize=8, color="#142235", va="top")
        pdf.savefig(fig, facecolor=fig.get_facecolor())
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        fig.patch.set_facecolor("#f4f8fb")
        ax.set_facecolor("#ffffff")
        timeline = cibele_daily.copy()
        timeline["ultimo_ponto_min"] = timeline["ultimo_ponto"].map(minute_from_any)
        timeline["ultima_saida_min"] = timeline["ultima_saida_fisica"].map(minute_from_any)
        timeline = timeline.dropna(subset=["data", "ultimo_ponto_min"]).sort_values("data")
        if timeline.empty:
            ax.text(0.05, 0.80, "Sem pontos diarios para plotar.", transform=ax.transAxes)
        else:
            normal = timeline[~timeline["qtd_pontos_999"].fillna(0).gt(0)]
            home = timeline[timeline["qtd_pontos_999"].fillna(0).gt(0)]
            if not normal.empty:
                ax.scatter(
                    normal["data"],
                    normal["ultimo_ponto_min"],
                    s=26,
                    color="#89CFF0",
                    edgecolors="#155C87",
                    linewidth=0.35,
                    alpha=0.78,
                    label="Ultimo ponto diario",
                )
            if not home.empty:
                ax.scatter(
                    home["data"],
                    home["ultimo_ponto_min"],
                    s=44,
                    color="#F2A65A",
                    edgecolors="#9A4F00",
                    linewidth=0.6,
                    alpha=0.95,
                    label="Dia com Home-office",
                )
            saidas = timeline.dropna(subset=["ultima_saida_min"])
            if not saidas.empty:
                ax.plot(
                    saidas["data"],
                    saidas["ultima_saida_min"],
                    color="#155C87",
                    linewidth=2.4,
                    alpha=0.80,
                    label="Ultima saida fisica",
                )
            y_values = timeline[["ultimo_ponto_min", "ultima_saida_min"]].stack().dropna()
            y_min = max(6 * 60, np.floor((y_values.min() - 45) / 30) * 30)
            y_max = min(24 * 60, np.ceil((y_values.max() + 45) / 30) * 30)
            ax.set_ylim(y_max, y_min)
            ax.set_yticks(np.arange(y_min, y_max + 1, 30))
            ax.set_yticklabels([minute_label(v) for v in np.arange(y_min, y_max + 1, 30)], fontsize=8)
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b/%y"))
            ax.grid(True, axis="both", color="#d5e5ee", linewidth=0.8)
            ax.legend(loc="upper left", frameon=True, facecolor="#ffffff", edgecolor="#d5e5ee", fontsize=8.4)
        ax.set_title("Cibele: ponto x presenca fisica", loc="left", fontsize=14, fontweight="bold", color="#142235")
        ax.set_ylabel("Horario")
        ax.set_xlabel("Data")
        for spine in ax.spines.values():
            spine.set_visible(False)
        pdf.savefig(fig, facecolor=fig.get_facecolor())
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        fig.patch.set_facecolor("#f4f8fb")
        ax.set_facecolor("#ffffff")
        top = cibele_daily.head(20).copy()
        if top.empty:
            ax.text(0.05, 0.80, "Sem dias de Cibele para plotar.", transform=ax.transAxes)
        else:
            top = top.sort_values("min_apos_ultimo_ponto")
            y_pos = np.arange(len(top))
            ax.barh(y_pos, top["min_apos_ultimo_ponto"].fillna(0) / 60.0, color="#1764a5")
            ax.set_yticks(y_pos)
            ax.set_yticklabels([pd.Timestamp(v).strftime("%d/%m/%Y") for v in top["data"]], fontsize=8)
            ax.set_xlabel("Horas entre ultimo ponto e ultima saida fisica")
            ax.set_title("Cibele: maiores gaps apos o ultimo ponto", loc="left", fontsize=14, fontweight="bold")
            ax.grid(axis="x", color="#d5e5ee", linewidth=0.8)
        pdf.savefig(fig, facecolor=fig.get_facecolor())
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        ax.axis("off")
        fig.patch.set_facecolor("#f4f8fb")
        outside = cibele_points[cibele_points["fora_presenca_fisica"]].head(25) if not cibele_points.empty else cibele_points
        ax.text(0.03, 0.95, "Cibele: pontos fora dos intervalos fisicos", fontsize=15, fontweight="bold", color="#142235")
        if outside.empty:
            ax.text(0.03, 0.86, "Nao foram encontrados pontos fora de presenca fisica.", fontsize=11, color="#5b7088")
        else:
            cols = ["data", "hora_ponto", "motivo_presenca", "diferenca", "manual_oficial", "planta", "descricao_coletor"]
            view = outside[[c for c in cols if c in outside.columns]].copy()
            view["data"] = pd.to_datetime(view["data"]).dt.strftime("%d/%m/%Y")
            ax.text(0.03, 0.88, view.to_string(index=False), family="monospace", fontsize=6.7, color="#142235", va="top")
        pdf.savefig(fig, facecolor=fig.get_facecolor())
        plt.close(fig)


def build_presence_outputs(people, all_rows):
    summaries = []
    daily_frames = []
    point_frames = []
    raw_frames = []

    for cadastro, person in people.items():
        rows = all_rows[all_rows["cadastro"].astype("string").str.strip().eq(cadastro)].copy()
        daily, points, raw = analyze_person_presence(rows, person)
        outside = (
            points[
                points["fora_presenca_fisica"]
                & points["beneficio_ponto_fora_min"].fillna(0).gt(0)
            ].copy()
            if not points.empty
            else points
        )
        gap_days = daily[daily["gap_apos_ponto_maior_1h"]].copy() if not daily.empty else daily

        summaries.append(
            {
                **person,
                "pontos_fora_presenca": int(len(outside)),
                "pontos_fora_manual_sim": int(outside["manual_oficial"].astype(str).str.upper().eq("SIM").sum())
                if not outside.empty
                else 0,
                "pontos_fora_planta_999": int(outside["planta"].astype(str).str.strip().eq("999").sum())
                if not outside.empty
                else 0,
                "dias_gap_apos_ponto_1h": int(len(gap_days)),
                "horas_gap_apos_ponto": round(float(gap_days["beneficio_gap_min"].fillna(0).sum()) / 60.0, 2)
                if not gap_days.empty
                else 0.0,
                "horas_pontos_fora_presenca": round(float(outside["beneficio_ponto_fora_min"].fillna(0).sum()) / 60.0, 2)
                if not outside.empty
                else 0.0,
                "maior_ponto_fora_min": round(float(outside["minutos_ate_presenca_fisica"].max()), 2)
                if not outside.empty
                else np.nan,
                "maior_gap_apos_ponto_min": round(float(gap_days["min_apos_ultimo_ponto"].max()), 2)
                if not gap_days.empty
                else np.nan,
                "total_cenarios": int(len(outside) + len(gap_days)),
            }
        )

        if not gap_days.empty:
            daily_frames.append(gap_days)
        if not outside.empty:
            point_frames.append(outside)
        if not raw.empty:
            raw_frames.append(raw)

    summary = pd.DataFrame(summaries)
    if not summary.empty:
        summary["nome_total"] = summary.apply(
            lambda row: (
                f"{row['nome']} | total {int(row['total_cenarios'])} cenarios | "
                f"{float(row['horas_gap_apos_ponto']):.1f}h gap"
            ),
            axis=1,
        )
        summary = summary.sort_values(
            ["total_cenarios", "horas_gap_apos_ponto", "pontos_fora_presenca"],
            ascending=False,
        )

    daily_scenarios = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    point_scenarios = pd.concat(point_frames, ignore_index=True) if point_frames else pd.DataFrame()
    raw_all = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame()
    return summary, daily_scenarios, point_scenarios, raw_all


def build_area_resumo(person_summary):
    with_scenarios = person_summary[person_summary["total_cenarios"].gt(0)] if not person_summary.empty else person_summary
    return pd.DataFrame(
        [
            {
                "item": "Colaboradores B-VSP avaliados",
                "valor": int(len(person_summary)),
                "leitura": "Pessoas com area registrada iniciando por B-VSP.",
            },
            {
                "item": "Colaboradores com cenario",
                "valor": int(len(with_scenarios)),
                "leitura": "Tem ponto fora da presenca fisica ou gap apos ultimo ponto maior que 1h.",
            },
            {
                "item": "Total de cenarios",
                "valor": int(with_scenarios["total_cenarios"].sum()) if not with_scenarios.empty else 0,
                "leitura": "Soma de pontos fora da presenca e dias com gap apos ponto.",
            },
            {
                "item": "Pontos fora em planta 999",
                "valor": int(with_scenarios["pontos_fora_planta_999"].sum()) if not with_scenarios.empty else 0,
                "leitura": "Capturas digitais/home office fora da presenca fisica.",
            },
            {
                "item": "Horas gap apos ultimo ponto",
                "valor": round(float(with_scenarios["horas_gap_apos_ponto"].sum()), 2) if not with_scenarios.empty else 0,
                "leitura": "Soma dos cenarios em que a saida fisica ficou mais de 1h depois do ultimo ponto.",
            },
        ]
    )


def y_axis_from_minutes(ax, values):
    values = pd.Series(values).dropna().astype(float)
    if values.empty:
        values = pd.Series([8 * 60, 18 * 60], dtype=float)
    y_min = max(0, np.floor((values.min() - 45) / 30) * 30)
    y_max = min(24 * 60, np.ceil((values.max() + 45) / 30) * 30)
    if y_max <= y_min:
        y_max = y_min + 120
    ticks = np.arange(y_min, y_max + 1, 60)
    ax.set_ylim(y_max, y_min)
    ax.set_yticks(ticks)
    ax.set_yticklabels([minute_label(v) for v in ticks], fontsize=8)


def plot_person_scenarios(pdf, person_row, daily_scenarios, point_scenarios):
    cad = str(person_row["cadastro"])
    name = str(person_row["nome"])
    total = int(person_row["total_cenarios"])
    person_daily = daily_scenarios[daily_scenarios["cadastro"].astype(str).eq(cad)].copy() if not daily_scenarios.empty else pd.DataFrame()
    person_points = point_scenarios[point_scenarios["cadastro"].astype(str).eq(cad)].copy() if not point_scenarios.empty else pd.DataFrame()

    fig, (ax, axp) = plt.subplots(1, 2, figsize=(11.7, 8.3), gridspec_kw={"width_ratios": [3.2, 1.2]})
    fig.patch.set_facecolor("#f4f8fb")
    ax.set_facecolor("#ffffff")
    axp.axis("off")

    y_values = []
    if not person_daily.empty:
        person_daily = person_daily.sort_values("beneficio_gap_min", ascending=False).head(TOP_DIAS_PDF)
        person_daily["ultimo_ponto_min"] = person_daily["ultimo_ponto"].map(minute_from_any)
        person_daily["ultima_saida_min"] = person_daily["ultima_saida_fisica"].map(minute_from_any)
        y_values.extend(person_daily["ultimo_ponto_min"].dropna().tolist())
        y_values.extend(person_daily["ultima_saida_min"].dropna().tolist())
        ax.scatter(
            person_daily["data"],
            person_daily["ultimo_ponto_min"],
            s=28,
            color="#89CFF0",
            edgecolors="#155C87",
            linewidth=0.35,
            alpha=0.84,
            label="Ultimo ponto",
        )
        ax.scatter(
            person_daily["data"],
            person_daily["ultima_saida_min"],
            s=30,
            color="#c83b32",
            edgecolors="#7c1f19",
            linewidth=0.35,
            alpha=0.85,
            label="Saida fisica",
        )

    if not person_points.empty:
        person_points = person_points.sort_values("beneficio_ponto_fora_min", ascending=False).head(TOP_DIAS_PDF)
        person_points["ponto_min"] = person_points["hora_ponto"].map(minute_from_any)
        y_values.extend(person_points["ponto_min"].dropna().tolist())
        home = person_points["planta"].astype(str).str.strip().eq("999")
        if (~home).any():
            ax.scatter(
                person_points.loc[~home, "data"],
                person_points.loc[~home, "ponto_min"],
                s=46,
                color="#B23A8C",
                edgecolors="#5A1C45",
                linewidth=0.55,
                alpha=0.92,
                label="Ponto fora",
            )
        if home.any():
            ax.scatter(
                person_points.loc[home, "data"],
                person_points.loc[home, "ponto_min"],
                s=54,
                color="#F2A65A",
                edgecolors="#9A4F00",
                linewidth=0.7,
                alpha=0.96,
                label="Home office / planta 999",
            )

    ax.set_title(f"{name} | total {total} cenarios", loc="left", fontsize=14, fontweight="bold", color="#142235")
    ax.set_xlabel("Dias com cenario")
    ax.set_ylabel("Horario")
    if not person_daily.empty or not person_points.empty:
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=8))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m/%y"))
        plt.setp(ax.get_xticklabels(), rotation=35, ha="right", fontsize=8)
    y_axis_from_minutes(ax, y_values)
    ax.grid(True, axis="both", color="#d5e5ee", linewidth=0.8)
    ax.legend(loc="upper left", frameon=True, facecolor="#ffffff", edgecolor="#d5e5ee", fontsize=8)
    for spine in ax.spines.values():
        spine.set_visible(False)

    axp.text(0.02, 0.96, "Resumo", fontsize=13, fontweight="bold", color="#142235", va="top")
    y = 0.88
    metrics = [
        ("Area", person_row.get("area", "")),
        ("Cargo", person_row.get("cargo", "")),
        ("Pontos fora", int(person_row["pontos_fora_presenca"])),
        ("Planta 999", int(person_row["pontos_fora_planta_999"])),
        ("Dias gap >1h", int(person_row["dias_gap_apos_ponto_1h"])),
        ("Horas gap", f"{float(person_row['horas_gap_apos_ponto']):.1f}h"),
        ("registro_manual=Sim fora", int(person_row["pontos_fora_manual_sim"])),
    ]
    for label, value in metrics:
        axp.text(0.02, y, label, fontsize=8.4, color="#5b7088", va="top")
        axp.text(0.98, y, str(value), fontsize=8.7, fontweight="bold", color="#1764a5", va="top", ha="right")
        y -= 0.062

    y -= 0.035
    axp.text(0.02, y, "Maiores cenarios", fontsize=10.5, fontweight="bold", color="#142235", va="top")
    y -= 0.060
    if not person_points.empty:
        for row in person_points.head(5).itertuples(index=False):
            axp.text(0.02, y, f"{pd.Timestamp(row.data):%d/%m/%Y} {row.hora_ponto}", fontsize=7.4, color="#142235", va="top")
            axp.text(0.98, y, row.diferenca, fontsize=7.4, color="#1764a5", fontweight="bold", ha="right", va="top")
            y -= 0.048
            axp.text(0.02, y, f"{row.motivo_presenca} | planta {row.planta}", fontsize=6.8, color="#5b7088", va="top")
            y -= 0.052
            if y < 0.16:
                break
    if y >= 0.16 and not person_daily.empty:
        for row in person_daily.head(4).itertuples(index=False):
            axp.text(0.02, y, f"{pd.Timestamp(row.data):%d/%m/%Y}", fontsize=7.4, color="#142235", va="top")
            axp.text(0.98, y, duration_label(row.beneficio_gap_min), fontsize=7.4, color="#1764a5", fontweight="bold", ha="right", va="top")
            y -= 0.048
            axp.text(0.02, y, f"ultimo ponto {row.ultimo_ponto} -> saida {row.ultima_saida_fisica}", fontsize=6.8, color="#5b7088", va="top")
            y -= 0.052
            if y < 0.12:
                break

    fig.tight_layout(rect=[0.02, 0.04, 0.98, 0.96])
    pdf.savefig(fig, facecolor=fig.get_facecolor())
    plt.close(fig)


def write_area_pdf(area_resumo, person_summary, daily_scenarios, point_scenarios):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUT_PDF) as pdf:
        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        fig.patch.set_facecolor("#f4f8fb")
        ax.axis("off")
        ax.text(0.03, 0.95, "B-VSP | cenarios de aproveitamento", fontsize=18, fontweight="bold", color="#142235")
        ax.text(0.03, 0.90, "Apenas pontos fora da presenca fisica e gaps relevantes apos o ultimo ponto.", fontsize=10, color="#5b7088")
        y = 0.82
        for row in area_resumo.itertuples(index=False):
            ax.text(0.04, y, str(row.item), fontsize=9, color="#5b7088")
            ax.text(0.42, y, str(row.valor), fontsize=13, fontweight="bold", color="#1764a5")
            ax.text(0.55, y, str(row.leitura), fontsize=8.2, color="#142235")
            y -= 0.065

        view_cols = ["nome_total", "cadastro", "area", "cargo", "pontos_fora_presenca", "dias_gap_apos_ponto_1h"]
        view = person_summary[[c for c in view_cols if c in person_summary.columns]].head(12).copy()
        y -= 0.04
        ax.text(0.04, y, "Ranking por colaborador", fontsize=12, fontweight="bold", color="#142235")
        y -= 0.045
        ax.text(0.04, y, view.to_string(index=False), family="monospace", fontsize=7.2, color="#142235", va="top")
        pdf.savefig(fig, facecolor=fig.get_facecolor())
        plt.close(fig)

        for _, row in person_summary[person_summary["total_cenarios"].gt(0)].iterrows():
            plot_person_scenarios(pdf, row, daily_scenarios, point_scenarios)


def write_person_pdfs(person_summary, daily_scenarios, point_scenarios):
    OUT_PEOPLE_DIR.mkdir(parents=True, exist_ok=True)
    for old_pdf in OUT_PEOPLE_DIR.glob("*.pdf"):
        old_pdf.unlink()
    for _, row in person_summary[person_summary["total_cenarios"].gt(0)].iterrows():
        total = int(row["total_cenarios"])
        filename = f"{row['cadastro']}_{safe_filename(row['nome'])}_total_{total}_cenarios.pdf"
        path = OUT_PEOPLE_DIR / filename
        with PdfPages(path) as pdf:
            plot_person_scenarios(pdf, row, daily_scenarios, point_scenarios)


def main():
    if not BASE.exists():
        raise FileNotFoundError(f"Base nao encontrada: {BASE}")

    manual_module = load_validando_module()
    people = find_focus_people()
    all_rows = load_rows_for_people(people)
    manual_summary, manual_cases = build_manual_summary(people, all_rows, manual_module)
    presence_summary, daily_scenarios, point_scenarios, raw_all = build_presence_outputs(people, all_rows)
    area_resumo = build_area_resumo(presence_summary)

    tables = {
        "resumo": area_resumo,
        "ranking_B-VSP": presence_summary,
        "manual_fora_B-VSP": manual_cases,
        "pontos_fora_presenca": point_scenarios,
        "dias_gap_apos_ponto": daily_scenarios,
        "parametros": pd.DataFrame(
            [
                {
                    "area_prefixo": f"{AREA_FOCO}*",
                    "cargo": CARGO_FOCO or "todos",
                    "periodo_inicio": PERIOD_START,
                    "periodo_fim": PERIOD_END,
                    "criterio_manual_oficial": "registro_manual=Sim, tipo Ponto, fora de home office/remoto, antes da entrada fisica ou apos saida fisica.",
                    "criterio_ponto_fora_presenca": "Descricao com PONTO/MARCA fora dos intervalos montados por portaria fisica real, excluindo planta 999 como presenca.",
                    "criterio_gap": f"Somente dias com mais de {GAP_MINIMO_MIN} minutos entre ultimo ponto e ultima saida fisica.",
                    "observacao": "Os graficos mostram apenas cenarios de aproveitamento; nao conectam dias com linhas.",
                    "base": str(BASE),
                }
            ]
        ),
    }
    if not raw_all.empty:
        tables["registros_base_B-VSP"] = raw_all[
            [
                c
                for c in [
                    "cadastro",
                    "nome",
                    "data_corrigida",
                    "hora",
                    "dir",
                    "tipo",
                    "acesso",
                    "planta",
                    "coletor",
                    "descricao_coletor",
                    "uso_acesso",
                    "area",
                    "cargo",
                    "registro_manual",
                ]
                if c in raw_all.columns
            ]
        ].copy()

    write_excel(tables)
    write_area_pdf(area_resumo, presence_summary, daily_scenarios, point_scenarios)
    write_person_pdfs(presence_summary, daily_scenarios, point_scenarios)

    print(f"Excel: {OUT_XLSX}")
    print(f"PDF: {OUT_PDF}")
    print(area_resumo.to_string(index=False))
    print(presence_summary[["cadastro", "nome", "area", "cargo", "total_cenarios", "pontos_fora_presenca", "dias_gap_apos_ponto_1h", "horas_gap_apos_ponto"]].to_string(index=False))


if __name__ == "__main__":
    main()
